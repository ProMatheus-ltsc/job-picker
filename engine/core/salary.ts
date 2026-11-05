/**
 * 地区薪酬参考表（选岗对比用）—— 市 + 区两级粒度
 *
 * ⚠️ 数据性质说明：
 * 公务员薪酬**没有全国统一公开的口径**，本表由三类公开信息交叉推算：
 *   1. 官方部门预算（如「税务系统 2026 年部门预算」「国家税务总局陕西省税务局 2026 年单位预算」）
 *      —— 用于确认**结构比例**（基本工资全国统一、津贴补贴由地方财政承担）
 *   2. 地方税务局的单位预算（用于确认基层人员经费规模）
 *   3. 公开招聘论坛 / 调研汇总的**区间**数据
 * 因此表中数值是**参考区间，不是官方标准**，实际以录用单位的工资单为准。
 * 按 `datagrade.ts` 的分级，市级与区级档位都是 **B 级（二手·可核验）**：
 * 有预算结构与样本可比对，但不是逐单位实测。
 *
 * 核心结论（解释为什么同岗位不同城市能差 2~3 倍）：
 * 基本工资（职务 + 级别）全国统一，**它只占工资福利支出的约 1/4**；
 * 真正拉开差距的是「津贴补贴」（占 40%+）与地方绩效奖金——这两项由当地财政决定。
 *
 * ★ 为什么必须下沉到区（2026-11-04 实测缺口）：
 * 原表广州整市一个档（18–25 万），但实测区际差 6.5–12 万：
 * 荔湾 18–21 万 vs 南沙 25–27 万，被同一档完全抹掉，排序结论失真。
 */
import type { Job } from '../types';
import type { DataGrade } from './datagrade';

export interface CitySalary {
  /** 展示名（市级名，区级档为「广州·南沙」这类） */
  city: string;
  /** 区名；市/层级兜底档为空字符串 */
  district: string;
  /** 年全包收入区间（万元）：到手工资 + 双边公积金 + 绩效 */
  payMin: number;
  payMax: number;
  /** 月到手区间（元，含车补） */
  cashMin: number;
  cashMax: number;
  /** 公积金双边/月（元） */
  fundMin: number;
  fundMax: number;
  /** 二手房均价（元/㎡） */
  housePrice: number;
  /** 数据来源 */
  basis: string;
  /**
   * 数据级别（与 `datagrade.ts` 的四级一致），由**匹配来源**决定：
   * 区级 B / 省直 A / 市级 B / 层级兜底 C。
   *
   * 不能靠解析 basis 文本猜测：市级档的 basis 是「多来源调研汇总」，不含级别字样，
   * 猜出来会变成 C（估算），而市级档实际有样本可核验（B）。
   * 误判成 C 会让「C 级不进排序公式」这条规则名存实亡（MJ-06）。
   */
  grade: DataGrade;
}

// grade 不在档位字面量里：由 estimateSalary 按匹配来源统一赋值（m-01）
type SalaryTier = Omit<CitySalary, 'city' | 'district' | 'grade'>;

/**
 * 市级档（未到区级时使用；按区域关键字模糊匹配）
 * 匹配顺序见 estimateSalary：区级 → 市级 → 层级兜底。
 */
const VERIFIED: Array<{ key: string; data: SalaryTier }> = [
  // ===== 广东 =====
  {
    key: '深圳',
    data: {
      payMin: 25, payMax: 30, cashMin: 14000, cashMax: 18000, fundMin: 4000, fundMax: 5600,
      housePrice: 55000, basis: '多来源调研汇总（2026）',
    },
  },
  {
    key: '广州',
    data: {
      payMin: 18, payMax: 25, cashMin: 8000, cashMax: 10000, fundMin: 3000, fundMax: 3500,
      housePrice: 32000, basis: '多来源调研汇总（2026）',
    },
  },
  { key: '东莞', data: { payMin: 17, payMax: 22, cashMin: 8000, cashMax: 11000, fundMin: 3000, fundMax: 4000, housePrice: 19200, basis: '珠三角调研汇总（2026）' } },
  { key: '佛山', data: { payMin: 17, payMax: 20, cashMin: 8000, cashMax: 11000, fundMin: 3000, fundMax: 4000, housePrice: 12500, basis: '珠三角调研汇总（2026，B 级：部门预算档 19–23 + 机构样本 16.8–20 交叉取 17–20）' } },
  { key: '珠海', data: { payMin: 17, payMax: 22, cashMin: 8000, cashMax: 11000, fundMin: 3000, fundMax: 4000, housePrice: 20200, basis: '珠三角调研汇总（2026）' } },
  { key: '中山', data: { payMin: 19, payMax: 22, cashMin: 8000, cashMax: 10500, fundMin: 3000, fundMax: 3800, housePrice: 8500, basis: '珠三角二梯队（2026，B 级：部门预算档 20–24 + 机构样本 17–22 交叉取 19–22）' } },
  { key: '惠州', data: { payMin: 15, payMax: 18, cashMin: 7000, cashMax: 9500, fundMin: 2500, fundMax: 3500, housePrice: 8300, basis: '广东省内第二梯队（2026）' } },
  { key: '江门', data: { payMin: 15, payMax: 18, cashMin: 7000, cashMax: 9500, fundMin: 2500, fundMax: 3500, housePrice: 6300, basis: '广东省内第二梯队（2026）' } },
  { key: '汕头', data: { payMin: 15, payMax: 18, cashMin: 7000, cashMax: 9500, fundMin: 2500, fundMax: 3500, housePrice: 10500, basis: '广东省内第二梯队（2026）' } },
  { key: '湛江', data: { payMin: 14, payMax: 17, cashMin: 6500, cashMax: 9000, fundMin: 2200, fundMax: 3200, housePrice: 8900, basis: '粤东西北（2026）' } },

  // ===== 浙江 =====
  {
    key: '杭州',
    data: {
      payMin: 18, payMax: 22, cashMin: 7000, cashMax: 9000, fundMin: 3500, fundMax: 4000,
      housePrice: 30000, basis: '多来源调研汇总（2026）',
    },
  },
  {
    key: '宁波',
    data: {
      payMin: 20, payMax: 25, cashMin: 9000, cashMax: 14000, fundMin: 4000, fundMax: 5000,
      housePrice: 18500, basis: '浙江省第一梯队调研（2026）',
    },
  },
  { key: '温州', data: { payMin: 16, payMax: 20, cashMin: 7500, cashMax: 10000, fundMin: 2800, fundMax: 3800, housePrice: 13400, basis: '浙江省第二梯队（2026）' } },
  { key: '绍兴', data: { payMin: 16, payMax: 20, cashMin: 7500, cashMax: 10000, fundMin: 2800, fundMax: 3800, housePrice: 13400, basis: '浙江省第二梯队（2026）' } },
  { key: '嘉兴', data: { payMin: 16, payMax: 20, cashMin: 7500, cashMax: 10000, fundMin: 2800, fundMax: 3800, housePrice: 12300, basis: '浙江省第二梯队（2026）' } },
  { key: '台州', data: { payMin: 16, payMax: 20, cashMin: 7500, cashMax: 10000, fundMin: 2800, fundMax: 3800, housePrice: 15100, basis: '浙江省第二梯队（2026）' } },
  { key: '金华', data: { payMin: 16, payMax: 20, cashMin: 7500, cashMax: 10000, fundMin: 2800, fundMax: 3800, housePrice: 15000, basis: '浙江省第二梯队（2026）' } },
  { key: '湖州', data: { payMin: 14, payMax: 15, cashMin: 6500, cashMax: 8000, fundMin: 2500, fundMax: 3200, housePrice: 9400, basis: '浙江省第三梯队（2026）' } },
  { key: '舟山', data: { payMin: 14, payMax: 15, cashMin: 6500, cashMax: 8000, fundMin: 2500, fundMax: 3200, housePrice: 11000, basis: '浙江省第三梯队（2026）' } },
  { key: '衢州', data: { payMin: 14, payMax: 15, cashMin: 6500, cashMax: 8000, fundMin: 2500, fundMax: 3200, housePrice: 11500, basis: '浙江省第三梯队（2026）' } },
  { key: '丽水', data: { payMin: 14, payMax: 15, cashMin: 6500, cashMax: 8000, fundMin: 2500, fundMax: 3200, housePrice: 14500, basis: '浙江省第三梯队（2026）' } },

  // ===== 陕西 =====
  {
    key: '西安',
    data: {
      payMin: 12, payMax: 14, cashMin: 5800, cashMax: 6400, fundMin: 900, fundMax: 1400,
      housePrice: 9054, basis: '税务系统公开收支拆解 + 西安区级房价（2026）',
    },
  },
];

/**
 * 区级档（★ 本次改造新增）：市 + 区 → 年全包区间。
 *
 * 数据来源与级别：
 * - 「依据级别 B」= 部门预算结构 + 同类区样本交叉，误差约 ±15–20%；
 * - 省直的 A（预算）档单列在 LEVEL_TIERS 里，因为省直没有"区"的概念。
 *
 * 覆盖优先：先市级命中市名，再在**该市**范围内匹配区名，避免「南沙」这类同名歧义。
 */
const DISTRICT_VERIFIED: Array<{
  city: string;
  districts: string[];
  data: SalaryTier;
}> = [
  // ===== 广州（区际差 6.5–12 万，实测最强的分化） =====
  {
    city: '广州',
    districts: ['南沙', '黄埔', '番禺'],
    data: {
      payMin: 25, payMax: 27, cashMin: 11000, cashMax: 13000, fundMin: 3800, fundMax: 4400,
      housePrice: 26000, basis: '区级分档（2026，B 级：部门预算结构 + 同类区样本交叉，误差 ±15–20%）',
    },
  },
  {
    city: '广州',
    districts: ['天河', '白云'],
    data: {
      payMin: 24, payMax: 26, cashMin: 10500, cashMax: 12500, fundMin: 3600, fundMax: 4200,
      housePrice: 38000, basis: '区级分档（2026，B 级：部门预算结构 + 同类区样本交叉，误差 ±15–20%）',
    },
  },
  {
    city: '广州',
    districts: ['海珠'],
    data: {
      payMin: 23, payMax: 25, cashMin: 10000, cashMax: 12000, fundMin: 3500, fundMax: 4100,
      housePrice: 36000, basis: '区级分档（2026，B 级：部门预算结构 + 同类区样本交叉，误差 ±15–20%）',
    },
  },
  {
    city: '广州',
    districts: ['荔湾'],
    data: {
      payMin: 18, payMax: 21, cashMin: 8000, cashMax: 9500, fundMin: 2900, fundMax: 3400,
      housePrice: 30000, basis: '区级分档（2026，B 级：财政弱区实测偏低，误差 ±15–20%）',
    },
  },
  {
    city: '广州',
    districts: ['从化'],
    data: {
      payMin: 15, payMax: 18, cashMin: 6800, cashMax: 8200, fundMin: 2400, fundMax: 3000,
      housePrice: 13000, basis: '区级分档（2026，B 级：远郊区实测偏低，误差 ±15–20%）',
    },
  },
  // ===== 深圳 =====
  {
    city: '深圳',
    districts: ['光明', '坪山'],
    data: {
      payMin: 24, payMax: 28, cashMin: 13500, cashMax: 17000, fundMin: 3900, fundMax: 5400,
      housePrice: 42000, basis: '区级分档（2026，B 级：原特区外样本交叉，误差 ±15–20%）',
    },
  },
  {
    city: '深圳',
    districts: ['深汕'],
    data: {
      payMin: 26, payMax: 30, cashMin: 14500, cashMax: 18500, fundMin: 4200, fundMax: 5800,
      housePrice: 12000, basis: '区级分档（2026，B 级：合作区补贴叠加，误差 ±15–20%）',
    },
  },
];

/** 未收录城市的档位兜底（口径来自公开的全国分档统计） */
const TIERS: Array<{ re: RegExp; label: string; data: SalaryTier }> = [
  {
    // ⚠️ 广东省考考区共 21 个，VERIFIED 只覆盖 10 个。不单列这条，
    //    肇庆/茂名/梅州等 11 个考区（3630 个岗位）会落到下面的「中西部普通地级市」9-13 万，
    //    对粤东西北是系统性低估 3~5 万。
    re: /肇庆|茂名|梅州|清远|河源|韶关|揭阳|阳江|汕尾|云浮|潮州/,
    label: '粤东西北',
    data: {
      payMin: 13, payMax: 16, cashMin: 6200, cashMax: 8200, fundMin: 2000, fundMax: 3000,
      housePrice: 7500, basis: '档位估算（粤东西北，无一手数据）',
    },
  },
  {
    re: /北京|上海/,
    label: '北京/上海',
    data: {
      payMin: 13, payMax: 16, cashMin: 7000, cashMax: 9000, fundMin: 2000, fundMax: 3000,
      housePrice: 45000, basis: '档位估算（一线非珠三角）',
    },
  },
  {
    re: /南京|苏州|无锡|宁波|厦门|珠海|佛山|东莞|天津|武汉|成都|合肥|长沙|济南|青岛/,
    label: '强二线/新一线',
    data: {
      payMin: 15, payMax: 20, cashMin: 6500, cashMax: 9000, fundMin: 2800, fundMax: 4000,
      housePrice: 20000, basis: '档位估算（新一线）',
    },
  },
  {
    re: /县|乡镇|区（|自治县/,
    label: '县域/乡镇',
    data: {
      payMin: 7, payMax: 11, cashMin: 4000, cashMax: 5200, fundMin: 900, fundMax: 1500,
      housePrice: 7000, basis: '档位估算（县域）',
    },
  },
];

const DEFAULT_TIER = {
  label: '未收录城市（估算）',
  data: {
    payMin: 9, payMax: 13, cashMin: 4500, cashMax: 6000, fundMin: 1200, fundMax: 2000,
    housePrice: 9000, basis: '档位估算（通用兜底，无一手数据）',
  },
};

/** 省直档（★ 新增）：省直机关驻广州，按预算反推的 A 级档，不随区波动 */
export const PROVINCE_LEVEL_TIER: SalaryTier & { label: string } = {
  label: '省直（驻广州）',
  payMin: 20.7,
  payMax: 22.9,
  cashMin: 9200,
  cashMax: 10500,
  fundMin: 3300,
  fundMax: 3800,
  housePrice: 32000,
  basis: '省直单位部门预算反推（2026，A 级：工资福利支出 − 单位缴费，误差 ±10%）',
};

/** 命中区级档（在该市范围内找区名） */
function matchDistrict(region: string): { city: string; district: string; data: SalaryTier } | null {
  for (const entry of DISTRICT_VERIFIED) {
    if (!region.includes(entry.city)) continue;
    const district = entry.districts.find((name) => region.includes(name));
    if (district) {
      return { city: entry.city, district, data: entry.data };
    }
  }
  return null;
}

/**
 * 是否为省直岗位（**仅广东**）。
 *
 * 判定必须同时满足，否则会误判：
 *   ① 不含任何市级标识（市/州/区/县/街道/镇）——「广东省广州市某局」是最常见写法，
 *      省级前缀 + 市级主体，误判成省直会把 18–25 万报成 20.7 万；
 *   ② 要么含明确省级措辞（省直/省级/省属/省本级），要么是「广东省 + 机关后缀」；
 *   ③ ★ 省直档（20.7–22.9 万）**只有广东有实测依据**（来自广东省直单位部门预算）。
 *      其它省份没有对应数据，硬套会把「浙江省财政厅」标成「省直（驻广州）」——明显错误。
 *      未收录省份一律回退市级/层级档，宁可粗也不编。
 *
 * 反例（必须判非省直）：「广东省广州市某局」「浙江省财政厅」「江苏省发展和改革委员会」
 * 正例（应判省直）：「广东省财政厅」「广东省发展和改革委员会」「省直某单位」
 */
function isProvinceLevel(region: string): boolean {
  const r = String(region ?? '').trim();
  if (!r) return false;
  // ① 市级标识的否定优先级最高
  if (/[市州区县]|街道|镇/.test(r)) return false;

  const explicitProvinceLevel = /省直|省级|省属|省本级/.test(r);
  const guangdongProvinceUnit = /广东.{0,20}(?:厅|委员会|委|办公室|办|局|院|中心)$/.test(r);
  if (!explicitProvinceLevel && !guangdongProvinceUnit) return false;

  // ② 明确的省级措辞：若文本里出现**其它省名**，说明不是广东，拒绝套用广东档
  if (explicitProvinceLevel) {
    const otherProvince =
      /(?:浙江|江苏|山东|河南|河北|山西|陕西|甘肃|青海|辽宁|吉林|黑龙江|安徽|福建|江西|湖北|湖南|四川|贵州|云南|海南|内蒙古|广西|西藏|宁夏|新疆|北京|上海|天津|重庆)/;
    if (otherProvince.test(r) && !/广东/.test(r)) return false;
    return true;
  }
  // ③「广东省 + 机关后缀」已是广东，直接放行
  return true;
}

/**
 * 按工作地点文本匹配薪酬档。
 *
 * **匹配顺序：区 > 省直 > 市 > 层级兜底**（区级粒度必须优先，否则南沙会被广州整市档吃掉）。
 *
 * `precise` 的语义（改造后）：**是否命中了比"整市"更细的已核验档**——
 * - 区级档命中 → true；
 * - 省直预算反推档命中 → true；
 * - 仅命中整市档 → false（区间是整市口径，不能代表某个区）；
 * - 层级兜底 → false。
 *
 * 改这个语义的原因：改造前整市档也算 precise=true，导致「增城区」和「南沙区」都显示"精确"，
 * 而它们实际共享同一个 18–25 万的整市区间——**"精确"这个词在骗人**。
 */
export function estimateSalary(region: string): CitySalary & { precise: boolean } {
  const r = String(region ?? '');

  // ① 区级（最高优先级）：B 级，有部门预算结构 + 同类区样本可核验
  const districtHit = matchDistrict(r);
  if (districtHit) {
    return {
      city: districtHit.city,
      district: districtHit.district,
      precise: true,
      grade: 'B',
      ...districtHit.data,
    };
  }

  // ② 省直：A 级，来自单位部门预算反推（一手）
  if (isProvinceLevel(r)) {
    const { label, ...tier } = PROVINCE_LEVEL_TIER;
    return { city: label, district: '', precise: true, grade: 'A', ...tier };
  }

  // ③ 市级：B 级，有调研样本可核验（整市口径 → 不够细，precise=false）
  for (const v of VERIFIED) {
    if (r.includes(v.key)) {
      return { city: v.key, district: '', precise: false, grade: 'B', ...v.data };
    }
  }

  // ④ 层级兜底：C 级，纯档位推断、无法核验（因此不得进排序公式）
  for (const t of TIERS) {
    if (t.re.test(r)) {
      return { city: t.label, district: '', precise: false, grade: 'C', ...t.data };
    }
  }
  return {
    city: DEFAULT_TIER.label,
    district: '',
    precise: false,
    grade: 'C',
    ...DEFAULT_TIER.data,
  };
}

/**
 * 按**岗位**匹配薪酬档：优先用「招考单位」判定区级/省直，单位名判不出来才退回考区。
 *
 * 为什么不能只用考区（2026-11-05 实测缺陷）：
 * 广东省考职位表的「考区」列只有 21 个地市名（「广州」「深圳」），
 * **区名与省直身份全在「招考单位」里**（「广州市南沙区发展和改革局」「广东省退役军人事务厅」）。
 * 只用考区 → 南沙被算成广州整市档 18–25 万、省直三个岗也落到广州整市档，
 * 区际 6.5–12 万的差距与省直 A 级预算档**全部失效**，而这正是选岗的主轴之一。
 *
 * 为什么不能简单拼成「单位 + 考区」：`isProvinceLevel` 见到「广州」里的「州」会判非省直，
 * 省直岗会被打回市档。所以先单独用单位名判定，判不出来（如考区名才是唯一地点线索）再拼。
 */
export function estimateSalaryForJob(job: { unit?: string | null; region?: string | null }): CitySalary & { precise: boolean } {
  const unit = String(job.unit ?? '').trim();
  const region = String(job.region ?? '').trim();

  if (unit) {
    const byUnit = estimateSalary(unit);
    // precise = 命中了区级档或省直预算档（比"整市"更细），这才是我们要的信息
    if (byUnit.precise) return byUnit;
  }
  if (unit && region) return estimateSalary(`${unit} ${region}`);
  return estimateSalary(region || unit);
}

/** 展示名：有区级时带上区（「广州·南沙」），否则只有市/档位名 */
export function salaryLabel(s: Pick<CitySalary, 'city' | 'district'>): string {
  return s.district ? `${s.city}·${s.district}` : s.city;
}

/** 多个岗位所在城市去重后的薪酬档（按年收入中位降序） */
export function salaryTable(jobs: Job[]): Array<CitySalary & { precise: boolean; count: number; yearsForHousing: number }> {
  const map = new Map<string, { s: CitySalary & { precise: boolean }; count: number }>();
  for (const j of jobs) {
    const est = estimateSalaryForJob(j);
    const label = salaryLabel(est);
    const hit = map.get(label);
    if (hit) hit.count += 1;
    else map.set(label, { s: est, count: 1 });
  }
  return [...map.values()]
    .map(({ s, count }) => ({ ...s, count, yearsForHousing: yearsForHousing(s) }))
    .sort((a, b) => b.payMax + b.payMin - (a.payMax + a.payMin));
}

/**
 * 买一套 100㎡ 二手房需要多少年的**全部收入**（不吃不喝，不含贷款）。
 * 数值越小 = 生活性价比越高。
 */
export function yearsForHousing(s: Pick<CitySalary, 'payMin' | 'payMax' | 'housePrice'>, areaM2 = 100): number {
  const mid = ((s.payMin + s.payMax) / 2) * 10000; // 元
  const total = s.housePrice * areaM2; // 元
  if (!mid) return 0;
  return Math.round((total / mid) * 10) / 10;
}

/** 年全包中位（万元）——帕累托与散点图的薪酬轴 */
export function salaryMidpoint(s: Pick<CitySalary, 'payMin' | 'payMax'>): number {
  return Math.round(((s.payMin + s.payMax) / 2) * 100) / 100;
}
