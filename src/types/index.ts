/**
 * 业务类型定义（05-api-doc §3 数据结构契约的 TS 化）
 * Job 字段命名遵循契约：applicants/hires（demo 的 applyCount/hireCount 迁移时更名）
 */

/** 统一结果结构（05 §1.1） */
export type Result<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };

export function ok<T>(data: T): Result<T> {
  return { ok: true, data };
}

export function err<T = never>(code: string, message: string): Result<T> {
  return { ok: false, error: { code, message } };
}

/** 轮次三态标记（05 §3.4） */
export type MarkStatus = 'pending' | 'promote' | 'eliminate';

/** 源表数据（05 §3.2） */
export interface RawTable {
  sheetName: string | null;
  columns: string[];
  rows: (string | null)[][];
}

/** 13 标准字段定义（F-02 列映射目标，demo FIELDS 原样迁移） */
export interface FieldDef {
  key: StandardFieldKey;
  name: string;
  required?: boolean;
}

export type StandardFieldKey =
  | 'code'
  | 'unit'
  | 'title'
  | 'avgIncome'
  | 'netIncome'
  | 'incomeScore'
  | 'netScore'
  | 'applicants'
  | 'hires'
  | 'region'
  | 'degree'
  | 'major'
  | 'intro';

export const FIELDS: FieldDef[] = [
  { key: 'code', name: '岗位代码', required: true },
  { key: 'unit', name: '招聘单位', required: true },
  { key: 'title', name: '招考职位' },
  { key: 'avgIncome', name: '平均收入(万)' },
  { key: 'netIncome', name: '到手收入(万)' },
  { key: 'incomeScore', name: '收入打分' },
  { key: 'netScore', name: '到手收入打分' },
  { key: 'applicants', name: '报名人数' },
  { key: 'hires', name: '录用人数' },
  { key: 'region', name: '考区' },
  { key: 'degree', name: '学历' },
  { key: 'major', name: '专业要求' },
  { key: 'intro', name: '职位简介' },
];

/** 列映射：标准字段 → 源列索引（05 §3.3，demo 的列名口径迁移为索引口径） */
export type Mapping = Partial<Record<StandardFieldKey, number | null>>;

/** 考生画像（05 §3.6） */
export interface Profile {
  degree: '' | '大专' | '本科' | '硕士' | '博士';
  regions: string[];
}

/** 岗位记录（05 §3.4） */
export interface Job {
  code: string;
  unit: string;
  title: string;
  avgIncome: number | null;
  netIncome: number | null;
  incomeScore: number | null;
  netScore: number | null;
  applicants: number | null;
  hires: number | null;
  region: string;
  degree: string;
  major: string;
  intro: string;
  remark: string;
  marks: MarkStatus[];
}

/** 内存态筛选条件（05 §3.8，不持久化） */
export interface Filters {
  region: string;
  degree: string;
  majorKeyword: string;
  applyMin: number | null;
  applyMax: number | null;
}

export type SortKey =
  | 'applicants'
  | 'hires'
  | 'ratio'
  | 'avgIncome'
  | 'netIncome'
  | 'incomeScore'
  | 'netScore'
  | 'total';

export interface SortState {
  key: SortKey;
  dir: 'asc' | 'desc';
}

/** 内存态全量业务状态（loadState 组装出参，05 §3.1） */
export interface AppState {
  schemaVersion: number;
  source: 'demo' | 'file';
  importedAt: string;
  raw: RawTable;
  mapping: Mapping;
  remarkCols: number[];
  rounds: string[];
  profile: Profile;
  jobs: Job[];
}

export const DEFAULT_ROUNDS = ['初筛', '二次筛选', '三次筛选', '最终'];

export function emptyProfile(): Profile {
  return { degree: '', regions: [] };
}

export function emptyFilters(): Filters {
  return { region: '', degree: '', majorKeyword: '', applyMin: null, applyMax: null };
}

/** AI 回填条目（05 §3.9） */
export interface AiEntry {
  unit: string;
  avgIncome: number;
  netIncome: number;
  note: string;
}

export interface ApplyAiSummary {
  unitCount: number;
  updatedCount: number;
  matchedUnits: string[];
  unmatchedUnits: string[];
  invalidEntries: unknown[];
}

/** 数值解析（demo num() 原样迁移：空/非数字 → null） */
export function num(v: string | number | null | undefined): number | null {
  if (v === '' || v == null) return null;
  const n = +v;
  return isNaN(n) ? null : n;
}
