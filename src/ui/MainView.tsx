/**
 * V3 主界面（Layout 壳内，04 §6.1）：
 * 顶栏工具行 + 轮次 Tab + 统计条 + 筛选栏 + 岗位表格（TableScroll）+ V7 页脚
 * 名单口径唯一出口 roundList（Q-D9）；三类空态（无匹配/空轮次/画像空态）复用 EmptyState
 */
import { useMemo, useState } from 'react';
import { ClipboardList, FileInput, RefreshCcw, Trash2, UserCog, Download } from 'lucide-react';
import { Layout, EmptyState } from '@shared/core';
import { useToast } from '@shared/core/hooks/useToast';
import type { AiEntry, AppState, ApplyAiSummary, Filters, Job, MarkStatus, SortState } from '../types';
import { emptyFilters } from '../types';
import { applyAiResults } from '../core/aiFill';
import { applyFilters, getRoundBase, profileActive, roundList, sortJobs } from '../core/filter';
import { RoundsTabs } from './RoundsTabs';
import { FiltersBar } from './FiltersBar';
import { JobTable } from './JobTable';
import { ProfileDialog } from './ProfileDialog';
import { AiDialog } from './AiDialog';
import { ExportDialog } from './ExportDialog';
import { FormulaFooter } from './FormulaFooter';

interface Props {
  state: AppState;
  updateState: (s: AppState) => void;
  mutateJobs: (fn: (jobs: Job[]) => void) => void;
  onRemap: () => void;
  onReimport: () => void;
  onClear: () => void;
}

export function MainView({ state, updateState, mutateJobs, onRemap, onReimport, onClear }: Props) {
  const { showToast } = useToast();
  const [round, setRound] = useState(0);
  const [filters, setFilters] = useState<Filters>(emptyFilters());
  const [sort, setSort] = useState<SortState>({ key: 'total', dir: 'desc' });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [profileOpen, setProfileOpen] = useState(false);
  const [aiCode, setAiCode] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);

  const cur = Math.min(round, state.rounds.length - 1);

  /** AI 收入分析目标岗位（逐岗位分析：按钮位于初筛每行的「初筛标记」后一列，Q-D4 修订） */
  const aiTarget = useMemo(
    () => (aiCode ? state.jobs.find((j) => j.code === aiCode) ?? null : null),
    [state.jobs, aiCode],
  );

  /* ---------- 名单口径（roundList 唯一出口，Q-D9） ---------- */
  const counts = useMemo(
    () => state.rounds.map((_, r) => roundList(r, state.jobs, state.profile).length),
    [state.rounds, state.jobs, state.profile],
  );
  const roundBase = useMemo(() => getRoundBase(cur, state.jobs), [cur, state.jobs]);
  const roundJobs = useMemo(() => roundList(cur, state.jobs, state.profile), [cur, state.jobs, state.profile]);

  const rangeInvalid =
    filters.applyMin != null && filters.applyMax != null && filters.applyMin > filters.applyMax;

  /** 筛选（区间倒置时不发起筛选，F-04 规则 4）+ 排序叠加 */
  const viewJobs = useMemo(() => {
    let list = roundJobs;
    if (!rangeInvalid) {
      const r = applyFilters(roundJobs, filters);
      list = r.ok ? r.data : roundJobs;
    }
    return sortJobs(list, sort.key, sort.dir);
  }, [roundJobs, filters, rangeInvalid, sort]);

  /** 筛选下拉选项：当前数据去重值 */
  const regions = useMemo(
    () => Array.from(new Set(state.jobs.map((j) => j.region).filter(Boolean))).sort(),
    [state.jobs],
  );
  const degrees = useMemo(
    () => Array.from(new Set(state.jobs.map((j) => j.degree).filter(Boolean))).sort(),
    [state.jobs],
  );

  /* ---------- 操作 ---------- */
  const handleSort = (key: SortState['key']) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }));
  };

  const toggleExpand = (code: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const handleSetMark = (code: string, mark: MarkStatus) =>
    mutateJobs((jobs) => {
      const j = jobs.find((x) => x.code === code);
      if (j) j.marks[cur] = mark;
    });

  const handleEditScore = (code: string, field: 'incomeScore' | 'netScore', value: number) =>
    mutateJobs((jobs) => {
      const j = jobs.find((x) => x.code === code);
      if (j) j[field] = value;
    });

  const handleEditApplicants = (code: string, value: number | null) =>
    mutateJobs((jobs) => {
      const j = jobs.find((x) => x.code === code);
      if (j) j.applicants = value;
    });

  const handleAddRound = () => {
    const name = window.prompt('新增轮次名称（追加在现有轮次之后）：', `第${state.rounds.length + 1}轮`);
    if (!name || !name.trim()) return;
    const rounds = [...state.rounds, name.trim()];
    updateState({
      ...state,
      rounds,
      jobs: state.jobs.map((j) => ({ ...j, marks: [...j.marks, 'pending'] })),
    });
    setRound(rounds.length - 1);
    showToast(`已新增轮次「${name.trim()}」`);
  };

  const handleSaveProfile = (p: AppState['profile']) => {
    updateState({ ...state, profile: p });
    const active = profileActive(p);
    showToast(active ? '考生画像已保存，所有轮次已按画像强过滤' : '已清除考生画像，恢复全量显示');
  };

  /** AI 回填：副本上应用得到摘要，再整体持久化（F-07 规则 6） */
  const handleAiApply = (entries: AiEntry[]): ApplyAiSummary => {
    // 不可变拷贝（含 marks），与 mutateJobs 模式一致（CR-002）
    const copy = state.jobs.map((j) => ({ ...j, marks: [...j.marks] }));
    const summary = applyAiResults(copy, entries);
    updateState({ ...state, jobs: copy });
    return summary;
  };

  /* ---------- 统计条 ---------- */
  const stats = useMemo(() => {
    let pending = 0;
    let promote = 0;
    let eliminate = 0;
    roundJobs.forEach((j) => {
      const m = j.marks[cur] ?? 'pending';
      if (m === 'promote') promote++;
      else if (m === 'eliminate') eliminate++;
      else pending++;
    });
    return { pending, promote, eliminate };
  }, [roundJobs, cur]);
  const profileOn = profileActive(state.profile);

  return (
    <Layout
      appConfig={{ name: '公考选岗筛选工具', icon: ClipboardList }}
      navItems={[{ to: '/', icon: ClipboardList, label: '岗位列表', end: true }]}
      enableSearch={false}
      user={{ username: '本地' }}
      storageKey="job-picker-nav-expanded"
    >
      {/* 顶栏工具行 */}
      <div className="mv-head">
        <div className="mv-title">
          <h2 style={{ margin: 0, fontSize: 18 }}>岗位列表</h2>
          <span className="mv-meta">
            已导入 <b>{state.jobs.length}</b> 个岗位 · 来源：
            {state.source === 'demo' ? '演示数据' : '文件导入'} ·{' '}
            {new Date(state.importedAt).toLocaleString()}
          </span>
        </div>
        <div className="jp-btns">
          <button className="jp-btn" onClick={onReimport}>
            <FileInput size={13} className="mr-1 inline align-[-2px]" />
            导入数据
          </button>
          <button className="jp-btn" onClick={onRemap}>
            <RefreshCcw size={13} className="mr-1 inline align-[-2px]" />
            列映射
          </button>
          <button className="jp-btn" onClick={() => setProfileOpen(true)}>
            <UserCog size={13} className="mr-1 inline align-[-2px]" />
            考生画像{profileOn ? '（生效中）' : ''}
          </button>
          <button className="jp-btn" onClick={() => setExportOpen(true)}>
            <Download size={13} className="mr-1 inline align-[-2px]" />
            导出名单
          </button>
          <button className="jp-btn danger" onClick={onClear}>
            <Trash2 size={13} className="mr-1 inline align-[-2px]" />
            清空数据
          </button>
        </div>
      </div>

      {/* 轮次 Tab（徽标 = 画像过滤后人数） */}
      <RoundsTabs rounds={state.rounds} current={cur} counts={counts} onSelect={setRound} onAdd={handleAddRound} />

      {/* 统计条 */}
      <div className="stats-wrap">
        <span>
          <b>{state.rounds[cur]}</b>：
        </span>
        <span className="st-pend">待定 {stats.pending}</span>
        <span className="st-pro">晋级 {stats.promote}</span>
        <span className="st-eli">淘汰 {stats.eliminate}</span>
        <span className="stats-profile">
          画像过滤后 <b>{roundJobs.length}</b> 个
          {roundBase.length !== roundJobs.length && `（链式名单 ${roundBase.length} 个）`}
        </span>
        {profileOn && (
          <button className="jp-btn sm" onClick={() => setProfileOpen(true)}>
            去设置
          </button>
        )}
      </div>

      {/* 筛选栏 */}
      <FiltersBar filters={filters} regions={regions} degrees={degrees} rangeInvalid={rangeInvalid} onChange={setFilters} />

      {/* 三类空态（F-05 规则 5 / F-11 规则 7 / F-05 规则 UI-01） */}
      {roundBase.length === 0 && cur > 0 ? (
        <div className="jp-card">
          <EmptyState
            title={`「${state.rounds[cur]}」为空轮次`}
            description={`上一轮「${state.rounds[cur - 1]}」还没有标记晋级的岗位，先去上一轮标记晋级者。`}
            action={
              <button className="jp-btn primary" onClick={() => setRound(cur - 1)}>
                去上一轮「{state.rounds[cur - 1]}」标记
              </button>
            }
          />
        </div>
      ) : roundJobs.length === 0 && roundBase.length > 0 ? (
        <div className="jp-card">
          <EmptyState
            title="链式名单非空，但被考生画像过滤为空"
            description={`当前画像（${
              state.profile.degree ? `学历 ${state.profile.degree}` : '学历不限'
            }${
              state.profile.regions.length ? ` · 意向考区 ${state.profile.regions.join('、')}` : ' · 考区不限'
            }）下没有可显示岗位；不符合画像的岗位仅被隐藏，标记数据保留。`}
            action={
              <button className="jp-btn primary" onClick={() => setProfileOpen(true)}>
                调整考生画像
              </button>
            }
          />
        </div>
      ) : viewJobs.length === 0 ? (
        <div className="jp-card">
          <EmptyState
            title="当前筛选条件下没有匹配岗位"
            description={`共 ${roundJobs.length} 个可见岗位，均不满足当前筛选条件（考区/学历/专业关键词/报名区间）。`}
            action={
              <button className="jp-btn" onClick={() => setFilters(emptyFilters())}>
                清除筛选条件
              </button>
            }
          />
        </div>
      ) : (
        <JobTable
          jobs={viewJobs}
          mapping={state.mapping}
          round={cur}
          roundName={state.rounds[cur]}
          sort={sort}
          onSort={handleSort}
          expanded={expanded}
          onToggleExpand={toggleExpand}
          onSetMark={handleSetMark}
          onEditScore={handleEditScore}
          onEditApplicants={handleEditApplicants}
          onAiScan={setAiCode}
        />
      )}

      <FormulaFooter />

      <ProfileDialog
        open={profileOpen}
        profile={state.profile}
        regions={regions}
        onSave={handleSaveProfile}
        onClose={() => setProfileOpen(false)}
      />
      {aiTarget && (
        <AiDialog open onClose={() => setAiCode(null)} jobs={[aiTarget]} onApply={handleAiApply} />
      )}
      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        viewJobs={viewJobs}
        mapping={state.mapping}
        remarkCols={state.remarkCols}
        rounds={state.rounds}
        round={cur}
      />
    </Layout>
  );
}
