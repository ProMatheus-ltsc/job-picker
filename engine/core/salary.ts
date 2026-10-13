/**
 * 地区薪酬参考表（选岗对比用）
 *
 * ⚠️ 数据性质说明：
 * 公务员薪酬**没有全国统一公开的口径**，本表由三类公开信息交叉推算：
 *   1. 官方部门预算（如「税务系统 2026 年部门预算」「国家税务总局陕西省税务局 2026 年单位预算」）
 *      —— 用于确认**结构比例**（基本工资全国统一、津贴补贴由地方财政承担）
 *   2. 地方税务局的单位预算（用于确认基层人员经费规模）
 *   3. 公开招聘论坛 / 调研汇总的**区间**数据
 * 因此表中数值是**参考区间，不是官方标准**，实际以录用单位的工资单为准。
 *
 * 核心结论（解释为什么同岗位不同城市能差 2~3 倍）：
 * 基本工资（职务 + 级别）全国统一，**它只占工资福利支出的约 1/4**；
 * 真正拉开差距的是「津贴补贴」（占 40%+）与地方绩效奖金——这两项由当地财政决定。
 */
import type { Job } from '../types';

export interface CitySalary {
  /** 展示名 */
  city: string;
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
}

/** 有明确公开数据的城市（按区域关键字模糊匹配） */
const VERIFIED: Array<{ key: string; data: Omit<CitySalary, 'city'> }> = [
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
  { key: '佛山', data: { payMin: 17, payMax: 22, cashMin: 8000, cashMax: 11000, fundMin: 3000, fundMax: 4000, housePrice: 12500, basis: '珠三角调研汇总（2026）' } },
  { key: '珠海', data: { payMin: 17, payMax: 22, cashMin: 8000, cashMax: 11000, fundMin: 3000, fundMax: 4000, housePrice: 20200, basis: '珠三角调研汇总（2026）' } },
  { key: '中山', data: { payMin: 15, payMax: 18, cashMin: 7000, cashMax: 9500, fundMin: 2500, fundMax: 3500, housePrice: 8500, basis: '广东省内第二梯队（2026）' } },
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

/** 未收录城市的档位兜底（口径来自公开的全国分档统计） */
const TIERS: Array<{ re: RegExp; label: string; data: Omit<CitySalary, 'city'> }> = [
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
  label: '普通地级市（估算）',
  data: {
    payMin: 9, payMax: 13, cashMin: 4500, cashMax: 6000, fundMin: 1200, fundMax: 2000,
    housePrice: 9000, basis: '档位估算（中西部普通地级市）',
  },
};

/** 按工作地点文本匹配薪酬档（模糊：填「深圳」即可命中「广东省深圳市」） */
export function estimateSalary(region: string): CitySalary & { precise: boolean } {
  const r = String(region ?? '');
  for (const v of VERIFIED) {
    if (r.includes(v.key)) return { city: v.key, precise: true, ...v.data };
  }
  for (const t of TIERS) {
    if (t.re.test(r)) return { city: t.label, precise: false, ...t.data };
  }
  return { city: DEFAULT_TIER.label, precise: false, ...DEFAULT_TIER.data };
}

/** 多个岗位所在城市去重后的薪酬档（按年收入中位降序） */
export function salaryTable(jobs: Job[]): Array<CitySalary & { precise: boolean; count: number; yearsForHousing: number }> {
  const map = new Map<string, { s: CitySalary & { precise: boolean }; count: number }>();
  for (const j of jobs) {
    const est = estimateSalary(j.region);
    const hit = map.get(est.city);
    if (hit) hit.count += 1;
    else map.set(est.city, { s: est, count: 1 });
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
