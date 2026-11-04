/**
 * 进面概率模型
 *
 * 公式（改造方案 §2.2）：
 *
 *   P(进面) ≈ P(笔试分 ≥ 该岗进面线) × 进面名额 ÷ 报名人数
 *
 *   其中 P(达线) = 1 − Φ((线 − μ) / σ)
 *        μ = 当前折算基线（当天用 67）
 *        σ = 整卷波动（当天用 3.5）
 *        进面名额 = 招录人数 × 进面比（1:3；招 4–5 人按 1:2.5 向下取整）
 *        报名人数 = 官方报名期逐日公布（唯一窗口）
 *
 * 三个必检项（方案 §2.2）：
 * 1. 进面线可信度必须先判级（省考官方只公布合格线 60，逐岗线全是推算/二手）；
 * 2. 样本量 < 30 的考区均值不可用；
 * 3. **概率的绝对量级本身是结论**——当天 11 个岗全部 < 0.1%，
 *    说明「分数达标前，选岗的边际收益极小」。
 */

import { requireUsable, weakest, type DataGrade, type GradedValue } from './datagrade';

export interface ProbabilityInput {
  /** 笔试折算基线（C 级：用户自报或模考统计） */
  mu: number | null;
  /** 整卷波动（C 级：无模考记录时为主观给定） */
  sigma: number | null;
  /** 该岗进面线区间下沿 */
  cutoffMin: number | null;
  /** 该岗进面线区间上沿（等于 cutoffMin 表示单点线） */
  cutoffMax: number | null;
  /** 招录人数 */
  hires: number | null;
  /** 进面比，默认 3（1:3） */
  interviewRatio?: number | null;
  /** 报名人数（官方报名期唯一一手数据） */
  applicants: number | null;
  /**
   * 进面线的数据级别（由调用方按考试类型决定）：
   * - 国考税务：进面分取自招录机关面试公告附件 → A；
   * - 省考：官方不公布逐岗线，只能用区级/层级代理 → C。
   *
   * 默认 C（保守）：没显式声明来源就是不可验证的推算。
   * ★ 这个字段是 CRITICAL 指出的问题：原先硬编码 C，导致国考下出现
   * cutoffGrade=C 与 proxyGrade=A 并存、报告前后不一致。
   */
  cutoffGrade?: DataGrade;
  /** 进面线来源说明（报告口径声明直接引用） */
  cutoffSource?: string;
}

export interface ProbabilityResult {
  /** 主结论概率（用区间中点线）；缺输入时为 null，**不得算成 0** */
  p: number | null;
  /** 用区间下沿线（乐观） */
  pAtMinLine: number | null;
  /** 用区间上沿线（悲观） */
  pAtMaxLine: number | null;
  /** P(达线)，用区间中点线 */
  pHitLine: number | null;
  /** 进面名额 */
  quota: number | null;
  /** 报名人数 */
  applicants: number | null;
  /** 绝对量级警告（p < 0.1% 时非空） */
  magnitudeWarning: string | null;
  /** 缺失的输入项名称（非空表示结论不可用） */
  missingInputs: string[];
  /** 进面线的数据级别（国考 A / 省考 C） */
  cutoffGraded: GradedValue | null;
  /**
   * **概率整体**的数据级别（由各输入取最保守者合成）。
   *
   * 为什么不等于 cutoffGrade：概率 = f(进面线, μ, σ, 名额, 报名人数)，
   * 只要有一项是估算，整体就不能标成一手。
   * 例：国考进面线 A 级 + μ/σ 用户自报 C 级 → 概率整体 C 级。
   * 把概率直接标成 A 会让报告的数据分级段与数据表互相矛盾。
   */
  probabilityGrade: DataGrade;
  /** 合成级别时各输入的级别明细（便于报告解释"为什么是 C"） */
  gradeInputs: Array<{ input: string; grade: DataGrade }>;
  /** 原始概率是否被 1 截断（进面名额 >= 报名人数时会发生） */
  capped?: boolean;
}

/** 标准正态分布累积分布函数 Φ(x)（Abramowitz–Stegun 7.1.26 误差函数近似，精度 ~1e-7） */
export function normalCdf(x: number): number {
  // Φ(x) = 0.5 * (1 + erf(x / √2))
  const z = Math.abs(x) / Math.SQRT2;
  // erf(z) 近似（Abramowitz–Stegun 7.1.26）
  const t = 1 / (1 + 0.3275911 * z);
  const poly =
    t *
    (0.254829592 +
      t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  const erf = 1 - poly * Math.exp(-z * z);
  return x >= 0 ? 0.5 * (1 + erf) : 0.5 * (1 - erf);
}

/**
 * 进面名额。
 * 默认 1:3；招 4–5 人时按 1:2.5 向下取整（方案 §2.2 的口径），且至少 1 个名额。
 */
export function interviewQuota(hires: number | null, ratio = 3): number | null {
  if (hires == null || !isFinite(hires) || hires <= 0) return null;
  const effectiveRatio = hires >= 4 && hires <= 5 ? 2.5 : ratio;
  return Math.max(1, Math.floor(hires * effectiveRatio));
}

/** 单个进面线下的达线概率 */
function hitProbability(line: number, mu: number, sigma: number): number {
  return 1 - normalCdf((line - mu) / sigma);
}

/**
 * 计算进面概率。
 *
 * 降级语义（与 PRD F-006 一致）：
 * - 缺 mu / sigma / applicants / cutoff / hires 任一项 → `p = null` 且 `missingInputs` 列出缺项；
 * - **绝不把缺失输入算成 0 概率**（会把"不知道"伪装成"没希望"）；
 * - sigma <= 0 → 抛错（分母为零，模型退化为阶跃函数，必须由调用方显式决定）。
 */
export function estimateProbability(input: ProbabilityInput): ProbabilityResult {
  const missing: string[] = [];
  if (input.mu == null) missing.push('mu');
  if (input.sigma == null) missing.push('sigma');
  if (input.cutoffMin == null) missing.push('cutoffMin');
  if (input.hires == null) missing.push('hires');
  if (input.applicants == null) missing.push('applicants');

  if (input.sigma != null && input.sigma <= 0) {
    throw new Error(`整卷波动 sigma 必须为正数，收到 ${input.sigma}`);
  }

  const quota = interviewQuota(input.hires, input.interviewRatio ?? 3);
  const base: ProbabilityResult = {
    p: null,
    pAtMinLine: null,
    pAtMaxLine: null,
    pHitLine: null,
    quota,
    applicants: input.applicants,
    magnitudeWarning: null,
    missingInputs: missing,
    cutoffGraded: null,
    probabilityGrade: 'C',
    gradeInputs: [],
  };
  if (missing.length) return base;

  const mu = input.mu as number;
  const sigma = input.sigma as number;
  const cutoffMin = input.cutoffMin as number;
  const cutoffMax = input.cutoffMax ?? cutoffMin;
  const midLine = (cutoffMin + cutoffMax) / 2;
  const applicants = input.applicants as number;
  if (quota == null || applicants <= 0) {
    return { ...base, missingInputs: quota == null ? ['hires'] : ['applicants'] };
  }

  const pHit = hitProbability(midLine, mu, sigma);
  // 概率本质上界是 1：进面名额可能多于报名人数（招 2 人 x 1:3 = 6 个名额，
  // 但只有 3 人报名时公式会算出 200%——数学上无意义）。
  // 这里截断为 1，并用 capped 标记让调用方能解释「为什么恰好是 100%」。
  const rawP = (pHit * quota) / applicants;
  const p = Math.min(1, rawP);
  const pAtMinLine = Math.min(1, (hitProbability(cutoffMin, mu, sigma) * quota) / applicants);
  const pAtMaxLine = Math.min(1, (hitProbability(cutoffMax, mu, sigma) * quota) / applicants);

  // 进面线的级别由调用方声明（国考 A / 省考 C），默认 C（保守）。
  // 用 display 用途校验：允许 C 级进报告，但 C 级不得进排序公式（由 datagrade 把关）。
  // 未声明来源时按 C 级（推算/机构整理）处理——这是保守默认：
  // 调用方没有显式声明来源，就不能假定它是一手数据。
  const cutoffGraded = requireUsable(
    midLine,
    input.cutoffGrade ?? 'C',
    'display',
    input.cutoffSource ?? '逐岗进面线未声明来源（按推算处理，级别 C）',
  );

  let warning: string | null = null;
  if (p < 1e-3) {
    warning =
      '概率低于 0.1%：分数达标之前，选岗的边际收益极小——此时应优先提分而非纠结岗位。';
  }

  // ★ 概率整体级别 = 各输入级别里最保守的那个。
  // μ/σ 固定 C（用户自报或主观给定）；报名人数有值即 A（官方报名期唯一一手）；
  // 进面线按考试类型（国考 A / 省考 C）。任一为 C，整体就是 C。
  const gradeInputs: Array<{ input: string; grade: DataGrade }> = [
    { input: '进面线', grade: cutoffGraded.grade },
    { input: '笔试基线 μ', grade: 'C' },
    { input: '整卷波动 σ', grade: 'C' },
    { input: '报名人数', grade: applicants > 0 ? 'A' : 'C' },
  ];
  const probabilityGrade = weakest(...gradeInputs.map((item) => item.grade));

  return {
    p,
    pAtMinLine,
    pAtMaxLine,
    pHitLine: pHit,
    quota,
    applicants,
    magnitudeWarning: warning,
    missingInputs: [],
    cutoffGraded,
    probabilityGrade,
    gradeInputs,
    capped: rawP > 1,
  };
}

/** 概率格式化为百分比或科学计数（概率常跨 5 个数量级，不能只用小数） */
export function formatProbability(p: number | null): string {
  if (p == null) return '—';
  if (p === 0) return '0';
  if (p >= 0.01) return `${(p * 100).toFixed(2)}%`;
  if (p >= 1e-4) return `${(p * 100).toFixed(4)}%`;
  return p.toExponential(2);
}
