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
  // 双学位：--majors 法学,物理学 会拼成「法学|物理学」，由 majorHit 按门类族分别匹配
  major: opt('majors', opt('major', '法学')).replace(/[,，]/g, '|'),
  majorCategory: opt('major-class', '法学类').replace(/[,，]/g, '|'),
  grassrootsYears: opt('grassroots') ? Number(opt('grassroots')) : null,
  politicalStatus: (opt('political', 'none') as Profile['politicalStatus']) || 'none',
  hasLegalCert: opt('legal-cert') === '1',
  // 广州户籍（仅省考岗位会用到；国考基本不限户籍）
  hukou: opt('hukou'),
  fresh: opt('fresh') === '1',
  gender: (opt('gender') as Profile['gender']) || '',
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
      /** 职位类型（广东省考决定申论考哪张卷：综合管理类 / 行政执法类 / 公安执法勤务） */
      institution: r.job.institution,
      competition: r.comp.score,
      level: r.comp.level,
      star: r.star,
      yearsForHousing: r.yearsForHousing,
      gates: r.gates,
      // 薪酬（推算）：见 engine/core/salary.ts 的口径说明
      salary: {
        city: r.salary.city,
        payMin: r.salary.payMin,
        payMax: r.salary.payMax,
        cashMin: r.salary.cashMin,
        cashMax: r.salary.cashMax,
        fundMin: r.salary.fundMin,
        fundMax: r.salary.fundMax,
        housePrice: r.salary.housePrice,
        basis: r.salary.basis,
        precise: r.salary.precise,
      },
    })),
  };

  const jsonOut = opt('json');
  if (jsonOut) {
    writeFileSync(jsonOut, JSON.stringify(payload, null, 2), 'utf-8');
    console.log(`✓ JSON → ${jsonOut}`);
  }

  // 文本报告
  console.log(`专业口径：${profile.major.replace(/\|/g, ' 或 ')} / ${profile.majorCategory.replace(/\|/g, ' 或 ')} ｜ 目标：${profile.targetCities.join(' + ') || '不限'}`);
  console.log(`画像：${profile.degree} ｜ 基层 ${profile.grassrootsYears ?? '未填'} 年 ｜ ${profile.politicalStatus === 'party' ? '党员' : '非党员'} ｜ ${profile.hasLegalCert ? '有' : '无法考证书'} ｜ ${profile.gender || '性别未填'} ｜ ${profile.fresh ? '应届' : '非应届'}`);
  console.log(`纳入判定 ${rep.total} ｜ ✅ ${rep.pass} ｜ ❌ ${rep.fail} ｜ ⚠ ${rep.warn}\n`);
  // 表格必须带单位名：只显示「广州」时 96 个候选长得一模一样，无法据此选岗
  console.log('推荐  城市    招  竞争度     指数  买房年  单位 · 职位');
  console.log('-'.repeat(118));
  for (const r of rep.ranked.slice(0, 25)) {
    const stars = '★'.repeat(Math.floor(r.star)) + (r.star % 1 >= 0.5 ? '☆' : '');
    const name = `${r.job.unit} ${r.job.title}`.slice(0, 40);
    console.log(
      `${stars.padEnd(5, '　')} ${(r.job.region || '').slice(0, 5).padEnd(5, '　')} ` +
        `${String(r.job.hires ?? '?').padStart(2)}  ${r.comp.level.padEnd(3, '　')} ${String(r.comp.score).padStart(4)}  ` +
        `${String(r.yearsForHousing + '年').padStart(5)}  ${name}${r.gates.length ? ` [${r.gates.join('+')}]` : ''}`,
    );
  }
  if (rep.ranked.length > 25) console.log(`… 另有 ${rep.ranked.length - 25} 个候选，见 --json 输出`);
  const noGate = rep.ranked.filter((r) => !r.gates.length).length;
  console.log(`\n候选合计 ${rep.ranked.length} 个 ｜ 无额外门槛 ${noGate} 个 ｜ 有门槛 ${rep.ranked.length - noGate} 个`);
  console.log(`淘汰原因：${rep.failReasons.map((f) => `${f.label} ${f.count}`).join(' ｜ ')}`);

  // 职位类型分布：广东省考里它决定申论考哪张卷，比"哪个单位"更影响备考成本
  const instCount = new Map<string, number>();
  rep.ranked.forEach((r) => {
    const k = String(r.job.institution ?? '').trim() || '（未标注）';
    instCount.set(k, (instCount.get(k) ?? 0) + 1);
  });
  if (instCount.size > 1) {
    console.log('\n职位类型（决定申论考哪张卷）：');
    [...instCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .forEach(([k, n]) => console.log(`  ${k.padEnd(14, '　')} ${n} 个`));
  }

  // 抽样自检：前 3 个候选的竞争度拆解（便于人工核对）
  console.log('\n竞争度拆解（前 3）：');
  for (const r of rep.ranked.slice(0, 3)) {
    const c = estimateCompetition(r.job);
    const s = estimateSalary(r.job.region);
    console.log(`  [${r.job.code}] ${r.job.unit}`);
    console.log(`    竞争 ${c.score}(${c.level}) ｜ 报录比参考 ≈${c.ratioRef}:1 ｜ 进面分参考 ${c.cutoffRef}`);
    console.log(`    薪酬 ${s.payMin}-${s.payMax}万 ｜ 房价 ${s.housePrice}/㎡ ｜ 买房 ${yearsForHousing(s)}年`);
    console.log(`    额外门槛：${hardGates(r.job).filter((g) => g !== '性别限制').join('、') || '无'}`);
  }
}

main();
