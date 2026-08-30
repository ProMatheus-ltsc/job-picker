/**
 * V3 岗位表格（F-03/F-05/F-08）— TableScroll 包裹宽表格（04 §6.3）
 * - 列 = 已映射标准字段 + 报录比 + 总分 + 当前轮次标记；8 列可排序（空值排尾，稳定排序）
 * - 行内编辑：收入打分/到手收入打分（F-03 规则 5）、报名人数（F-08，非负校验、空值黄底提示）
 * - 三态标记（当前轮次）；行点击展开详情（公式代入式 + 备注 + 全字段）
 */
import { memo, useEffect, useRef, useState } from 'react';
import { TableScroll } from '@shared/core';
import { useToast } from '@shared/core/hooks/useToast';
import { FIELDS, type Job, type Mapping, type MarkStatus, type SortState } from '../types';
import { calcRatio, calcTotal, fnum, formulaExpression, totalDisplay } from '../core/scoring';
import { isSortable } from '../core/filter';

type CellKey = string; // StandardFieldKey | 'ratio' | 'total' | '_mark'

interface Props {
  jobs: Job[]; // 当前视图（轮次 ∩ 画像 ∩ 筛选 ∩ 排序）
  mapping: Mapping;
  round: number;
  roundName: string;
  sort: SortState;
  onSort: (key: SortState['key']) => void;
  expanded: Set<string>;
  onToggleExpand: (code: string) => void;
  onSetMark: (code: string, mark: MarkStatus) => void;
  onEditScore: (code: string, field: 'incomeScore' | 'netScore', value: number) => void;
  onEditApplicants: (code: string, value: number | null) => void;
  /** 逐岗位 AI 收入分析：点击某行按钮打开该岗位的分析对话框（F-07，Q-D4 修订） */
  onAiScan: (code: string) => void;
}

const MARK_BTNS: Array<{ v: MarkStatus; label: string }> = [
  { v: 'pending', label: '待定' },
  { v: 'promote', label: '晋级' },
  { v: 'eliminate', label: '淘汰' },
];

export function JobTable(props: Props) {
  const { jobs, mapping, sort, onSort } = props;

  const cols: Array<{ key: CellKey; name: string; sortable: boolean }> = [
    ...FIELDS.filter((f) => mapping[f.key] != null).map((f) => ({
      key: f.key,
      name: f.name,
      sortable: isSortable(f.key),
    })),
    { key: 'ratio', name: '报录比', sortable: true },
    { key: 'total', name: '总分', sortable: true },
    { key: '_mark', name: `${props.roundName}标记`, sortable: false },
    // AI 收入分析：仅初筛（第 0 轮）展示，位于「初筛标记」后一列（一个岗位一个岗位分析）
    ...(props.round === 0
      ? [{ key: '_ai' as CellKey, name: 'AI 收入分析', sortable: false }]
      : []),
  ];

  const arrow = (key: CellKey) =>
    sort.key === key ? <span className="arr">{sort.dir === 'desc' ? '▼' : '▲'}</span> : null;

  return (
    <div className="jp-card" style={{ padding: 0, overflow: 'hidden' }}>
      <TableScroll label="岗位列表">
        <table className="job-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c.key}
                  className={c.sortable ? 'sortable' : undefined}
                  aria-sort={sort.key === c.key ? (sort.dir === 'desc' ? 'descending' : 'ascending') : undefined}
                  onClick={c.sortable ? () => onSort(c.key as SortState['key']) : undefined}
                >
                  {c.name}
                  {arrow(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <JobRow key={j.code} job={j} cols={cols} {...props} />
            ))}
          </tbody>
        </table>
      </TableScroll>
    </div>
  );
}

/* ---------- 单行（memo 化，1000 行级渲染口径 §6.3） ---------- */

interface RowProps {
  job: Job;
  cols: Array<{ key: CellKey; name: string; sortable: boolean }>;
  round: number;
  sort: SortState;
  expanded: Set<string>;
  onSort: (key: SortState['key']) => void;
  onToggleExpand: (code: string) => void;
  onSetMark: (code: string, mark: MarkStatus) => void;
  onEditScore: (code: string, field: 'incomeScore' | 'netScore', value: number) => void;
  onEditApplicants: (code: string, value: number | null) => void;
  onAiScan: (code: string) => void;
}

const JobRow = memo(function JobRow({
  job,
  cols,
  round,
  expanded,
  onToggleExpand,
  onSetMark,
  onEditScore,
  onEditApplicants,
  onAiScan,
}: RowProps) {
  const mark = job.marks[round] ?? 'pending';
  const isOpen = expanded.has(job.code);

  /** 行点击展开（点击按钮/输入框等交互元素不触发） */
  const onRowClick = (e: React.MouseEvent<HTMLTableRowElement>) => {
    const t = e.target as HTMLElement;
    if (t.closest('button, input, select, a, textarea')) return;
    onToggleExpand(job.code);
  };

  const cell = (key: CellKey) => {
    switch (key) {
      case 'code':
        return <span className="code-cell">{job.code}</span>;
      case 'title':
        return (
          <>
            {job.title || '—'}
            {job.remark && (
              <span className="remark-badge" title={job.remark}>
                备
              </span>
            )}
          </>
        );
      case 'avgIncome':
        return fnum(job.avgIncome, 2);
      case 'netIncome':
        return fnum(job.netIncome, 2);
      case 'incomeScore':
        return (
          <ScoreEdit
            value={job.incomeScore}
            onCommit={(v) => onEditScore(job.code, 'incomeScore', v)}
          />
        );
      case 'netScore':
        return <ScoreEdit value={job.netScore} onCommit={(v) => onEditScore(job.code, 'netScore', v)} />;
      case 'applicants':
        return (
          <ApplicantsEdit
            value={job.applicants}
            onCommit={(v) => onEditApplicants(job.code, v)}
          />
        );
      case 'hires':
        return fnum(job.hires, 0);
      case 'ratio': {
        const r = calcRatio(job.applicants, job.hires);
        return fnum(r, 1);
      }
      case 'total':
        return <span className="total-cell">{totalDisplay(calcTotal(job))}</span>;
      case '_mark':
        return <MarksCell mark={mark} onSet={(m) => onSetMark(job.code, m)} />;
      case '_ai':
        return (
          <button
            type="button"
            className="jp-btn ai-scan-btn"
            title="用 AI 分析该岗位的收入并回填"
            onClick={() => onAiScan(job.code)}
          >
            AI 分析
          </button>
        );
      default:
        return String((job as unknown as Record<string, unknown>)[key] ?? '') || '—';
    }
  };

  return (
    <>
      <tr
        className={`job-row mark-${mark}`}
        onClick={onRowClick}
        aria-expanded={isOpen}
      >
        {cols.map((c) => (
          <td key={c.key} className={isNumericCell(c.key) ? 'num' : undefined}>
            {cell(c.key)}
          </td>
        ))}
      </tr>
      {isOpen && (
        <tr className="row-detail">
          <td colSpan={cols.length}>
            <div className="detail-grid">
              <div>
                <b>招聘单位：</b>
                {job.unit}
              </div>
              <div>
                <b>招考职位：</b>
                {job.title || '—'}
              </div>
              <div>
                <b>考区：</b>
                {job.region || '—'}
              </div>
              <div>
                <b>学历：</b>
                {job.degree || '—'}
              </div>
              <div>
                <b>专业要求：</b>
                {job.major || '—'}
              </div>
              {job.intro && (
                <div>
                  <b>职位简介：</b>
                  {job.intro}
                </div>
              )}
            </div>
            {job.remark && (
              <div className="detail-grid" style={{ marginTop: 4 }}>
                <div style={{ gridColumn: '1 / -1' }}>
                  <b>备注：</b>
                  <span className="remark-text">{job.remark}</span>
                </div>
              </div>
            )}
            <div className="formula-line">总分代入式：{formulaExpression(job)}</div>
          </td>
        </tr>
      )}
    </>
  );
});

/** 三态标记按钮（F-05 规则 3：即时生效，可撤销） */
function MarksCell({ mark, onSet }: { mark: MarkStatus; onSet: (m: MarkStatus) => void }) {
  return (
    <span className="marks">
      {MARK_BTNS.map((b) => (
        <button
          key={b.v}
          className={`${b.v}${mark === b.v ? ' on' : ''}`}
          onClick={() => onSet(b.v)}
          title={b.label}
        >
          {b.label}
        </button>
      ))}
    </span>
  );
}

/** 打分行内编辑（F-03 规则 5：点击变输入框；回车/失焦保存、Esc 取消；非法输入恢复原值） */
function ScoreEdit({ value, onCommit }: { value: number | null; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (draft !== null) inputRef.current?.select();
  }, [draft]);

  const commit = () => {
    if (draft === null) return;
    const n = parseFloat(draft);
    if (!isNaN(n)) onCommit(n);
    setDraft(null);
  };

  if (draft !== null) {
    return (
      <input
        ref={inputRef}
        className="score-input"
        value={draft}
        inputMode="decimal"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setDraft(null);
        }}
      />
    );
  }
  return (
    <span
      className="score-view"
      title="点击修改打分"
      style={{ cursor: 'text', display: 'inline-block', minWidth: 40 }}
      onClick={() => setDraft(String(value ?? ''))}
    >
      {fnum(value, 0)}
    </span>
  );
}

/** 报名人数行内编辑（F-08：非负校验；空值 null 黄底提示「空值按 0 参与计算」） */
function ApplicantsEdit({
  value,
  onCommit,
}: {
  value: number | null;
  onCommit: (v: number | null) => void;
}) {
  const { showToast } = useToast();
  const [draft, setDraft] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (draft !== null) inputRef.current?.select();
  }, [draft]);

  const commit = () => {
    if (draft === null) return;
    const t = draft.trim();
    if (t === '') {
      onCommit(null); // 置空：按 0 参与计算（黄底提示）
    } else {
      const n = parseFloat(t);
      if (isNaN(n) || n < 0) {
        // 非法输入（负数/非数字）恢复原值并报错（F-08 规则 2）
        showToast('报名人数需为非负数，已恢复原值', 'error');
      } else {
        onCommit(n);
      }
    }
    setDraft(null);
  };

  if (draft !== null) {
    return (
      <input
        ref={inputRef}
        className="apply-input"
        value={draft}
        inputMode="numeric"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setDraft(null);
        }}
      />
    );
  }
  return (
    <span
      className={value == null ? 'apply-empty-val' : undefined}
      style={{ cursor: 'text', display: 'inline-block', minWidth: 40 }}
      title={value == null ? '报名人数为空：按 0 参与计算（点击填写）' : '点击修改报名人数'}
      onClick={() => setDraft(value == null ? '' : String(value))}
    >
      {fnum(value, 0)}
    </span>
  );
}

function isNumericCell(key: CellKey): boolean {
  return [
    'avgIncome',
    'netIncome',
    'incomeScore',
    'netScore',
    'applicants',
    'hires',
    'ratio',
    'total',
  ].includes(key);
}
