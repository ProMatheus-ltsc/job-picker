/**
 * Markdown 报告模板（固定五段：结论 → 依据 → 数据表 → 局限 → 待核）
 *
 * 为什么要有固定模板：当天最大的体验问题是"每次输出结构都不一样"，
 * 读者无法判断这次是否漏了某一类信息。固定五段后，缺什么一目了然：
 * 空的小节也必须写出来（写「无」而不是省略），这样"省略"就再也不能被误读为"没想到"。
 *
 * 同时强制在开头写**判断口径声明**：μ/σ 是多少、进面线取自哪级数据、误差多大。
 * 这一条来自当天的三次纠正（C1~C5），核心是「判定标准先公开再出结果」。
 */

import type { DataGrade } from '../core/datagrade';
import { gradeSuffix } from '../core/datagrade';
import type { ExamType } from '../core/examMode';
import { examTypeNote } from '../core/examMode';
import type { ProbabilityResult } from '../core/probability';
import { formatProbability } from '../core/probability';
import type { IntensityResult } from '../core/intensity';
import { intensitySummary } from '../core/intensity';
import type { ParetoResult } from '../core/pareto';
import { paretoSummary } from '../core/pareto';

export interface ReportRow {
  /** 单位 + 职位（展示名） */
  label: string;
  /** 岗位代码 */
  code: string;
  /** 地区（含区级） */
  region: string;
  /** 招录人数 */
  hires: number | null;
  /** 年全包区间（万元） */
  payMin: number;
  payMax: number;
  /** 薪酬档依据级别 */
  payGrade: DataGrade;
  /** 进面概率 */
  probability: number | null;
  /** 数据级别 */
  probabilityGrade: DataGrade;
  /** 竞争比（报名 ÷ 招录） */
  ratio: number | null;
  /** 强度筛查 */
  intensity: IntensityResult;
  /** 最低服务年限 */
  minServiceYears: number | null;
  /** 是否帕累托前沿点 */
  frontier: boolean;
}

export interface CaliberStatement {
  /** 笔试基线 */
  mu: number | null;
  /** 整卷波动 */
  sigma: number | null;
  /** 进面线来源说明 */
  cutoffSource: string;
  /** 进面线级别 */
  cutoffGrade: DataGrade;
  /**
   * **概率整体**级别（weakest 合成）。
   * 与 cutoffGrade 分开：国考线是 A 级，但只要 μ/σ 是 C 级，概率整体就是 C 级。
   * 报告的「仅作方向筛选」声明按这个字段判断，而不是按进面线级别。
   */
  probabilityGrade?: DataGrade;
  /** 误差范围描述 */
  tolerance: string;
}

export interface ReportInput {
  examType: ExamType;
  cities: string[];
  caliber: CaliberStatement;
  rows: ReportRow[];
  pareto: ParetoResult;
  /** 范围外提示小节（由 scope.ts 生成，已含标题） */
  scopeNotice: string;
  /** 已知局限（缺数据、样本偏差等） */
  limitations: string[];
  /** 待核事项 */
  pendingChecks: string[];
  /** 概率量级警告（可选） */
  magnitudeWarning?: string | null;
  /** 生成时间与数据源指纹 */
  fingerprint?: { generatedAt?: string; sources?: string[] };
}

function cell(text: string | number | null): string {
  if (text == null || text === '') return '—';
  return String(text).replace(/\|/g, '\\|');
}

/** 结论段：一句话推荐 + 是否值得纠结 */
function renderConclusion(input: ReportInput): string {
  const { pareto, rows, magnitudeWarning, caliber } = input;
  const lines: string[] = ['## 结论', ''];
  if (!rows.length) {
    lines.push('**无符合条件的候选岗位。** 请检查画像参数、目标城市与强度筛选口径。');
    return lines.join('\n');
  }
  const frontier = pareto.frontier
    .map((p) => rows.find((r) => r.code === p.key)?.label ?? p.key)
    .filter(Boolean);

  // ★ 关键区分：全部被 excluded 说明「缺少概率轴，算不了」，不能写成「0 个前沿点」。
  // 后者会把"不知道"伪造成"没有更优岗"，是本项目最典型的错误输出。
  const analyzed = frontier.length + pareto.dominated.length;
  if (!analyzed) {
    lines.push(
      `本次 ${rows.length} 个候选岗位**未做帕累托前沿分析**：缺少两轴数据（` +
        `${pareto.excluded.length} 个岗位因缺薪酬或概率被排除）。`,
    );
    lines.push('');
    lines.push(
      '这不是"没有更优岗"，而是**算不了**。要得到前沿结论，请补上进面概率所需的输入' +
        '（`--mu` / `--sigma` / 报名人数）。',
    );
    lines.push('');
    if (magnitudeWarning) {
      lines.push(`> ⚠️ ${magnitudeWarning}`);
      lines.push('');
    }
    lines.push('**当前可依据的结论**：只能按薪酬区间与竞争度排序，不能判断"值不值得纠结"。');
    return lines.join('\n');
  }

  lines.push(
    `在 ${rows.length} 个候选岗位中，**${frontier.length} 个位于帕累托前沿**（薪酬与进面概率两轴都不被支配）：` +
      `${frontier.length ? frontier.map((f) => `**${f}**`).join('、') : '无'}。`,
  );
  lines.push('');
  if (pareto.dominated.length) {
    lines.push(`另有 ${pareto.dominated.length} 个岗位被支配（没有理由选它）：${paretoSummary(pareto)}。`);
    lines.push('');
  }
  if (pareto.excluded.length) {
    lines.push(`另有 ${pareto.excluded.length} 个岗位因缺轴未参与两轴比较（不影响上述结论）。`);
    lines.push('');
  }
  if (magnitudeWarning) {
    lines.push(`> ⚠️ ${magnitudeWarning}`);
    lines.push('');
  }
  lines.push(
    '**是否值得纠结**：若前沿点之间的概率差异不足一个数量级，薪酬差异应作为主要决策依据；' +
      '若概率差异超过 10 倍，优先选概率高的（薪酬差距在几年内可以用稳定性换回来）。',
  );
  // ★ 只要概率轴不是 A 级（即概率含估算成分），就必须声明"仅作方向筛选"。
  // 原先只看 cutoffGrade==='C'，国考（线是 A 级但 μ/σ 是 C 级）就漏了声明（MJ-04）。
  if (caliber.probabilityGrade && caliber.probabilityGrade !== 'A') {
    lines.push('');
    // 原因要按实际情况写：国考的线是官方 A 级，但 μ/σ 仍是用户自报的 C 级，
    // 写死「省考无官方逐岗线」在国考报告里就是错误陈述。
    const grade = caliber.probabilityGrade;
    const reason =
      caliber.cutoffGrade === 'C'
        ? '进面线本身是 C 级代理（官方不公布逐岗线），且 μ/σ 为自报值'
        : '进面线虽取自官方（A 级），但 μ/σ 为用户自报（C 级），概率整体仍是估算';
    lines.push(
      '> ⚠️ 概率整体为 **' +
        grade +
        ' 级**（' +
        reason +
        '）。帕累托前沿在此仅作**方向筛选**（剔除两轴都不优的岗），' +
        '不参与任何综合得分计算。前沿内部的先后顺序不代表优劣。',
    );
  }
  return lines.join('\n');
}

/** 依据段：口径声明 + 数据级别 */
function renderBasis(input: ReportInput): string {
  const { caliber, examType } = input;
  const lines: string[] = ['## 依据', '', '### 判断口径声明', ''];
  lines.push('| 项 | 取值 | 级别 | 说明 |');
  lines.push('|----|------|------|------|');
  lines.push(
    `| 笔试基线 μ | ${cell(caliber.mu == null ? '未指定' : caliber.mu)} | C | 用户自报或模考统计，非官方 |`,
  );
  lines.push(
    `| 整卷波动 σ | ${cell(caliber.sigma == null ? '未指定' : caliber.sigma)} | C | 无模考记录时为主观给定 |`,
  );
  lines.push(`| 进面线 | ${cell(caliber.cutoffSource)} | ${caliber.cutoffGrade} | 见下 |`);
  lines.push(`| 误差范围 | ${cell(caliber.tolerance)} | — | 概率绝对值仅供参考 |`);
  lines.push('');
  lines.push(`**考试类型**：${examType === 'sk' ? '省考（sk）' : '国考（gk）'} —— ${examTypeNote(examType)}`);
  lines.push('');
  lines.push('### 数据分级', '');
  lines.push('| 级别 | 含义 | 本报告中的用途 |');
  lines.push('|------|------|----------------|');
  lines.push('| A 一手 | 官方原件 | 职位表、报名人数、部门预算 |');
  lines.push('| B 二手·可核验 | 有原始附件或可复算式 | 区级薪酬区间（可参与排序） |');
  lines.push('| C 二手·估算 | 无法验证、样本不明 | 进面概率（**只读方向，不进排序公式**） |');
  lines.push('| D 禁用 | 营销模板、明显矛盾 | 本报告不引用任何 D 级数据 |');
  return lines.join('\n');
}

/** 数据表段 */
function renderTable(input: ReportInput): string {
  const lines: string[] = ['## 数据表', ''];
  lines.push(
    '| 岗位 | 代码 | 地区 | 招录 | 年全包（万） | 进面概率 | 竞争比 | 强度 | 服务期 | 前沿 |',
  );
  lines.push('|------|------|------|------|--------------|----------|--------|------|--------|------|');
  for (const row of input.rows) {
    const pay = `${row.payMin}–${row.payMax}${gradeSuffix(row.payGrade)}`;
    const prob = row.probability == null ? '—' : `${formatProbability(row.probability)}${gradeSuffix(row.probabilityGrade)}`;
    const ratio = row.ratio == null ? '—' : `${Math.round(row.ratio)}:1`;
    const service = row.minServiceYears == null ? '—' : `${row.minServiceYears} 年`;
    lines.push(
      `| ${cell(row.label)} | ${cell(row.code)} | ${cell(row.region)} | ${cell(row.hires)} | ${pay} | ${prob} | ${ratio} | ${intensitySummary(row.intensity)} | ${service} | ${row.frontier ? '★' : ''} |`,
    );
  }
  return lines.join('\n');
}

/** 局限段 */
function renderLimitations(input: ReportInput): string {
  const lines: string[] = ['## 局限', ''];
  const items = input.limitations.length ? input.limitations : ['无已知局限（仍受样本与数据时效限制）'];
  for (const item of items) lines.push(`- ${item}`);
  return lines.join('\n');
}

/** 待核段 */
function renderPending(input: ReportInput): string {
  const lines: string[] = ['## 待核', ''];
  const items = input.pendingChecks.length ? input.pendingChecks : ['无需人工确认的事项'];
  for (const item of items) lines.push(`- ${item}`);
  return lines.join('\n');
}

/**
 * 渲染完整 Markdown 报告。
 *
 * 五段**总是全部输出**（空段写「无」），因为「省略」会被误读为「没想到」。
 * 范围外提示由调用方传入（scope.ts 生成），保证单一实现。
 */
export function renderMarkdownReport(input: ReportInput, title = '选岗分析报告'): string {
  const header: string[] = [`# ${title}`, ''];
  const fp = input.fingerprint;
  const scope = input.cities.length ? input.cities.join('、') : '全量';
  header.push(`- 分析范围：${scope}`);
  header.push(`- 候选岗位数：${input.rows.length}`);
  if (fp?.generatedAt) header.push(`- 生成时间：${fp.generatedAt}`);
  if (fp?.sources?.length) {
    header.push('- 数据源指纹：');
    for (const src of fp.sources) header.push(`  - ${src}`);
  }
  header.push('');
  header.push('> 本报告按固定五段输出（结论 → 依据 → 数据表 → 局限 → 待核）。空段写「无」，不省略，');
  header.push('> 以便读者判断"确实没有"而非"没有考虑"。');
  header.push('');

  return [
    ...header,
    renderConclusion(input),
    '',
    renderBasis(input),
    '',
    renderTable(input),
    '',
    renderLimitations(input),
    '',
    renderPending(input),
    '',
    input.scopeNotice,
    '',
  ].join('\n');
}

/** 从概率结果收集「待核」项（缺输入、量级警告、C 级线） */
export function pendingFromProbability(
  prob: ProbabilityResult | null,
  label: string,
): string[] {
  if (!prob) return [`${label}：未计算进面概率（未提供 μ/σ 或报名人数）`];
  const items: string[] = [];
  if (prob.missingInputs.length) {
    items.push(`${label}：进面概率缺少输入 ${prob.missingInputs.join('、')}，概率列为「—」`);
  }
  if (prob.cutoffGraded?.grade === 'C') {
    items.push(`${label}：进面线为 C 级代理值（只读方向，不进排序公式）`);
  }
  return items;
}
