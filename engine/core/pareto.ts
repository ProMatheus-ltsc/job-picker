/**
 * 帕累托支配分析（薪酬 × 进面概率两轴）
 *
 * 目的：剔除「没有理由选它」的岗位。A 在薪酬与概率两轴都不劣于 B，且至少一轴更优 → A 支配 B。
 * 输出前沿点（值得纠结的）与被支配点（附各自的支配者）。
 *
 * 为什么需要它：只有星级排序时，一个「薪酬高但概率低 30 倍」的岗位可能因为星级接近而
 * 看起来和「薪酬略低但概率高得多」的岗位等价。当天实测：黄埔/深圳光明被南沙同薪酬支配，
 * 概率低 27–34 倍——这种岗位在排序表里完全看不出问题。
 */

export interface ParetoPoint {
  /** 岗位唯一标识（用于报告回溯） */
  key: string;
  /** 展示名（单位+职位） */
  label?: string;
  /** 薪酬轴：年全包中位（万元），越大越好。null 表示该轴不可用 */
  salaryMid: number | null;
  /** 概率轴：进面概率，越大越好。null 表示该轴不可用 */
  probability: number | null;
}

export interface ParetoDominance {
  /** 被支配的岗位 */
  key: string;
  label?: string;
  /** 支配它的岗位（可能多个） */
  by: string[];
  /** 相对各支配者的两轴差值（便于解释"差多少"） */
  deltas: Array<{ dominator: string; salaryDiff: number; probabilityRatio: number }>;
}

export interface ParetoResult {
  /** 前沿点（不被任何点支配） */
  frontier: ParetoPoint[];
  /** 被支配点 */
  dominated: ParetoDominance[];
  /** 因轴缺失被排除的点 */
  excluded: Array<{ key: string; label?: string; reason: string }>;
}

/**
 * A 是否支配 B。
 * 条件：两轴均不劣（>=）且至少一轴严格更优（>）。同值不算支配，判并列。
 */
export function dominates(a: ParetoPoint, b: ParetoPoint): boolean {
  if (a.salaryMid == null || a.probability == null) return false;
  if (b.salaryMid == null || b.probability == null) return false;
  const salaryNotWorse = a.salaryMid >= b.salaryMid;
  const probNotWorse = a.probability >= b.probability;
  const strictlyBetter = a.salaryMid > b.salaryMid || a.probability > b.probability;
  return salaryNotWorse && probNotWorse && strictlyBetter;
}

/**
 * 非支配排序。
 * - 输入为空 → 返回空结果，不抛错；
 * - 任一轴为 null → 排除并记入 excluded（不参与支配关系，也不污染前沿结论）；
 * - 同值点互不支配，均留在前沿。
 */
export function nonDominated(points: ParetoPoint[]): ParetoResult {
  const usable: ParetoPoint[] = [];
  const excluded: ParetoResult['excluded'] = [];
  for (const point of points ?? []) {
    if (point.salaryMid == null || point.probability == null) {
      const missing: string[] = [];
      if (point.salaryMid == null) missing.push('薪酬');
      if (point.probability == null) missing.push('概率');
      excluded.push({
        key: point.key,
        label: point.label,
        reason: `缺少${missing.join('与')}，无法参与两轴比较`,
      });
      continue;
    }
    usable.push(point);
  }

  const frontier: ParetoPoint[] = [];
  const dominated: ParetoDominance[] = [];
  for (const candidate of usable) {
    const dominators = usable.filter((other) => other.key !== candidate.key && dominates(other, candidate));
    if (!dominators.length) {
      frontier.push(candidate);
      continue;
    }
    dominated.push({
      key: candidate.key,
      label: candidate.label,
      by: dominators.map((d) => d.key),
      deltas: dominators.map((d) => ({
        dominator: d.key,
        salaryDiff: round((d.salaryMid as number) - (candidate.salaryMid as number), 2),
        // 概率之比：说明"低多少倍"，比差值更直观（当天用的就是倍数口径）
        probabilityRatio: round(
          (candidate.probability as number) > 0
            ? (d.probability as number) / (candidate.probability as number)
            : Infinity,
          1,
        ),
      })),
    });
  }

  return { frontier, dominated, excluded };
}

function round(value: number, digits: number): number {
  if (!isFinite(value)) return value;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** 一句话结论，如「3 个前沿点；2 个被支配（黄埔 被 南沙发改 支配，概率低 34 倍）」 */
export function paretoSummary(result: ParetoResult): string {
  const lines: string[] = [`${result.frontier.length} 个前沿点`];
  if (result.dominated.length) {
    const items = result.dominated.map((d) => {
      const ratio = d.deltas[0]?.probabilityRatio;
      const ratioText = ratio != null && isFinite(ratio) ? `，概率低 ${ratio} 倍` : '';
      return `${d.label ?? d.key} 被 ${d.by.join('/')} 支配${ratioText}`;
    });
    lines.push(`${result.dominated.length} 个被支配（${items.join('；')}）`);
  }
  if (result.excluded.length) {
    lines.push(`${result.excluded.length} 个因缺轴排除`);
  }
  return lines.join('；');
}
