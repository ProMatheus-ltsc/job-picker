/**
 * 打分计算（05 §4.4 契约，公式冻结；demo calc() 拆解迁移，业务口径零变更）
 * 总分 =（平均收入 + 到手收入 + 收入打分 + 到手收入打分）÷ 报录比
 */

/** 收入打分默认 = 年收入万数四舍五入（Q-D1；null → 0） */
export function roundIncomeScore(incomeWan: number | null): number {
  if (incomeWan == null) return 0;
  return Math.round(incomeWan);
}

/** 报录比 = 报名人数 ÷ 录用人数；人数为 null/0 → null（Q-D2，报录比无意义） */
export function calcRatio(applicants: number | null, hires: number | null): number | null {
  const a = applicants ?? 0;
  const h = hires ?? 0;
  if (a === 0 || h === 0) return null;
  return a / h;
}

/** 总分；收入项 null 按 0 参与求和；报录比 null → 总分 null（UI 显示「—」） */
export function calcTotal(job: {
  avgIncome: number | null;
  netIncome: number | null;
  incomeScore: number | null;
  netScore: number | null;
  applicants: number | null;
  hires: number | null;
}): number | null {
  const avg = job.avgIncome ?? 0;
  const net = job.netIncome ?? 0;
  const sAvg = job.incomeScore ?? 0;
  const sNet = job.netScore ?? 0;
  const ratio = calcRatio(job.applicants, job.hires);
  const sum = avg + net + sAvg + sNet;
  if (ratio == null || ratio <= 0) return null;
  return sum / ratio;
}

/** null → '—'；否则两位小数（0.9348 → '0.93'） */
export function totalDisplay(total: number | null): string {
  return total == null ? '—' : total.toFixed(2);
}

/** 数值统一显示：null → '—'，否则 toFixed(d)（demo fnum 迁移） */
export function fnum(v: number | null | undefined, d: number): string {
  return v == null ? '—' : (+v).toFixed(d);
}

/** 行展开代入式（F-03 规则 7），如 (49.88+45.08+55+37)÷(400÷2)=0.93；报录比无效时分母段显示 — */
export function formulaExpression(job: {
  avgIncome: number | null;
  netIncome: number | null;
  incomeScore: number | null;
  netScore: number | null;
  applicants: number | null;
  hires: number | null;
}): string {
  const total = calcTotal(job);
  const denom =
    job.applicants == null && job.hires == null ? '—' : `${job.applicants ?? 0}÷${job.hires ?? 0}`;
  return `（${fnum(job.avgIncome, 2)} + ${fnum(job.netIncome, 2)} + ${fnum(job.incomeScore, 0)} + ${fnum(job.netScore, 0)}）÷（${denom}）= ${total == null ? '—' : total.toFixed(3)}`;
}
