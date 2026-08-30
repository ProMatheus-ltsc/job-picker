/**
 * 应用根组件 — 内存路由装配 + 业务全量状态管理（04 §6.1/§6.2）
 * - MemoryRouter：地址栏不变（PRD「路由均为 /」口径）；/welcome /import 全屏，/ 进 Layout 壳
 * - state（AppState|null）持有业务全量；更新经 updateState/mutateJobs 统一持久化（IndexedDB）
 * - 不引入全局状态库：状态提升至本组件，经 props 下发
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { ToastProvider, useToast } from '@shared/core/hooks/useToast';
import { ToastContainer } from '@shared/core/components/Toast';
import { ConfirmDialog } from '@shared/core/components/ConfirmDialog';
import { LoadingSpinner } from '@shared/core/components/LoadingSpinner';
import type { AppState, Job, Mapping, RawTable } from './types';
import { DEFAULT_ROUNDS, emptyProfile } from './types';
import { saveState, clearState } from './core/store';
import { buildJobs } from './core/mapping';
import { DEMO_MAPPING, DEMO_RAW, DEMO_REMARK_COLS } from './core/demoData';
import { parseCsv, rawToCsv, parseCsvRows } from './io/parseCsv';
import { parseXlsx } from './io/parseXlsx';
import { Welcome } from './ui/Welcome';
import { Wizard, type ImportPayload } from './ui/Wizard';
import { MainView } from './ui/MainView';

function AppInner({ initialState }: { initialState: AppState | null }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [state, setState] = useState<AppState | null>(initialState);
  const [pendingImport, setPendingImport] = useState<ImportPayload | null>(null);
  const [parsing, setParsing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  /* ---------- 持久化更新 ---------- */
  const updateState = useCallback((next: AppState) => {
    setState(next);
  }, []);

  /**
   * 原地修改 jobs 的更新入口（行内打分/报名人数/标记共用）：
   * 不可变更新（新数组 + 新 job 对象 + 拷贝 marks），保证 memo 行组件与 useMemo 派生值正确刷新
   */
  const mutateJobs = useCallback((fn: (jobs: Job[]) => void) => {
    setState((prev) => {
      if (!prev) return prev;
      const jobs = prev.jobs.map((j) => ({ ...j, marks: [...j.marks] }));
      fn(jobs);
      return { ...prev, jobs };
    });
  }, []);

  // 状态变化统一持久化（IndexedDB；失败 toast 不静默，F-10 规则 4）
  useEffect(() => {
    if (!state) return;
    void saveState(state).then((r) => {
      if (!r.ok) showToast(r.error.message, 'error');
    });
  }, [state, showToast]);

  /* ---------- 导入入口 ---------- */

  /** 演示数据一键导入（V1 入口） */
  const handleLoadDemo = useCallback(() => {
    const built = buildJobs(DEMO_RAW, DEMO_MAPPING, DEMO_REMARK_COLS, DEFAULT_ROUNDS.length);
    if (!built.ok) {
      showToast(built.error.message, 'error');
      return;
    }
    updateState({
      schemaVersion: 1,
      source: 'demo',
      importedAt: new Date().toISOString(),
      raw: DEMO_RAW,
      mapping: DEMO_MAPPING,
      remarkCols: DEMO_REMARK_COLS,
      rounds: DEFAULT_ROUNDS.slice(),
      profile: emptyProfile(),
      jobs: built.data.jobs,
    });
    navigate('/');
    showToast(`已加载 ${built.data.jobs.length} 条演示岗位数据（2026 省考结构，含样例岗位 10200312658008 总分 0.93）`);
  }, [navigate, showToast, updateState]);

  /** 演示 CSV 体验完整导入向导（V1 入口） */
  const handleDemoCsv = useCallback(() => {
    const csv = rawToCsv(DEMO_RAW);
    const rows = parseCsvRows(csv);
    setPendingImport({ fileName: '演示数据-2026省考.csv', csvRows: rows });
    navigate('/import');
    showToast('已生成演示 CSV 并进入导入向导（走真实 CSV 解析流程）');
  }, [navigate, showToast]);

  /** 触发文件选择（CSV / .xlsx；已有数据时解析成功后二次确认覆盖导入 Q-D7） */
  const handlePickFile = useCallback(() => {
    fileRef.current?.click();
  }, []);

  const handleFileChosen = useCallback(
    async (file: File) => {
      setParsing(true);
      try {
        if (/\.xlsx?$/i.test(file.name) && !/\.xls$/i.test(file.name)) {
          const buffer = await file.arrayBuffer();
          const parsed = await parseXlsx(buffer);
          if (!parsed.ok) {
            showToast(parsed.error.message, 'error');
            return;
          }
          const payload: ImportPayload = { fileName: file.name, xlsxSheets: parsed.data.sheets };
          setPendingImport(payload);
          if (state) {
            setConfirmOverwrite(true); // 已有数据 → 覆盖导入确认
          } else {
            navigate('/import');
          }
        } else {
          const text = await file.text();
          const parsed = parseCsv(text);
          if (!parsed.ok) {
            showToast(parsed.error.message, 'error');
            return;
          }
          const payload: ImportPayload = {
            fileName: file.name,
            csvRows: [parsed.data.columns, ...parsed.data.rows.map((r) => r.map((c) => c ?? ''))],
          };
          setPendingImport(payload);
          if (state) {
            setConfirmOverwrite(true);
          } else {
            navigate('/import');
          }
        }
      } finally {
        setParsing(false);
      }
    },
    [navigate, showToast, state],
  );

  /** 重新映射（V3 顶栏；保留数据，恢复源表值，标记按岗位代码保留 F-02 规则 8） */
  const handleRemap = useCallback(() => {
    if (!state) return;
    setPendingImport({
      fileName: '当前数据',
      csvRows: [state.raw.columns, ...state.raw.rows.map((r) => r.map((c) => c ?? ''))],
      remap: true,
    });
    navigate('/import');
  }, [navigate, state]);

  /** 向导完成回调（Wizard 组装 raw/mapping/remarkCols，App 负责状态组装与持久化） */
  const handleImportComplete = useCallback(
    (raw: RawTable, mapping: Mapping, remarkCols: number[]) => {
      const prev = pendingImport?.remap && state ? state : null;
      const rounds = prev ? prev.rounds : DEFAULT_ROUNDS.slice();
      const built = buildJobs(
        raw,
        mapping,
        remarkCols,
        rounds.length,
        prev ? new Map(prev.jobs.map((j) => [j.code, j.marks])) : undefined,
      );
      if (!built.ok) {
        showToast(built.error.message, 'error');
        return;
      }
      if (!built.data.jobs.length) {
        showToast('没有有效岗位（岗位代码/招聘单位为空）', 'error');
        return;
      }
      updateState({
        schemaVersion: 1,
        source: prev ? prev.source : 'file',
        importedAt: new Date().toISOString(),
        raw,
        mapping,
        remarkCols,
        rounds,
        profile: prev ? prev.profile : emptyProfile(),
        jobs: built.data.jobs,
      });
      setPendingImport(null);
      navigate('/');
      showToast(
        `导入完成：${built.data.jobs.length} 个岗位` +
          (built.data.skipped ? `，跳过 ${built.data.skipped} 行无效数据` : ''),
      );
    },
    [navigate, pendingImport, showToast, state, updateState],
  );

  /** 清空数据（F-10；ConfirmDialog 二次确认后执行） */
  const handleClear = useCallback(async () => {
    await clearState();
    setState(null);
    setPendingImport(null);
    setConfirmClear(false);
    navigate('/welcome');
    showToast('已清空本地数据，回到初始状态');
  }, [navigate, showToast]);

  const handleWizardCancel = useCallback(() => {
    setPendingImport(null);
    navigate(state ? '/' : '/welcome');
  }, [navigate, state]);

  return (
    <div className="min-h-dvh">
      {parsing ? (
        <LoadingSpinner message="正在解析文件，请稍候…" />
      ) : (
        <Routes>
          <Route
            path="/welcome"
            element={
              <Welcome
                onLoadDemo={handleLoadDemo}
                onPickFile={handlePickFile}
                onDemoCsv={handleDemoCsv}
              />
            }
          />
          <Route
            path="/import"
            element={
              pendingImport ? (
                <Wizard
                  payload={pendingImport}
                  currentRounds={state?.rounds ?? DEFAULT_ROUNDS.slice()}
                  onComplete={handleImportComplete}
                  onCancel={handleWizardCancel}
                />
              ) : (
                <Welcome
                  onLoadDemo={handleLoadDemo}
                  onPickFile={handlePickFile}
                  onDemoCsv={handleDemoCsv}
                />
              )
            }
          />
          <Route
            path="/"
            element={
              state ? (
                <MainView
                  state={state}
                  updateState={updateState}
                  mutateJobs={mutateJobs}
                  onRemap={handleRemap}
                  onReimport={handlePickFile}
                  onClear={() => setConfirmClear(true)}
                />
              ) : (
                <Welcome
                  onLoadDemo={handleLoadDemo}
                  onPickFile={handlePickFile}
                  onDemoCsv={handleDemoCsv}
                />
              )
            }
          />
        </Routes>
      )}

      {/* 隐藏文件选择（CSV / .xlsx 统一入口） */}
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,text/csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = '';
          if (f) void handleFileChosen(f);
        }}
      />

      {/* 清空数据二次确认（F-10，variant=danger） */}
      <ConfirmDialog
        open={confirmClear}
        title="清空本地数据"
        message="将删除本地存储中的岗位数据与轮次标记，回到初始导入页面（F-10）。此操作不可恢复，确定继续？"
        confirmText="清空数据"
        variant="danger"
        onConfirm={() => void handleClear()}
        onCancel={() => setConfirmClear(false)}
      />

      {/* 覆盖导入二次确认（Q-D7） */}
      <ConfirmDialog
        open={confirmOverwrite}
        title="覆盖导入"
        message="导入新文件将替换当前全部岗位数据、轮次标记与考生画像（Q-D7）。确定继续？"
        confirmText="覆盖导入"
        variant="danger"
        onConfirm={() => {
          setConfirmOverwrite(false);
          navigate('/import');
        }}
        onCancel={() => {
          setConfirmOverwrite(false);
          setPendingImport(null);
        }}
      />
    </div>
  );
}

export function App({ initialState }: { initialState: AppState | null }) {
  const entry = initialState ? '/' : '/welcome';
  return (
    <MemoryRouter initialEntries={[entry]}>
      <ToastProvider>
        <AppInner initialState={initialState} />
        <ToastContainer />
      </ToastProvider>
    </MemoryRouter>
  );
}
