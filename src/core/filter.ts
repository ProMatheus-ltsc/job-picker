/**
 * 筛选/轮次/画像（05 §4.5 契约；demo roundList 唯一口径出口原样迁移）
 * 口径（M2 三次反馈最终定论）：画像过滤作用于所有轮次；
 * 任一轮次名单 = 链式基础名单（初筛=全量、后续轮=上一轮晋级者）∩ 画像过滤。
 */
import type { Filters, Job, Profile, SortKey } from '../types';
import { num } from '../types';
import { err, ok, type Result } from '../types';
import { calcRatio, calcTotal } from './scoring';

/** 学历等级映射（Q-D8） */
const DEGREE_LEVEL: Record<string, number> = { 大专: 1, 本科: 2, 硕士: 3, 博士: 4 };

/**
 * 岗位学历要求 → 最低学历等级；0 = 不限/无法识别（不限制）
 * 「大专/大专以上/大专及以上」→1；「本科/本科以上/本科及以上/本科及以下」→2；
 * 「硕士/硕士研究生/研究生」→3；「博士/博士及以上」→4；「大专或本科」并提按较低口径计。
 */
export function parseDegreeLevel(text: string | null): 0 | 1 | 2 | 3 | 4 {
  const s = String(text ?? '').replace(/\s/g, '');
  if (!s || /不限|无/.test(s)) return 0;
  const hasDa = /大专|专科|中专|高中/.test(s);
  const hasBen = /本科|学士|大学/.test(s);
  if (s.includes('博士')) return 4;
  if (s.includes('硕士') || s.includes('研究生')) return 3;
  if (hasDa && hasBen) return 1;
  if (hasBen) return 2;
  if (hasDa) return 1;
  return 0;
}

/** 画像是否生效（degree 或 regions 任一设置） */
export function profileActive(profile: Profile): boolean {
  return !!(profile && (profile.degree || profile.regions.length));
}

/**
 * F-11 强过滤：学历要求等级 ≤ 考生学历，且考区在意向范围内（两条件独立生效）
 */
export function applyProfile(list: Job[], profile: Profile): Job[] {
  if (!profile || (!profile.degree && !profile.regions.length)) return list;
  const my = profile.degree ? (DEGREE_LEVEL[profile.degree] ?? 99) : 99;
  return list.filter((j) => {
    if (profile.degree && parseDegreeLevel(j.degree) > my) return false;
    if (profile.regions.length && !profile.regions.includes(String(j.region ?? '').trim())) return false;
    return true;
  });
}

/** 链式基础名单：r=0 → 全量；r>0 → 上一轮晋级者 */
export function getRoundBase(r: number, jobs: Job[]): Job[] {
  if (r === 0) return jobs.slice();
  return jobs.filter((j) => j.marks[r - 1] === 'promote');
}

/**
 * 所有轮次的唯一名单口径出口（Q-D9）
 * Tab 徽标/统计条/表格/导出四处消费点必须统一走本函数，禁止各自实现。
 */
export function roundList(r: number, jobs: Job[], profile: Profile): Job[] {
  return applyProfile(getRoundBase(r, jobs), profile);
}

/** F-04 组合筛选（各条件交集）；区间倒置 → E_RANGE_INVALID */
export function applyFilters(list: Job[], filters: Filters): Result<Job[]> {
  if (
    filters.applyMin != null &&
    filters.applyMax != null &&
    filters.applyMin > filters.applyMax
  ) {
    return err('E_RANGE_INVALID', '区间倒置：最小值大于最大值');
  }
  const f = filters;
  return ok(list.filter((j) => {
    if (f.region && String(j.region ?? '') !== f.region) return false;
    if (f.degree && String(j.degree ?? '') !== f.degree) return false;
    if (f.majorKeyword && !String(j.major ?? '').toLowerCase().includes(f.majorKeyword.toLowerCase()))
      return false;
    const a = num(j.applicants);
    if (f.applyMin != null && (a == null || a < f.applyMin)) return false;
    if (f.applyMax != null && (a == null || a > f.applyMax)) return false;
    return true;
  }));
}

const SORTABLE: Record<SortKey, boolean> = {
  applicants: true,
  hires: true,
  ratio: true,
  avgIncome: true,
  netIncome: true,
  incomeScore: true,
  netScore: true,
  total: true,
};

export function isSortable(key: string): key is SortKey {
  return !!SORTABLE[key as SortKey];
}

function sortVal(j: Job, key: SortKey): number | null {
  if (key === 'ratio') return calcRatio(j.applicants, j.hires);
  if (key === 'total') return calcTotal(j);
  return num(j[key]);
}

/** 数值排序；空值排尾；稳定排序（Array.prototype.sort） */
export function sortJobs(list: Job[], key: SortKey, dir: 'asc' | 'desc'): Job[] {
  return list.slice().sort((a, b) => {
    const va = sortVal(a, key);
    const vb = sortVal(b, key);
    const na = va == null || isNaN(va);
    const nb = vb == null || isNaN(vb);
    if (na && nb) return 0;
    if (na) return 1;
    if (nb) return -1;
    return dir === 'desc' ? vb - va : va - vb;
  });
}
