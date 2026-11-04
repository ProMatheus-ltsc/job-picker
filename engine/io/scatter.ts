/**
 * 薪酬 × 进面概率散点图（单文件 HTML，纵轴对数）
 *
 * 为什么纵轴要对数：当天 11 个岗位的概率跨 200 倍以上，线性轴会把除最大值外的所有点
 * 全部压到底轴上，等于只画了一个点。对数轴下每个数量级等距，低概率岗位之间的差异才可见。
 *
 * 约束（PRD F-009）：
 * - 单文件、无外部依赖（不引 CDN / 不引脚本）；
 * - 气泡大小 = 竞争比，颜色 = 城市，带图例；
 * - 概率为 0 的点**不静默丢弃**，固定在轴底并以特殊标记呈现。
 */

export interface ScatterPoint {
  /** 展示名（单位+职位） */
  label: string;
  /** 城市/区（决定颜色） */
  city: string;
  /** 薪酬轴：年全包中位（万元）；null 表示缺数据 */
  salaryMid: number | null;
  /** 概率轴：进面概率；null 表示未计算，0 表示确实为 0 */
  probability: number | null;
  /** 竞争比（报名 ÷ 招录），决定气泡大小；null 表示缺报名人数 */
  ratio: number | null;
}

/** 城市 → 配色（同一城市同色；按出现顺序分配，超出预设则回退调色板循环） */
const PALETTE = [
  '#2563eb', '#dc2626', '#059669', '#7c3aed', '#ea580c',
  '#0891b2', '#c026d3', '#65a30d', '#b45309', '#475569',
];

const W = 860;
const H = 480;
const PAD = { left: 84, right: 210, top: 40, bottom: 64 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function esc(text: string): string {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 对数轴刻度：取数据范围覆盖的 10 的整数次幂 */
function logTicks(minP: number, maxP: number): number[] {
  const low = Math.floor(Math.log10(Math.max(minP, 1e-9)));
  const high = Math.ceil(Math.log10(Math.max(maxP, 1e-9)));
  const ticks: number[] = [];
  for (let exp = low; exp <= high; exp += 1) ticks.push(10 ** exp);
  return ticks;
}

/**
 * 渲染散点图 HTML。
 * 概率为 null 的点不绘制（计入 skipped 并在页面说明），概率为 0 的点画在轴底并加「0」标记。
 */
export function renderScatterHtml(points: ScatterPoint[], title = '薪酬 × 进面概率'): string {
  const usable = (points ?? []).filter((p) => p.salaryMid != null);
  const skipped = (points ?? []).filter((p) => p.salaryMid == null);

  const salaries = usable.map((p) => p.salaryMid as number);
  const probs = usable
    .map((p) => p.probability)
    .filter((v): v is number => v != null && v > 0);

  const salaryMin = salaries.length ? Math.min(...salaries) : 14;
  const salaryMax = salaries.length ? Math.max(...salaries) : 30;
  const pMin = probs.length ? Math.min(...probs) : 1e-4;
  const pMax = probs.length ? Math.max(...probs) : 1;
  const ticks = logTicks(pMin, pMax);
  const axisLow = Math.min(ticks[0], pMin * 0.5);
  const axisHigh = Math.max(ticks[ticks.length - 1], pMax * 2);

  const xOf = (salary: number): number => {
    const span = salaryMax - salaryMin || 1;
    return PAD.left + ((salary - salaryMin) / span) * PLOT_W * 0.86 + PLOT_W * 0.07;
  };
  const yOf = (p: number): number => {
    const value = Math.max(p, axisLow);
    const frac = (Math.log10(value) - Math.log10(axisLow)) /
      (Math.log10(axisHigh) - Math.log10(axisLow) || 1);
    return PAD.top + PLOT_H - frac * PLOT_H;
  };
  const rOf = (ratio: number | null): number => {
    if (ratio == null || !isFinite(ratio) || ratio <= 0) return 5;
    return Math.max(4, Math.min(20, 4 + Math.sqrt(ratio) * 0.9));
  };

  const cities = [...new Set(usable.map((p) => p.city))];
  const colorOf = (city: string): string =>
    PALETTE[cities.indexOf(city) % PALETTE.length] ?? PALETTE[0];

  const bubbles = usable
    .map((p) => {
      const x = xOf(p.salaryMid as number);
      const isZero = p.probability === 0;
      const y = isZero ? PAD.top + PLOT_H : yOf((p.probability ?? axisLow) as number);
      const r = rOf(p.ratio);
      const color = colorOf(p.city);
      const tip = `${p.label}｜薪酬 ${(p.salaryMid as number).toFixed(1)} 万｜概率 ${
        p.probability == null ? '未计算' : p.probability === 0 ? '0' : p.probability.toExponential(2)
      }｜竞争比 ${p.ratio == null ? '—' : `${Math.round(p.ratio)}:1`}`;
      return [
        `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}"`,
        ` fill-opacity="${isZero ? 0.35 : 0.6}" stroke="${color}" stroke-width="1.4"`,
        ` stroke-dasharray="${isZero ? '3 2' : '0'}"><title>${esc(tip)}</title></circle>`,
      ].join('');
    })
    .join('\n    ');

  const yGrid = ticks
    .map((t) => {
      const y = yOf(t);
      return `<line x1="${PAD.left}" y1="${y.toFixed(1)}" x2="${PAD.left + PLOT_W}" y2="${y.toFixed(1)}" stroke="#eef2f7"/>` +
        `<text x="${PAD.left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="10.5" fill="#6b7280">${t.toExponential(0)}</text>`;
    })
    .join('\n    ');

  const xTicks = [0, 0.25, 0.5, 0.75, 1]
    .map((frac) => {
      const salary = salaryMin + (salaryMax - salaryMin) * frac;
      const x = PAD.left + frac * PLOT_W;
      return `<text x="${x.toFixed(1)}" y="${PAD.top + PLOT_H + 20}" text-anchor="middle" font-size="10.5" fill="#6b7280">${salary.toFixed(1)}</text>`;
    })
    .join('');

  const legend = cities
    .map((city, index) => {
      const y = PAD.top + 18 + index * 20;
      return `<circle cx="${PAD.left + PLOT_W + 18}" cy="${y}" r="6" fill="${colorOf(city)}" fill-opacity=".62"/>` +
        `<text x="${PAD.left + PLOT_W + 32}" y="${y + 4}" font-size="11" fill="#374151">${esc(city)}</text>`;
    })
    .join('\n    ');

  const skippedNote = skipped.length
    ? `<p class="note">${skipped.length} 个岗位因缺少薪酬数据未绘制：${skipped
        .map((p) => esc(p.label))
        .join('、')}</p>`
    : '';

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${esc(title)}</title>
<style>
  body { margin:0; padding:24px 28px 40px; font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         color:#1b1f24; background:#fbfcfd; }
  h1 { font-size:19px; margin:0 0 6px; }
  .sub { color:#6b7280; font-size:12.5px; margin-bottom:16px; }
  .card { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px 18px; }
  .note { color:#8a5a00; background:#fff8e6; border:1px solid #f3d98b; border-radius:8px;
          padding:8px 12px; font-size:12.5px; margin:12px 0 0; }
</style>
</head>
<body>
<h1>${esc(title)}</h1>
<div class="sub">纵轴为对数刻度（log10）：概率跨多个数量级时线性轴会把低概率点全部压在底轴上。气泡大小 = 竞争比，颜色 = 城市。</div>
<div class="card">
<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="薪酬与进面概率散点图，纵轴对数">
    <line x1="${PAD.left}" y1="${PAD.top}" x2="${PAD.left}" y2="${PAD.top + PLOT_H}" stroke="#cbd5e1"/>
    <line x1="${PAD.left}" y1="${PAD.top + PLOT_H}" x2="${PAD.left + PLOT_W}" y2="${PAD.top + PLOT_H}" stroke="#cbd5e1"/>
    ${yGrid}
    ${xTicks}
    <text x="${PAD.left + PLOT_W / 2}" y="${H - 18}" text-anchor="middle" font-size="11.5" fill="#6b7280">年全包（万元，中位）</text>
    <text x="20" y="${PAD.top + PLOT_H / 2}" font-size="11.5" fill="#6b7280" text-anchor="middle"
          transform="rotate(-90 20 ${PAD.top + PLOT_H / 2})">进面概率（log10）</text>
    ${bubbles}
    ${legend}
    <text x="${PAD.left + PLOT_W + 14}" y="${PAD.top + 18 + cities.length * 20 + 8}" font-size="10.5" fill="#6b7280">气泡 = 竞争比</text>
</svg>
${skippedNote}
</div>
</body>
</html>
`;
}
