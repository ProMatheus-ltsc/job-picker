#!/usr/bin/env tsx
/**
 * 选岗流水线 CLI —— skill 入口
 *
 * ⚠️ 一致性保证：
 *   本脚本**不自己实现判定逻辑**，而是 import `engine/` 下的引擎。
 *   `engine/` 是从 job-picker 仓库原样复制（目录结构保持一致，import 零修改）。
 *   → 因此本脚本的结论与 job-picker 的 TS 脚本**必然一致**（同一份代码）。
 *
 * 用法：
 *   npx tsx scripts/pick.ts --jobs <职位表.xls> \
 *     --major 法学 --major-class 法学类 --cities 浙江,陕西,广东 \
 *     --grassroots 5 --political none --degree 本科 [--json out.json]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { parseXlsx } from '../engine/io/parseXlsx';
import { autoSuggestMapping, buildJobs, suggestRemarkCols } from '../engine/core/mapping';
import { buildSelectionReport } from '../engine/core/report';
import { estimateCompetition, hardGates } from '../engine/core/competition';
import { estimateSalary, yearsForHousing } from '../engine/core/salary';
import type { Job, Profile } from '../engine/types';

// ── 参数 ──────────────────────────────────────────────────────────
function opt(name: string, def = ''): string {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const file = opt('jobs') || process.argv[2];
if (!file) {
  console.error('用法：npx tsx scripts/pick.ts --jobs <职位表> [--major 法学 --major-class 法学类 --cities 浙江,陕西,广东 ...]');
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

// ── 主流程 ────────────────────────────────────────────────────────
async function main(): Promise<void> {
  const buf = readFileSync(file);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  const parsed = await parseXlsx(ab);
  if (!parsed.ok) {
    console.error(`✗ 解析失败：${parsed.error.message}`);
    process.exit(1);
  }

  const jobs: Job[] = [];
  for (const sheet of parsed.data.sheets) {
    if (!sheet.rows.length) continue;
    const raw = { sheetName: sheet.name, columns: sheet.columns, rows: sheet.rows };
    const mapping = autoSuggestMapping(raw.columns);
    const built = buildJobs(raw, mapping, suggestRemarkCols(raw.columns, mapping), 4);
    if (built.ok) jobs.push(...built.data.jobs);
  }

  const rep = buildSelectionReport(jobs, profile);

  // 结构化输出（供下游 / 对比）
  const payload = {
    input: { file, profile },
    summary: { total: rep.total, pass: rep.pass, fail: rep.fail, warn: rep.warn },
    candidates: rep.ranked.map((r) => ({
      code: r.job.code,
      key: r.job.key,
      unit: r.job.unit,
      title: r.job.title,
      region: r.job.region,
      hires: r.job.hires,
      competition: r.comp.score,
      level: r.comp.level,
      star: r.star,
      yearsForHousing: r.yearsForHousing,
      gates: r.gates,
    })),
  };

  const jsonOut = opt('json');
  if (jsonOut) {
    writeFileSync(jsonOut, JSON.stringify(payload, null, 2), 'utf-8');
    console.log(`✓ JSON → ${jsonOut}`);
  }

  // 文本报告
  console.log(`专业口径：${profile.major}/${profile.majorCategory} ｜ 目标：${profile.targetCities.join(' + ') || '不限'}`);
  console.log(`纳入判定 ${rep.total} ｜ ✅ ${rep.pass} ｜ ❌ ${rep.fail} ｜ ⚠ ${rep.warn}\n`);
  console.log('推荐  城市        招  竞争度  指数   买房年  门槛');
  console.log('-'.repeat(72));
  for (const r of rep.ranked.slice(0, 20)) {
    const stars = '★'.repeat(Math.floor(r.star)) + (r.star % 1 >= 0.5 ? '☆' : '');
    console.log(
      `${stars.padEnd(5, '　')} ${(r.job.region || '').slice(0, 9).padEnd(9, '　')} ` +
        `${String(r.job.hires ?? '?').padStart(2)}  ${r.comp.level.padEnd(4, '　')} ${String(r.comp.score).padStart(4)}  ` +
        `${String(r.yearsForHousing + '年').padStart(6)}  ${r.gates.length ? r.gates.join('+') : '无'}`,
    );
  }

  // 抽样自检：前 3 个候选的竞争度拆解（便于人工核对）
  console.log('\n竞争度拆解（前 3）：');
  for (const r of rep.ranked.slice(0, 3)) {
    const c = estimateCompetition(r.job);
    const s = estimateSalary(r.job.region);
    console.log(`  [${r.job.code}] ${r.job.unit}`);
    console.log(`    竞争 ${c.score}(${c.level}) ｜ 报录比参考 ≈${c.ratioRef}:1 ｜ 进面分参考 ${c.cutoffRef}`);
    console.log(`    薪酬 ${s.payMin}-${s.payMax}万 ｜ 房价 ${s.housePrice}/㎡ ｜ 买房 ${yearsForHousing(s)}年`);
    console.log(`    额外门槛：${hardGates(r.job).join('、') || '无'}`);
  }
}

main();
