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
import {
  buildSelectionReport,
  type BuildReportOptions,
  type SelectionReport,
} from '../engine/core/report';
import { estimateCompetition, hardGates, recommendStar } from '../engine/core/competition';
import { estimateSalary, salaryLabel, yearsForHousing } from '../engine/core/salary';
import { CATEGORY_LABEL, intensitySummary, scanIntensity } from '../engine/core/intensity';
import { estimateProbability, formatProbability } from '../engine/core/probability';
import { nonDominated, paretoSummary } from '../engine/core/pareto';
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
import { weakest, type DataGrade } from '../engine/core/datagrade';
import { renderScatterHtml } from '../engine/io/scatter';
import { renderMarkdownReport, pendingFromProbability, type ReportRow } from '../engine/io/markdownReport';
import { emptyProfileExtras, loadProfileFile } from '../engine/io/profileFile';
import type { Job, Profile } from '../engine/types';

// ── 参数 ──────────────────────────────────────────────────────────
function opt(name: string, def = ''): string {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--')
    ? process.argv[i + 1]
    : def;
}

function has(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

/** 显式给了 flag 但没给值（或下一个是另一个 flag）→ 视为用法错误，不静默回退默认值 */
function missingValue(name: string): boolean {
  const i = process.argv.indexOf(`--${name}`);
  if (i < 0) return false;
  const next = process.argv[i + 1];
  return !next || next.startsWith('--');
}

/**
 * 解析数值型参数：空 → null（未提供）；非法数字 → 退出 2。
 * 不能直接用 Number()，因为 `Number('abc')` 是 NaN，
 * 而 NaN 会静默传播成"概率算不出来"而不是"参数写错了"（CR 指出过这个问题）。
 */
function numOpt(name: string): number | null {
  if (missingValue(name)) {
    console.error(`✗ --${name} 缺少取值`);
    process.exit(2);
  }
  const raw = opt(name);
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    console.error(`✗ --${name} 需为数值，收到：${raw}`);
    process.exit(2);
  }
  return value;
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
  console.error('      [--mu 67 --sigma 3.5 --cutoff 65,70 --applicants numbers.json --report-out report.md]');
  process.exit(2);
}

// ── 考试类型（P0-2）：非法/缺值直接退出 2，禁止静默回退 ─────────────
if (missingValue('exam-type')) {
  console.error('✗ --exam-type 缺少取值');
  console.error(`  合法取值：${EXAM_TYPE_USAGE}`);
  process.exit(2);
}
const examType = parseExamType(opt('exam-type'));
if (examType == null) {
  console.error(`✗ 非法 --exam-type 取值：${opt('exam-type')}`);
  console.error(`  合法取值：${EXAM_TYPE_USAGE}`);
  process.exit(2);
}

// ── 报名人数（A 级一手数据，按需从文件读入并回填到岗位）────────────
// 契约（04-contracts §1.1）：--applicants 指向一个「职位代码 → 报名人数」的 JSON/CSV。
// 这是唯一的一手竞争度来源（官方只在报名期逐日公布），因此必须支持独立注入，
// 而不是只能依赖职位表里恰好带这一列。
const applicantsRaw = opt('applicants');
const applicantMap = new Map<string, number>();
if (applicantsRaw) {
  try {
    const text = readFileSync(applicantsRaw, 'utf-8');
    const trimmed = text.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      const data = JSON.parse(trimmed) as Record<string, unknown> | Array<Record<string, unknown>>;
      if (Array.isArray(data)) {
        for (const item of data) {
          const code = String(item.code ?? item['职位代码'] ?? '').trim();
          const count = Number(item.applicants ?? item['报名人数']);
          if (code && Number.isFinite(count)) applicantMap.set(code, count);
        }
      } else {
        for (const [code, count] of Object.entries(data)) {
          const value = Number(count);
          if (code.trim() && Number.isFinite(value)) applicantMap.set(code.trim(), value);
        }
      }
    } else {
      // CSV：首行表头，取 code/applicants（或 职位代码/报名人数）两列
      const lines = trimmed.split(/\r?\n/).filter(Boolean);
      const head = lines[0].split(',').map((s) => s.trim());
      const codeIdx = head.findIndex((h) => h === 'code' || h === '职位代码');
      const countIdx = head.findIndex((h) => h === 'applicants' || h === '报名人数');
      if (codeIdx < 0 || countIdx < 0) {
        console.error(`✗ --applicants 的 CSV 表头需含 code/applicants（或 职位代码/报名人数），收到：${head.join(',')}`);
        process.exit(2);
      }
      for (const line of lines.slice(1)) {
        const cells = line.split(',').map((s) => s.trim());
        const count = Number(cells[countIdx]);
        if (cells[codeIdx] && Number.isFinite(count)) {
          applicantMap.set(cells[codeIdx], count);
        }
      }
    }
  } catch (error) {
    console.error(
      `✗ --applicants 读取失败：${error instanceof Error ? error.message : String(error)}`,
    );
    process.exit(2);
  }
}

// ── 画像文件（REQ-012）：assets/profile.md 的新字段必须真的能被读取 ──
// 只加文档不加读取入口，等于文档撒谎（用户填了不生效）。因此这里显式解析并把
// 「接受强度 / 排除区 / 最低年薪 / 接受服务期」落成判定输入。
// 路径型参数缺值必须报错（静默忽略会让用户以为画像生效了）
for (const flag of ['profile', 'applicants', 'json', 'report-out', 'scatter-out', 'jobs']) {
  if (missingValue(flag)) {
    console.error(`✗ --${flag} 缺少取值`);
    process.exit(2);
  }
}

const profileFile = opt('profile');
const loaded = profileFile
  ? loadProfileFile(profileFile)
  : { profile: {}, extras: emptyProfileExtras(), found: false };
if (profileFile && !loaded.found) {
  console.error(`✗ 画像文件不可读：${profileFile}`);
  process.exit(2);
}
const extras = loaded.extras;

/**
 * 画像字段合并：CLI 显式给了就用 CLI，否则用画像文件的值，最后才用默认值。
 *
 * 为什么不能只读画像的「新增偏好字段」：那会让 --profile 里的学历/专业/目标城市
 * 静默失效（用户填了硬条件却不生效），是 CR 明确指出的缺陷。
 */
function pickString(cliValue: string, fileValue: string | undefined, fallback: string): string {
  if (cliValue) return cliValue;
  if (fileValue != null && String(fileValue).trim()) return String(fileValue).trim();
  return fallback;
}

const profile: Profile = {
  degree: pickString(opt('degree'), loaded.profile.degree, '本科') as Profile['degree'],
  regions: [],
  targetCities: opt('cities')
    ? opt('cities').split(',').map((s) => s.trim()).filter(Boolean)
    : (loaded.profile.targetCities ?? []),
  major: pickString(opt('major'), loaded.profile.major, '法学'),
  majorCategory: pickString(opt('major-class'), loaded.profile.majorCategory, '法学类'),
  grassrootsYears: numOpt('grassroots') ?? loaded.profile.grassrootsYears ?? null,
  politicalStatus: (pickString(
    opt('political'),
    loaded.profile.politicalStatus,
    'none',
  ) as Profile['politicalStatus']) || 'none',
  hasLegalCert: has('legal-cert')
    ? opt('legal-cert') === '1'
    : (loaded.profile.hasLegalCert ?? false),
  // 广州户籍（仅省考岗位会用到；国考基本不限户籍）
  hukou: opt('hukou'),
  fresh: has('fresh') ? opt('fresh') === '1' : (loaded.profile.fresh ?? false),
} as Profile;

// ── 概率模型输入（P1-2）─────────────────────────────────────────
const mu = numOpt('mu');
const sigma = numOpt('sigma');
const cutoffRaw = opt('cutoff');
let cutoffMin: number | null = null;
let cutoffMax: number | null = null;
if (missingValue('cutoff')) {
  console.error('✗ --cutoff 缺少取值');
  process.exit(2);
}
if (cutoffRaw) {
  const parts = cutoffRaw.split(',').map((s) => Number(s.trim()));
  if (parts.some((n) => !Number.isFinite(n))) {
    console.error(`✗ --cutoff 需为「下沿」或「下沿,上沿」的数值，收到：${cutoffRaw}`);
    process.exit(2);
  }
  cutoffMin = parts[0];
  cutoffMax = parts.length > 1 ? parts[1] : parts[0];
}
const interviewRatio = numOpt('ratio') ?? 3;
const keepHeavy = has('keep-heavy');

/** 强度类别 → 是否接受（null = 未表态，按默认排除处理并提示） */
function acceptsCategory(category: string): boolean | null {
  switch (category) {
    case 'duty':
      return extras.acceptDuty;
    case 'emergency':
      return extras.acceptEmergency;
    case 'enforce':
      return extras.acceptEnforce;
    case 'petition':
      return extras.acceptPetition;
    case 'travel':
      return extras.acceptTravel;
    default:
      return null;
  }
}


/**
 * 帕累托概率轴的级别 = 该批候选概率级别里最保守的一个。
 *
 * 与 `cutoffGrade` 的区别：cutoffGrade 只描述**进面线**的来源（国考 A / 省考 C），
 * 而概率还依赖 μ/σ（恒为 C），所以轴的级别恒为 C——除非所有候选都没有概率。
 */
function probabilityAxisGrade(result: SelectionReport): DataGrade {
  const grades = result.ranked
    .map((row) => row.probability?.probabilityGrade)
    .filter((g): g is DataGrade => !!g);
  if (!grades.length) return 'C';
  return weakest(...grades);
}

/** 按画像的强度偏好重判候选（精准排除"用户明确不接受"的类别） */
function filterByPreference(report: SelectionReport): SelectionReport {
  // ★ 必须把"接受"也算作偏好：否则「接受值班=是」不会触发重判，
  // heavy 岗位永远回不来（它们在 buildSelectionReport 内已被排除）。
  // 信访/出差也必须计入，否则单独设置这两项时 hasPreference 为 false 直接返回（MJ-02）。
  const hasPreference =
    extras.acceptDuty != null ||
    extras.acceptEmergency != null ||
    extras.acceptEnforce != null ||
    extras.acceptPetition != null ||
    extras.acceptTravel != null ||
    extras.excludeDistricts.length > 0 ||
    extras.minAnnualPackage != null ||
    extras.acceptServiceBond != null;
  if (!hasPreference) return report;

  const kept: typeof report.ranked = [];
  const dropped: Array<{ job: Job; reasons: string[] }> = [];


  for (const row of report.ranked) {
    const reasons: string[] = [];
    // ① 用户明确不接受的强度类别
    for (const hit of row.intensity.hits) {
      if (acceptsCategory(hit.category) === false) {
        reasons.push(
          `不接受「${CATEGORY_LABEL[hit.category]}」类（命中「${hit.kw}」于 ${hit.field}）`,
        );
      }
    }
    // ② 排除区
    const regionText = `${row.job.region} ${salaryLabel(row.salary)}`;
    const excludedDistrict = extras.excludeDistricts.find((d) => regionText.includes(d));
    if (excludedDistrict) reasons.push(`画像排除区：${excludedDistrict}`);
    // ③ 最低年薪（年全包口径）
    if (extras.minAnnualPackage != null && row.salary.payMax < extras.minAnnualPackage) {
      reasons.push(`年薪上限 ${row.salary.payMax} 万 < 可接受最低 ${extras.minAnnualPackage} 万`);
    }
    // ④ 不接受 5 年最低服务期
    if (extras.acceptServiceBond === false && (row.job.minServiceYears ?? 0) >= 5) {
      reasons.push(`不接受 ${row.job.minServiceYears} 年最低服务期`);
    }

    if (reasons.length) {
      dropped.push({ job: row.job, reasons });
    } else {
      kept.push(row);
    }
  }
  if (!dropped.length) return report;

  // ★ 过滤后必须重算帕累托：否则前沿集合仍包含已被排除的岗位，
  // 会出现「3 个候选却有 3 个前沿点」这种自相矛盾的输出（CR 指出过）。
  const recomputed = nonDominated(
    kept.map((r) => ({
      key: r.job.code,
      label: `${r.job.unit}${r.job.title ? `·${r.job.title}` : ''}`,
      salaryMid: r.salaryMid,
      probability: r.probability?.p ?? null,
    })),
  );

  return {
    ...report,
    // 候选数与 pass 数同步减少，避免报告里「纳入 N 个 / 候选 M 个」互相对不上
    pass: report.pass - dropped.length,
    total: report.total - dropped.length,
    ranked: kept,
    candidates: kept.map((r) => r.job),
    // 被画像排除的岗位与强度排除分开记录，报告里分别说明原因（不能混称"强度排除"）
    excludedByPreference: dropped,
    pareto: recomputed,
  };
}

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
  const parsedSheets: string[] = [];
  for (const sheet of parsed.data.sheets) {
    if (!sheet.rows.length) continue;
    try {
      const raw = { sheetName: sheet.name, columns: sheet.columns, rows: sheet.rows };
      const mapping = autoSuggestMapping(raw.columns);
      const built = buildJobs(raw, mapping, suggestRemarkCols(raw.columns, mapping), 4);
      if (built.ok) {
        jobs.push(...built.data.jobs);
        // 只要该 sheet 贡献了岗位就算「已解析」，用于诊断解析层是否覆盖全部 sheet
        if (built.data.jobs.length) parsedSheets.push(sheet.name);
      } else sheetErrors.push({ sheet: sheet.name, error: built.error.message });
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

  // 把 --applicants 提供的一手报名人数回填到岗位（职位表不一定带这一列）
  if (applicantMap.size) {
    let filled = 0;
    for (const job of jobs) {
      const count = applicantMap.get(job.code);
      if (count != null) {
        job.applicants = count;
        filled += 1;
      }
    }
    console.log(`报名人数：从 --applicants 回填 ${filled}/${jobs.length} 个岗位（一手 A 级）`);
  }

  // 画像明确接受的强度类别：交给构建阶段，命中这些类别的岗位不再判为"应排除"
  const acceptedCategories = (['duty', 'emergency', 'enforce', 'petition', 'travel'] as const).filter(
    (category) => acceptsCategory(category) === true,
  );

  const baseReport: SelectionReport = buildSelectionReport(jobs, profile, {
    examType,
    mu,
    sigma,
    cutoffMin,
    cutoffMax,
    interviewRatio,
    keepHeavy,
    acceptedCategories,
  });
  const rep: SelectionReport = filterByPreference(baseReport);

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
        // 级别随档位走（省直 A / 区级市级 B / 兜底 C），下游据此复现报告标注（m-02）
        grade: r.salary.grade,
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
            // 进面线的级别（国考 A / 省考 C）
            proxyGrade: cutoffGrade(examType),
            // ★ 概率整体的级别（weakest 合成）：即使国考线是 A 级，
            // μ/σ 仍是 C 级，整体必须标 C，否则与报告的数据分级段矛盾（CR-01）。
            probabilityGrade: r.probability.probabilityGrade,
            gradeInputs: r.probability.gradeInputs,
            capped: r.probability.capped ?? false,
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
    excludedByPreference: (rep.excludedByPreference ?? []).map((item) => ({
      code: item.job.code,
      unit: item.job.unit,
      title: item.job.title,
      region: item.job.region,
      reasons: item.reasons,
    })),
    pareto: {
      ...rep.pareto,
      // ★ 概率轴级别必须取**概率整体级别**（weakest 合成），不能取进面线级别：
      // 国考线是 A 级但 μ/σ 是 C 级，整条概率轴就是 C 级（MJ-04）。
      probabilityAxisGrade: probabilityAxisGrade(rep),
      usedAsRanking: false,
    },
    diagnostics: {
      sheetErrors,
      parsedSheets,
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
      // 薪酬级别直接取自薪酬档（estimateSalary 按匹配来源声明 A/B/C）：
      // 省直 A、区级与市级 B、层级兜底 C。
      // 不再解析 basis 文本——市级档的 basis 不含级别字样，猜出来会变 C（MJ-06）。
      payGrade: r.salary.grade,
      probability: r.probability?.p ?? null,
      // ★ 概率级别不能用进面线级别（CR-01）：国考线是 A 级，但 μ/σ 是 C 级，
      // 概率整体按最保守输入取级，否则报告数据表与数据分级段会自相矛盾。
      probabilityGrade: r.probability?.probabilityGrade ?? 'C',
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
    // 画像偏好排除与强度排除是两回事，报告里必须分开列（否则会被误读成「强度不过关」）
    for (const item of rep.excludedByPreference ?? []) {
      pending.push(
        `${item.job.unit}·${item.job.title}：因画像偏好被排除（${item.reasons.join('；')}）`,
      );
    }
    if (sheetErrors.length) {
      pending.push(`${sheetErrors.length} 个 sheet 解析失败，相关岗位未纳入（见 stderr）`);
    }

    // 薪酬口径按实际用到的级别生成：省直 A（±10%）、区级/市级 B（±15–20%）、兜底 C（估算）
    const payGrades = [...new Set(rows.map((row) => row.payGrade))];
    const payLimit =
      payGrades.includes('A')
        ? '省直薪酬为 A 级（部门预算反推），误差约 ±10%，不等于工资单'
        : payGrades.includes('C')
          ? '含 C 级薪酬（档位估算，无法核验），这类区间只能作量级参考，不参与精确比较'
          : '区级/市级薪酬为 B 级（部门预算结构 + 样本交叉），误差约 ±15–20%，不等于工资单';
    const limitations: string[] = [
      payLimit,
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
        // 概率整体级别（weakest）：报告的「仅作方向筛选」声明按它判断，
        // 否则国考（进面线 A 级但 μ/σ C 级）会漏掉声明（MJ-04）
        probabilityGrade: probabilityAxisGrade(rep),
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
