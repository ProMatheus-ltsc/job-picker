#!/usr/bin/env tsx
/**
 * 选岗流水线 CLI —— skill 入口
 *
 * ⚠️ 一致性保证：
 *   本脚本**不自己实现判定逻辑**，而是 import `engine/` 下的引擎。
 *   `engine/` 是从 job-picker 仓库原样复制（目录结构保持一致，import 零修改）。
 *
 * 用法：
 *   npx tsx scripts/pick.ts --jobs <职位表.xls> \
 *     --major 法学 --major-class 法学类 --cities 广州,深圳 \
 *     --grassroots 5 --political none --degree 本科 \
 *     --exam-type sk --mu 67 --sigma 3.5 --cutoff 65,70 \
 *     --json out.json --report-out report.md --scatter-out scatter.html
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { parseXlsx } from '../engine/io/parseXlsx';
import { autoSuggestMapping, buildJobs, suggestRemarkCols } from '../engine/core/mapping';
import { buildSelectionReport, type SelectionReport } from '../engine/core/report';
import { estimateCompetition, hardGates } from '../engine/core/competition';
import { estimateSalary, salaryLabel, yearsForHousing } from '../engine/core/salary';
import { intensitySummary } from '../engine/core/intensity';import { formatProbability } from '../engine/core/probability';
import { paretoSummary } from '../engine/core/pareto';
import { renderScopeNotice } from '../engine/core/scope';
import {
  EXAM_TYPE_LABEL,
  EXAM_TYPE_USAGE,
  GK_CUTOFF_SOURCE,
  SK_CUTOFF_SOURCE,
  cutoffGrade,
  examTypeNote,
  parseExamType,
} from '../engine/core/examMode';
import { renderScatterHtml } from '../engine/io/scatter';
import { renderMarkdownReport, pendingFromProbability, type ReportRow } from '../engine/io/markdownReport';
import type { Job, Profile } from '../engine/types';

// ── 参数 ──────────────────────────────────────────────────────────
function opt(name: string, def = ''): string {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

function has(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

function writeOut(path: string, content: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, 'utf-8');
}

const file = opt('jobs') || process.argv[2];
if (!file) {
  console.error(
    '用法：npx tsx scripts/pick.ts --jobs <职位表> [--major 法学 --major-class 法学类 --cities 浙江,陕西,广东 ...]',
  );
  console.error(`      ${EXAM_TYPE_USAGE}`);
  console.error('      [--mu 67 --sigma 3.5 --cutoff 65,70 --report-out report.md --scatter-out scatter.html]');
  process.exit(2);
}

// ── 考试类型（P0-2）：非法取值直接退出 2，禁止静默回退 ─────────────
const examType = parseExamType(opt('exam-type'));
if (examType == null) {
  console.error(`✗ 非法 --exam-type 取值：${opt('exam-type')}`);
  console.error(`  合法取值：${EXAM_TYPE_USAGE}`);
  process.exit(2);
}

const profile: Profile = {
  degree: (opt('degree', '本科') as Profile['degree']) || '',
  regions: [],
  targetCities: opt('cities').split(',').map((s) => s.trim()).filter(Boolean),
  major: opt('major', '法学'),
  majorCategory: opt('major-class', '法学类'),
  grassrootsYears: opt('grassroots') ? Number(opt('grassroots')) : null,
  politicalStatus: (opt('political', 'none') as Profile['politicalStatus']) || 'none',
  hasLegalCert: opt('legal-cert') === '1',
  // 广州户籍（仅省考岗位会用到；国考基本不限户籍）
  hukou: opt('hukou'),
  fresh: opt('fresh') === '1',
} as Profile;

// ── 概率模型输入（P1-2）─────────────────────────────────────────
const mu = opt('mu') ? Number(opt('mu')) : null;
const sigma = opt('sigma') ? Number(opt('sigma')) : null;
const cutoffRaw = opt('cutoff');
let cutoffMin: number | null = null;
let cutoffMax: number | null = null;
if (cutoffRaw) {
  const parts = cutoffRaw.split(',').map((s) => Number(s.trim()));
  if (parts.some((n) => isNaN(n))) {
    console.error(`✗ --cutoff 需为「下沿」或「下沿,上沿」的数值，收到：${cutoffRaw}`);
    process.exit(2);
  }
  cutoffMin = parts[0];
  cutoffMax = parts.length > 1 ? parts[1] : parts[0];
}
const interviewRatio = opt('ratio') ? Number(opt('ratio')) : 3;
const keepHeavy = has('keep-heavy');

// ── 主流程 ────────────────────────────────────────────────────────
async function main(): Promise<void> {
  const buf = readFileSync(file);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  const parsed = await parseXlsx(ab);
  if (!parsed.ok) {
    console.error(`✗ 解析失败：${parsed.error.message}`);
    console.error('  若提示「文件已损坏」，通常是依赖未安装：在 skill 目录执行 npm i');
    process.exit(1);
  }

  const jobs: Job[] = [];
  const sheetErrors: Array<{ sheet: string; error: string }> = [];
  for (const sheet of parsed.data.sheets) {
    if (!sheet.rows.length) continue;
    try {
      const raw = { sheetName: sheet.name, columns: sheet.columns, rows: sheet.rows };
      const mapping = autoSuggestMapping(raw.columns);
      const built = buildJobs(raw, mapping, suggestRemarkCols(raw.columns, mapping), 4);
      if (built.ok) jobs.push(...built.data.jobs);
      else sheetErrors.push({ sheet: sheet.name, error: built.error.message });
    } catch (error) {
      // 单 sheet 失败不得中断整表（省考 6 sheet 里任何一个表头异常都不该毁掉整次分析）
      sheetErrors.push({
        sheet: sheet.name,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  if (sheetErrors.length) {
    console.error(`⚠ ${sheetErrors.length} 个 sheet 解析失败（其余继续）：`);
    for (const item of sheetErrors) console.error(`  - ${item.sheet}: ${item.error}`);
  }

  const rep: SelectionReport = buildSelectionReport(jobs, profile, {
    examType,
    mu,
    sigma,
    cutoffMin,
    cutoffMax,
    interviewRatio,
    keepHeavy,
  });

  // 结构化输出（供下游 / 对比）
  const payload = {
    input: {
      file,
      examType,
      profile,
      probability: { mu, sigma, cutoffMin, cutoffMax, interviewRatio },
      keepHeavy,
    },
    summary: {
      total: rep.total,
      pass: rep.pass,
      fail: rep.fail,
      warn: rep.warn,
      examType: rep.examType,
      excludedByIntensity: rep.excludedByIntensity.length,
    },
    candidates: rep.ranked.map((r) => ({
      code: r.job.code,
      key: r.job.key,
      unit: r.job.unit,
      title: r.job.title,
      region: r.job.region,
      regionLabel: salaryLabel(r.salary),
      sourceSheet: r.job.sourceSheet,
      minServiceYears: r.job.minServiceYears,
      hires: r.job.hires,
      salary: {
        payMin: r.salary.payMin,
        payMax: r.salary.payMax,
        mid: r.salaryMid,
        district: r.salary.district,
        precise: r.salary.precise,
        basis: r.salary.basis,
      },
      intensity: r.intensity,
      probability: r.probability
        ? {
            p: r.probability.p,
            pAtMinLine: r.probability.pAtMinLine,
            pAtMaxLine: r.probability.pAtMaxLine,
            quota: r.probability.quota,
            missingInputs: r.probability.missingInputs,
            magnitudeWarning: r.probability.magnitudeWarning,
            cutoffGrade: r.probability.cutoffGraded?.grade ?? null,
          }
        : null,
      competition: r.comp.score,
      level: r.comp.level,
      star: r.star,
      yearsForHousing: r.yearsForHousing,
      gates: r.gates,
    })),
    excludedByIntensity: rep.excludedByIntensity.map((item) => ({
      code: item.job.code,
      unit: item.job.unit,
      title: item.job.title,
      region: item.job.region,
      sourceSheet: item.job.sourceSheet,
      minServiceYears: item.job.minServiceYears,
      intensity: item.intensity,
    })),
    pareto: rep.pareto,
    diagnostics: {
      sheetErrors,
      intensityTags: rep.intensityTags,
      failReasons: rep.failReasons,
      riskTags: rep.riskTags,
    },
  };

  const jsonOut = opt('json');
  if (jsonOut) {
    writeOut(jsonOut, JSON.stringify(payload, null, 2));
    console.log(`✓ JSON → ${jsonOut}`);
  }

  // ── 文本报告 ──
  console.log(
    `考试类型：${EXAM_TYPE_LABEL[examType]}（${examType}）｜专业口径：${profile.major}/${profile.majorCategory}` +
      ` ｜ 目标：${profile.targetCities.join(' + ') || '不限'}`,
  );
  console.log(`纳入判定 ${rep.total} ｜ ✅ ${rep.pass} ｜ ❌ ${rep.fail} ｜ ⚠ ${rep.warn}`);
  if (rep.excludedByIntensity.length) {
    console.log(`强度筛查：排除 ${rep.excludedByIntensity.length} 个 heavy 岗位（值班/执法/应急）`);
  }
  console.log('');
  console.log('推荐  地区            招  竞争度  指数   买房年  强度    服务期  门槛');
  console.log('-'.repeat(92));
  for (const r of rep.ranked.slice(0, 20)) {
    const stars = '★'.repeat(Math.floor(r.star)) + (r.star % 1 >= 0.5 ? '☆' : '');
    const service = r.job.minServiceYears == null ? '—' : `${r.job.minServiceYears}年`;
    console.log(
      `${stars.padEnd(5, '　')} ${salaryLabel(r.salary).slice(0, 9).padEnd(9, '　')} ` +
        `${String(r.job.hires ?? '?').padStart(2)}  ${r.comp.level.padEnd(4, '　')} ${String(r.comp.score).padStart(4)}  ` +
        `${String(r.yearsForHousing + '年').padStart(6)}  ${r.intensity.level.padEnd(6, '　')} ${service.padStart(5)}  ` +
        `${r.gates.length ? r.gates.join('+') : '无'}`,
    );
  }

  // 抽样自检：前 3 个候选的拆解（便于人工核对）
  console.log('\n拆解（前 3）：');
  for (const r of rep.ranked.slice(0, 3)) {
    const c = estimateCompetition(r.job);
    console.log(`  [${r.job.code}] ${r.job.unit}${r.job.title ? `·${r.job.title}` : ''}`);
    console.log(`    竞争 ${c.score}(${c.level}) ｜ 报录比参考 ≈${c.ratioRef}:1`);
    console.log(
      `    薪酬 ${r.salary.payMin}-${r.salary.payMax}万（${salaryLabel(r.salary)}）｜ 房价 ${r.salary.housePrice}/㎡ ｜ 买房 ${yearsForHousing(r.salary)}年`,
    );
    console.log(
      `    强度 ${intensitySummary(r.intensity)} ｜ 服务期 ${r.job.minServiceYears ?? '—'}`,
    );
    if (r.probability) {
      console.log(
        `    进面概率 ${formatProbability(r.probability.p)}（名额 ${r.probability.quota} ｜ 报名 ${r.probability.applicants ?? '—'}）`,
      );
      if (r.probability.magnitudeWarning) console.log(`    ⚠ ${r.probability.magnitudeWarning}`);
    } else {
      console.log('    进面概率：未计算（缺 μ/σ/报名人数）');
    }
    console.log(`    额外门槛：${hardGates(r.job).join('、') || '无'}`);
  }

  if (rep.ranked.length) {
    console.log(`\n帕累托（薪酬 × 概率）：${paretoSummary(rep.pareto)}`);
  }

  // ── 范围外提示（P1-4）：报告与 stdout 都要出现 ──
  const scopeNotice = renderScopeNotice({
    cities: profile.targetCities,
    inScopeTotal: rep.total,
    fullScan: !profile.targetCities.length,
    adjacentRegions: profile.targetCities.length ? ['珠三角其他城市', '粤东西北'] : [],
  });
  console.log(`\n${scopeNotice}`);

  // ── Markdown 报告（P2 P1-4）──
  const reportOut = opt('report-out');
  if (reportOut) {
    const frontier = new Set(rep.pareto.frontier.map((p) => p.key));
    const rows: ReportRow[] = rep.ranked.map((r) => ({
      label: `${r.job.unit}${r.job.title ? `·${r.job.title}` : ''}`,
      code: r.job.code,
      region: salaryLabel(r.salary),
      hires: r.job.hires,
      payMin: r.salary.payMin,
      payMax: r.salary.payMax,
      payGrade: 'B',
      probability: r.probability?.p ?? null,
      probabilityGrade: cutoffGrade(examType),
      ratio:
        r.job.applicants != null && r.job.hires
          ? r.job.applicants / r.job.hires
          : null,
      intensity: r.intensity,
      minServiceYears: r.job.minServiceYears,
      frontier: frontier.has(r.job.code),
    }));

    const pending: string[] = [];
    for (const r of rep.ranked) {
      pending.push(...pendingFromProbability(r.probability, `${r.job.unit}·${r.job.title}`));
    }
    for (const item of rep.excludedByIntensity) {
      pending.push(
        `${item.job.unit}·${item.job.title}：因工作强度被排除（${intensitySummary(item.intensity)}），如可接受需 ` +
          '加 --keep-heavy 重跑',
      );
    }
    if (mu == null || sigma == null) {
      pending.push('未提供 --mu/--sigma，进面概率未计算；如需概率请补模考基线');
    }
    if (sheetErrors.length) {
      pending.push(`${sheetErrors.length} 个 sheet 解析失败，相关岗位未纳入（见 stderr）`);
    }

    const limitations: string[] = [
      '区级薪酬为 B 级（部门预算结构 + 样本交叉），误差约 ±15–20%，不等于工资单',
      '进面概率的 μ/σ 为 C 级（用户自报或主观给定），概率绝对值仅供参考，量级比数值可信',
      `进面线：${examType === 'sk' ? SK_CUTOFF_SOURCE : GK_CUTOFF_SOURCE}`,
    ];
    if (rep.excludedByIntensity.length) {
      limitations.push(
        `强度筛查排除 ${rep.excludedByIntensity.length} 个岗位；关键词表可能漏掉未覆盖的表达方式`,
      );
    }

    const report = renderMarkdownReport({
      examType,
      cities: profile.targetCities,
      caliber: {
        mu,
        sigma,
        cutoffSource: examType === 'sk' ? SK_CUTOFF_SOURCE : GK_CUTOFF_SOURCE,
        cutoffGrade: cutoffGrade(examType),
        tolerance: '薪酬 ±15–20%；概率绝对值 ±1 个量级（μ/σ 为 C 级）',
      },
      rows,
      pareto: rep.pareto,
      scopeNotice,
      limitations,
      pendingChecks: pending,
      magnitudeWarning:
        rep.ranked.find((r) => r.probability?.magnitudeWarning)?.probability?.magnitudeWarning ?? null,
      fingerprint: {
        generatedAt: new Date().toISOString(),
        sources: [
          `职位表：${file}`,
          `考试类型：${EXAM_TYPE_LABEL[examType]}（${examTypeNote(examType)}）`,
        ],
      },
    });
    writeOut(reportOut, report);
    console.log(`✓ Markdown 报告 → ${reportOut}`);
  }

  // ── 散点图（P2）──
  const scatterOut = opt('scatter-out');
  if (scatterOut) {
    const html = renderScatterHtml(
      rep.ranked.map((r) => {
        const s = estimateSalary(r.job.region);
        return {
          label: `${r.job.unit}${r.job.title ? `·${r.job.title}` : ''}`,
          city: salaryLabel(s),
          salaryMid: r.salaryMid,
          probability: r.probability?.p ?? null,
          ratio:
            r.job.applicants != null && r.job.hires ? r.job.applicants / r.job.hires : null,
        };
      }),
      `薪酬 × 进面概率（${EXAM_TYPE_LABEL[examType]}｜${profile.targetCities.join('、') || '全量'}）`,
    );
    writeOut(scatterOut, html);
    console.log(`✓ 散点图 → ${scatterOut}`);
  }
}

main().catch((error) => {
  console.error(`✗ 运行失败：${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
