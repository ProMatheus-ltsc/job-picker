/**
 * 岗位竞争激烈度评估（选岗对比用）
 *
 * ⚠️ 方法说明（重要）：
 * 国考职位表**不含报名人数**，报名期（10/15 8:00 起）官方才逐日公布。
 * 因此本模块给出的是**事前预估**（ex-ante），依据报名前就能从表里读到的三类客观信息：
 *
 *   A. 报考池大小（40 分）—— 门槛越宽松，符合条件的人越多，池子越大、竞争越激烈
 *   B. 地区热度（30 分）—— 一线/新一线吸引力强，同岗位报名人数天然更多
 *   C. 招录规模（30 分）—— 招 1 人 vs 招 3 人，在报名人数相近时报录比差 3 倍
 *
 * 再用「额外门槛」（英语等级、法律职业资格、加试专业、性别/户籍限制）做减分修正。
 *
 * 报名开始后，请把官方公布的报名人数填进表格的「报名人数」列 ——
 * 那时工具里的**报录比**才是真实竞争度，本预估仅用于**报名前的取舍排序**。
 */
import type { Job } from '../types';

export type CompetitionLevel = '极激烈' | '激烈' | '中等' | '相对缓和';

export interface CompetitionFactor {
  /** 维度名 */
  label: string;
  /** 得分 */
  score: number;
  /** 该维度满分 */
  max: number;
  /** 判定依据（展示用） */
  note: string;
}

export interface CompetitionResult {
  /** 竞争激烈度指数 0~100，越高越激烈 */
  score: number;
  level: CompetitionLevel;
  /** 拆解明细 */
  factors: CompetitionFactor[];
  /** 报考池规模定性 */
  pool: '极大' | '大' | '中' | '小';
  /** 一句话结论 */
  hint: string;
  /** 历史报录比参考值（省份基准 × 区位系数推算；**参考量级，非预测**） */
  ratioRef: number;
  /** 历史报录比依据说明 */
  ratioBasis: string;
  /** 进面分参考区间（依据 2026 国考税务系统实测分布） */
  cutoffRef: string;
}

/**
 * 分省竞争比基准（**2026 国考税务系统实测**，来源：国家公务员局报名系统统计）
 * 用途：给「竞争度指数」提供真实量级锚点——指数只用于排序，量级要看这里。
 */
const PROVINCE_BASE: Array<{ re: RegExp; ratio: number; label: string }> = [
  { re: /上海|北京/, ratio: 136, label: '直辖市局 2026 实测' },
  { re: /浙江/, ratio: 59, label: '浙江省局 58.78:1（2026）' },
  { re: /江苏/, ratio: 58, label: '江苏省局 58.3:1（2026）' },
  { re: /湖南|辽宁/, ratio: 55, label: '省局 2026 实测' },
  { re: /河北|四川/, ratio: 70, label: '省局 2026 实测' },
  { re: /湖北/, ratio: 74, label: '湖北省局 74.25:1（2026）' },
  { re: /江西|河南/, ratio: 86, label: '省局 2026 实测' },
  { re: /山东/, ratio: 91, label: '山东省局 91.44:1（2026）' },
  { re: /广东/, ratio: 99, label: '广东省局 99.21:1（2026）' },
  { re: /福建/, ratio: 104, label: '福建省局 103.88:1（2026）' },
  { re: /广西/, ratio: 117, label: '广西区局 117.48:1（2026）' },
  { re: /陕西/, ratio: 124, label: '陕西省局 123.7:1（2026）｜2025 峰值 133.9:1' },
  { re: /云南/, ratio: 124, label: '云南省局 124:1（2026）' },
  { re: /贵州/, ratio: 134, label: '贵州省局 134.38:1（2025）' },
];
const DEFAULT_BASE = { ratio: 95, label: '税务系统全国平均 95:1（2026）' };

/**
 * 区位系数：同一省内，越靠近中心城市竞争越激烈（实测规律）
 * 依据：2026 陕西税务——西安市区岗最高 869:1、县城岗最低 947:1 与低于均值并存；
 *       进面分「越靠近市区越高」（西安新城区 139.6 分 vs 子长市 104.2 分）。
 */
function areaFactor(region: string): { f: number; label: string } {
  const r = String(region ?? '');
  if (/北京|上海|深圳|广州/.test(r)) return { f: 1.5, label: '一线城市' };
  if (/[市省]\S*?区$/.test(r) || /开发区|高新区|新区/.test(r)) return { f: 1.3, label: '城区' };
  if (/县|乡镇|旗/.test(r)) return { f: 0.6, label: '县域' };
  return { f: 0.85, label: '地级市' };
}

/** 进面分参考（依据 2026 国考税务系统实测：最高 139.6 / 最低 104.2） */
function cutoffRef(region: string): string {
  const r = String(region ?? '');
  if (/北京|上海|深圳|广州/.test(r)) return '135–142';
  if (/[市省]\S*?区$/.test(r) || /开发区|高新区|新区/.test(r)) return '130–140';
  if (/县|乡镇|旗/.test(r)) return '104–122';
  return '118–132';
}

/** 报考池/热度 → 竞争指数所用的城市热度（保持与分省基准一致的排序逻辑） */
const HOT_CITIES: Array<{ re: RegExp; score: number; label: string }> = [
  { re: /深圳|广州|北京|上海/, score: 30, label: '一线城市' },
  { re: /杭州|南京|苏州|成都|武汉|重庆|西安|天津|厦门|青岛|长沙|合肥|郑州|济南/, score: 24, label: '省会/新一线' },
  { re: /宁波|东莞|佛山|珠海|无锡|温州|福州|昆明|贵阳|南昌|太原|石家庄|大连|沈阳|哈尔滨|长春/, score: 18, label: '强二线' },
  { re: /绍兴|嘉兴|金华|台州|湖州|中山|惠州|江门|汕头|扬州|泉州|烟台|潍坊|常州|南通|徐州|洛阳/, score: 12, label: '普通地级市' },
  { re: /县|乡镇|自治县|旗/, score: 5, label: '县域/乡镇' },
];

const DEFAULT_HOT = { score: 14, label: '其他地市' };

/** 学历门槛 → 池子贡献（越宽松分越高） */
function degreeScore(degreeText: string): { score: number; note: string } {
  const d = String(degreeText ?? '');
  if (!d || /不限/.test(d)) return { score: 12, note: '学历不限，池子最大' };
  if (/大专|专科/.test(d) && !/本科/.test(d)) return { score: 12, note: '大专及以上即可' };
  if (/博士/.test(d) && !/硕士|本科/.test(d)) return { score: 1, note: '仅限博士' };
  if (/硕士|研究生/.test(d) && !/本科.*及以上/.test(d)) return { score: 3, note: '限硕士及以上' };
  return { score: 10, note: '本科及以上' };
}

/** 政治面貌 → 池子贡献 */
function politicalScore(text: string): { score: number; note: string } {
  const s = String(text ?? '');
  if (!s || /不限/.test(s)) return { score: 10, note: '政治面貌不限' };
  if (/中共党员/.test(s) && /共青团员/.test(s)) return { score: 4, note: '限党员或团员' };
  if (/中共党员/.test(s) || /党员/.test(s)) return { score: 1, note: '仅限中共党员' };
  return { score: 10, note: '政治面貌不限' };
}

/** 基层经历 → 池子贡献（要求年限 = 缩小池子） */
function grassrootsScore(text: string): { score: number; note: string } {
  const s = String(text ?? '');
  if (!s || /无限制|不限|无要求|不要求|^无$/.test(s)) return { score: 10, note: '无基层经历要求' };
  if (/应届/.test(s)) return { score: 6, note: '面向应届毕业生' };
  const m = s.match(/(\d+|[一二三四五六七八九十])\s*年/);
  if (m) return { score: 2, note: `要求 ${s.replace(/\s/g, '')}` };
  return { score: 6, note: '身份有附加要求' };
}

/** 专业范围 → 池子贡献（列举的专业大类越多，符合的人越多） */
function majorScore(majorText: string): { score: number; note: string } {
  const s = String(majorText ?? '').replace(/\s/g, '');
  if (!s || /不限|无限制/.test(s)) return { score: 8, note: '专业不限' };
  const segs = s.split(/[,，、;；/／]/).filter(Boolean).length;
  if (segs >= 4) return { score: 8, note: `专业面宽（${segs} 类）` };
  if (segs >= 2) return { score: 5, note: `专业面中（${segs} 类）` };
  return { score: 2, note: '专业限定较窄' };
}

/** 额外门槛减分（门槛越多，能报的人越少） */
function extraPenalty(job: Job): { score: number; notes: string[] } {
  const txt = `${job.remark ?? ''} ${job.intro ?? ''}`;
  const notes: string[] = [];
  let p = 0;
  if (/英语六级|六级|雅思|托福|大学英语|英语专业/.test(txt)) {
    p += 12;
    notes.push('英语等级要求（−12）');
  }
  if (/法律职业资格|司法考试|法考/.test(txt)) {
    p += 10;
    notes.push('法律职业资格证（−10）');
  }
  if (/加试|专业能力测试|专业测试|业务水平测试/.test(txt)) {
    p += 8;
    notes.push('需加试专业（−8）');
  }
  if (/限男性|限女性|男性|女性/.test(txt)) {
    p += 5;
    notes.push('性别限制（−5）');
  }
  if (/户籍|本地户口|生源/.test(txt)) {
    p += 6;
    notes.push('户籍/生源限制（−6）');
  }
  if (/体能测评|体能测试|体测/.test(txt)) {
    p += 4;
    notes.push('需体测（−4）');
  }
  return { score: p, notes };
}

/** 招录规模 → 竞争度（招得越少，报录比越高） */
function hiresScore(hires: number | null | undefined): { score: number; note: string } {
  const n = typeof hires === 'number' && hires > 0 ? hires : null;
  if (n == null) return { score: 18, note: '招录人数未知' };
  if (n === 1) return { score: 30, note: '仅招 1 人，容错率最低' };
  if (n === 2) return { score: 20, note: '招 2 人' };
  if (n === 3) return { score: 12, note: '招 3 人' };
  return { score: 6, note: `招 ${n} 人，规模较大` };
}

function toLevel(score: number): CompetitionLevel {
  if (score >= 72) return '极激烈';
  if (score >= 58) return '激烈';
  if (score >= 44) return '中等';
  return '相对缓和';
}

function toPool(score: number): CompetitionResult['pool'] {
  if (score >= 32) return '极大';
  if (score >= 24) return '大';
  if (score >= 16) return '中';
  return '小';
}

/** 单岗位竞争激烈度评估 */
export function estimateCompetition(job: Job): CompetitionResult {
  const deg = degreeScore(job.degree);
  const pol = politicalScore(job.politicalStatus);
  const gra = grassrootsScore(job.grassrootsYears ?? job.freshRequired);
  const maj = majorScore(job.major);
  const pool = deg.score + pol.score + gra.score + maj.score; // 0~40

  const hot = HOT_CITIES.find((h) => h.re.test(job.region ?? '')) ?? DEFAULT_HOT;
  const hir = hiresScore(job.hires);
  const pen = extraPenalty(job);

  const raw = pool + hot.score + hir.score - pen.score;
  const score = Math.max(0, Math.min(100, Math.round(raw)));

  const factors: CompetitionFactor[] = [
    { label: '报考池', score: pool, max: 40, note: `${deg.note}；${pol.note}；${gra.note}；${maj.note}` },
    { label: '地区热度', score: hot.score, max: 30, note: `${hot.label}（${job.region || '未标注'}）` },
    { label: '招录规模', score: hir.score, max: 30, note: hir.note },
  ];
  if (pen.score) {
    factors.push({ label: '门槛减分', score: -pen.score, max: 0, note: pen.notes.join('；') });
  }

  const level = toLevel(score);
  const hint =
    pen.score >= 10
      ? '额外门槛显著收窄了报考人群，实际竞争会低于同城同类岗位'
      : level === '极激烈' || level === '激烈'
        ? '门槛宽松 + 地区热门，预计报名人数偏高'
        : '门槛或地区消化了一部分报名需求';

  // 真实量级锚点：省份基准 × 区位系数（参考值，非预测）
  const hit = PROVINCE_BASE.find((b) => b.re.test(job.region ?? ''));
  const base: { ratio: number; label: string } = hit ?? DEFAULT_BASE;
  const area = areaFactor(job.region);
  const ratioRef = Math.round(base.ratio * area.f);

  return {
    score,
    level,
    factors,
    pool: toPool(pool),
    hint,
    ratioRef,
    ratioBasis: `${base.label} × ${area.label}系数 ${area.f}`,
    cutoffRef: cutoffRef(job.region),
  };
}

/** 批量评估（保持输入顺序） */
export function competitionTable(jobs: Job[]): Array<{ job: Job; comp: CompetitionResult }> {
  return jobs.map((job) => ({ job, comp: estimateCompetition(job) }));
}

/** 竞争度徽标样式用的短标签 */
export function competitionShort(level: CompetitionLevel): string {
  return level === '极激烈' ? '★★★★' : level === '激烈' ? '★★★' : level === '中等' ? '★★' : '★';
}

/**
 * 额外硬门槛：不是资格审查的 fail 项，但决定「你实际能不能报」。
 * （表里写在备注/职位简介，审核时按岗执行）
 */
export function hardGates(job: Job): string[] {
  const txt = `${job.remark ?? ''} ${job.intro ?? ''}`;
  const g: string[] = [];
  if (/英语六级|六级|雅思|托福|大学英语|英语专业/.test(txt)) g.push('英语等级');
  if (/法律职业资格|司法考试|法考/.test(txt)) g.push('法考证书');
  if (/加试|专业能力测试|专业测试|业务水平测试/.test(txt)) g.push('加试专业');
  if (/限男性|限女性|男性|女性/.test(txt)) g.push('性别限制');
  if (/户籍|本地户口|生源/.test(txt)) g.push('户籍限制');
  return g;
}

/**
 * 推荐指数（0.5~5 星）：性价比（买房年数）+ 竞争度 + 招录规模 的合成。
 * 这是**排序用途**，不是绝对评价——权重可按个人偏好调整。
 */
export function recommendStar(yearsForHousing: number, compScore: number, hires: number | null): number {
  let s = 3;
  if (yearsForHousing <= 6) s += 1;
  else if (yearsForHousing <= 9) s += 0.5;
  else if (yearsForHousing >= 20) s -= 1.5;
  else if (yearsForHousing >= 14) s -= 1;
  if (compScore <= 45) s += 1;
  else if (compScore <= 58) s += 0.5;
  else if (compScore >= 85) s -= 1.5;
  else if (compScore >= 72) s -= 1;
  if (hires === 1) s -= 0.5;
  else if ((hires ?? 0) >= 3) s += 0.5;
  return Math.max(0.5, Math.min(5, Math.round(s * 2) / 2));
}
