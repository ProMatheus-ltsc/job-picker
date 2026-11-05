/**
 * 工作强度筛查（选岗硬筛）
 *
 * 背景：2026-11-04 一次真实选岗里，**用一句话筛掉 433 岗里的 265 个（61%）**：
 * 职位简介含「值班/夜间/执法/应急/三防/消防/信访/一线/处突/适合男性」一律排除。
 * 这是当天收益最大的单项能力，而 job-picker 原先的 `eligibility.ts` 只查**报考资格**，
 * 完全不查**工作强度**。
 *
 * ★ 铁律（当天踩过的坑）：**必须扫职位简介，不能只扫结构化字段。**
 * 实测 50 个岗里有 5 个综合卷岗位的「职位简介」写着"三防/消防/应急"，却被标成无强度——
 * 因为它们把信号藏在自由文本里，而结构化字段（机构性质/职位类型）看起来完全正常。
 *
 * 因此扫描范围固定为三字段：intro（职位简介）、title（招考职位）、remark（其他要求）。
 */

import type { Job } from '../types';

export type IntensityLevel = 'none' | 'light' | 'heavy';

export type IntensityCategory =
  | 'duty' // 值班类
  | 'enforce' // 执法类
  | 'emergency' // 应急类
  | 'petition' // 信访类
  | 'travel' // 出差类
  | 'gender'; // 性别类（本身是强度信号，不只是性别限制）

export interface IntensityLexicon {
  duty: string[];
  enforce: string[];
  emergency: string[];
  petition: string[];
  travel: string[];
  gender: string[];
}

/** 默认词表（可被调用方整体或部分覆盖） */
export const DEFAULT_LEXICON: IntensityLexicon = {
  duty: ['值班', '24小时', '夜间', '轮班', '值守'],
  enforce: ['执法', '执勤', '巡查', '一线', '处突'],
  emergency: ['应急', '三防', '消防', '救援', '防汛', '森林防火'],
  petition: ['信访', '接访', '维稳'],
  travel: ['驻外', '出差', '常驻'],
  gender: ['适合男性'],
};

/** 扫描字段 → Job 属性名（顺序即报告展示顺序） */
const SCAN_FIELDS: Array<{ field: 'intro' | 'title' | 'remark'; key: keyof Job }> = [
  { field: 'intro', key: 'intro' },
  { field: 'title', key: 'title' },
  { field: 'remark', key: 'remark' },
];

export interface IntensityHit {
  /** 命中的关键词 */
  kw: string;
  /** 命中字段 */
  field: 'intro' | 'title' | 'remark';
  /** 所属类别 */
  category: IntensityCategory;
  /** 命中处周围的一小段原文（便于人工复核） */
  text: string;
}

export interface IntensityResult {
  level: IntensityLevel;
  hits: IntensityHit[];
}

/** 直接判 heavy 的类别：执法与应急意味着不可协商的工作形态 */
const HEAVY_CATEGORIES: IntensityCategory[] = ['duty', 'enforce', 'emergency'];

/** 只判 light 的类别：出差/信访/性别是提示性信号 */
const LIGHT_CATEGORIES: IntensityCategory[] = ['petition', 'travel', 'gender'];

/** 把可选的用户词表与默认词表合并：显式传空数组视为"未配置"，回退默认 */
export function mergeLexicon(custom?: Partial<IntensityLexicon>): IntensityLexicon {
  const merged = { ...DEFAULT_LEXICON };
  if (!custom) return merged;
  (Object.keys(DEFAULT_LEXICON) as IntensityCategory[]).forEach((key) => {
    const list = custom[key];
    if (Array.isArray(list) && list.length) {
      merged[key] = list.slice();
    }
  });
  return merged;
}

/** 取命中位置周围的上下文片段（最多 24 字，便于报告展示） */
function contextOf(text: string, index: number, length: number): string {
  const start = Math.max(0, index - 8);
  const end = Math.min(text.length, index + length + 8);
  return text.slice(start, end).replace(/\s+/g, ' ').trim();
}

/**
 * 扫描单个岗位的工作强度。
 *
 * 判定规则（与改造方案 §五 P0-3 一致）：
 * - 命中 duty / enforce / emergency 任一类别 → `heavy`（值班即不可接受，执法与应急同理）；
 * - 仅命中 petition / travel / gender → `light`（提示性信号，交人工判断）；
 * - 无命中 → `none`。
 *
 * 同一关键词在多个字段命中时**每个字段各记一条**，因为报告需要指出"信号藏在哪个字段"。
 */
export function scanIntensity(job: Job, custom?: Partial<IntensityLexicon>): IntensityResult {
  const lexicon = mergeLexicon(custom);
  const hits: IntensityHit[] = [];

  for (const { field, key } of SCAN_FIELDS) {
    const raw = String((job as unknown as Record<string, unknown>)[key] ?? '');
    if (!raw) continue;
    for (const category of Object.keys(lexicon) as IntensityCategory[]) {
      for (const kw of lexicon[category]) {
        const index = raw.indexOf(kw);
        if (index < 0) continue;
        hits.push({
          kw,
          field,
          category,
          text: contextOf(raw, index, kw.length),
        });
      }
    }
  }

  let level: IntensityLevel = 'none';
  if (hits.some((h) => HEAVY_CATEGORIES.includes(h.category))) {
    level = 'heavy';
  } else if (hits.some((h) => LIGHT_CATEGORIES.includes(h.category))) {
    level = 'light';
  }
  return { level, hits };
}

/** heavy 是否应排除出候选（选岗默认排除，可用 keepHeavy 反向保留） */
export function isExcludedByIntensity(result: IntensityResult): boolean {
  return result.level === 'heavy';
}

/** 命中类别的中文标签（报告展示用） */
export const CATEGORY_LABEL: Record<IntensityCategory, string> = {
  duty: '值班',
  enforce: '执法',
  emergency: '应急',
  petition: '信访',
  travel: '出差',
  gender: '性别',
};

/** 一句话摘要，如「heavy：值班(职位简介)、执法(招考职位)」 */
export function intensitySummary(result: IntensityResult): string {
  if (!result.hits.length) return '无强度信号';
  const parts: string[] = [];
  for (const hit of result.hits) {
    const item = `${CATEGORY_LABEL[hit.category]}(${hit.field})`;
    if (!parts.includes(item)) parts.push(item);
  }
  return `${result.level}：${parts.join('、')}`;
}
