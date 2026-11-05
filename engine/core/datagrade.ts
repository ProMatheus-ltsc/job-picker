/**
 * 数据分级制度（A/B/C/D）与强制标注
 *
 * 省考官方**从不公布逐岗进面分**，而国考税务有官方面试名单。若坚持「只用一手数据」的二分铁律，
 * 省考就无法做任何分数分析；若放开成"什么都能用"，又会毁掉 job-picker 最核心的纪律。
 * 本模块用**四级 + 用途分离**解决这个矛盾：
 *
 * | 级别 | 定义 | 示例 | 允许用途 |
 * |------|------|------|----------|
 * | A 一手 | 官方原件 | 职位表、面试名单、部门预算、合格线公告 | 可直接进结论与排序 |
 * | B 二手可核验 | 有原始附件/可复算式，但由机构整理 | 含行测/申论拆解可自洽验算的进面分 | 可用，标（二手·可核验），可排序 |
 * | C 二手估算 | 无法验证、样本不明 | "广州 74.47"（佛山珠海三项相同 = 单岗样本） | **只读方向，不进排序公式** |
 * | D 禁用 | 营销模板、明显矛盾 | "2026 区直 80–84 分"（超过去年全市最高分） | 不引用 |
 *
 * 关键设计：**放宽发生在"标注层"，不发生在"守门层"**。
 * `scripts/_guard.py` 的官方域名硬校验保持不变（抓取侧仍然只能抓官网），
 * 分级只决定「已拿到的数字能不能进排序公式」。
 */

export type DataGrade = 'A' | 'B' | 'C' | 'D';

/** 数字的用途：display = 展示与方向判断，rank = 参与排序/公式运算 */
export type Usage = 'display' | 'rank';

export interface GradeMeta {
  grade: DataGrade;
  /** 展示用短标签，如「一手」「二手·可核验」「二手·估算」「禁用」 */
  label: string;
  /** 该级别的允许用途说明 */
  allowed: string;
}

export const GRADES: Record<DataGrade, GradeMeta> = {
  A: { grade: 'A', label: '一手', allowed: '可直接进结论与排序' },
  B: { grade: 'B', label: '二手·可核验', allowed: '可用，标注后参与排序' },
  C: { grade: 'C', label: '二手·估算', allowed: '只读方向，禁止进排序公式' },
  D: { grade: 'D', label: '禁用', allowed: '不引用' },
};

/** 携带级别与来源的数值（报告里每个数字都应长这样） */
export interface GradedValue {
  value: number | null;
  grade: DataGrade;
  label: string;
  source: string;
}

export class DataGradeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DataGradeError';
  }
}

const VALID_GRADES: DataGrade[] = ['A', 'B', 'C', 'D'];

/**
 * 数值用途校验：返回带标注的 GradedValue，或按规则抛 DataGradeError。
 *
 * 规则：
 * - 级别非法 → 抛错（不猜默认级别，避免把未知来源当成一手）；
 * - `D` 级任何用途 → 抛错；
 * - `C` 级用于 `rank` → 抛错（这是「不许把估算值混进排序」的唯一执行点）；
 * - `A`/`B` 任何用途、`C` 用于 `display` → 放行。
 */
export function requireUsable(
  value: number | null,
  grade: DataGrade,
  use: Usage,
  source: string,
): GradedValue {
  if (!VALID_GRADES.includes(grade)) {
    throw new DataGradeError(
      `数据级别非法: ${String(grade)}（只接受 A/B/C/D）｜来源: ${source || '未标注'}`,
    );
  }
  const meta = GRADES[grade];
  if (grade === 'D') {
    throw new DataGradeError(
      `D 级数据禁止引用（${
        use === 'rank' ? '排序' : '展示'
      }）｜来源: ${source || '未标注'}`,
    );
  }
  if (grade === 'C' && use === 'rank') {
    throw new DataGradeError(
      `C 级数据不得进入排序公式（只读方向）｜值=${value}｜来源: ${source || '未标注'}`,
    );
  }
  return { value, grade, label: meta.label, source };
}

/** 不做校验的标注包装（用于已经确定是展示用途、或只为报告留痕的场景） */
export function annotate(value: number | null, grade: DataGrade, source: string): GradedValue {
  return { value, grade, label: GRADES[grade].label, source };
}

/** 报告里的标注后缀，如「（一手）」「（二手·估算）」 */
export function gradeSuffix(grade: DataGrade): string {
  return `（${GRADES[grade].label}）`;
}

/** 用途能力判断（供调用方提前分支，避免用 try/catch 做流程控制） */
export function canUse(grade: DataGrade, use: Usage): boolean {
  if (!VALID_GRADES.includes(grade)) return false;
  if (grade === 'D') return false;
  if (grade === 'C' && use === 'rank') return false;
  return true;
}

/** 两级别取更保守的一个（合并多个来源时使用） */
export function weakest(...grades: DataGrade[]): DataGrade {
  const order: Record<DataGrade, number> = { A: 0, B: 1, C: 2, D: 3 };
  let worst: DataGrade = 'A';
  for (const g of grades) {
    if (order[g] > order[worst]) worst = g;
  }
  return worst;
}
