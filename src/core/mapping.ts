/**
 * 列映射（05 §4.3 契约；demo buildJobs/autoGuessMapping 逻辑迁移为索引口径）
 */
import { FIELDS, num, type Job, type Mapping, type RawTable, type Result } from '../types';
import { err, ok } from '../types';
import { roundIncomeScore } from './scoring';

/**
 * 同名精确相等或包含关系的源列自动预填（F-02 规则 2，demo 词表口径原样迁移）
 */
export function autoSuggestMapping(columns: string[]): Mapping {
  const mapping: Mapping = {};
  FIELDS.forEach((f) => {
    const base = f.name.replace(/\(.*\)/, '');
    const hit =
      columns.find((c) => c === f.name) ||
      columns.find((c) => c.replace(/\s/g, '') === base) ||
      columns.find((c) => c.includes(base) || base.includes(c.replace(/\(.*\)/, '')));
    mapping[f.key] = hit ? columns.indexOf(hit) : null;
  });
  return mapping;
}

/**
 * F-02 按映射生成岗位数组（demo 逻辑原样迁移，列名口径 → 索引口径）
 * - 数值字段 parseFloat（失败 → null）
 * - 打分列未映射/为空 → roundIncomeScore 自动生成（40 万 → 40 分）
 * - remarkCols 按勾选拼接「列名: 内容」换行并入备注
 * - 岗位代码或招聘单位为空的行跳过并计入 skipped
 */
export function buildJobs(
  raw: RawTable,
  mapping: Mapping,
  remarkCols: number[],
  roundsLength: number,
  prevMarksByCode?: Map<string, Job['marks']>,
): Result<{ jobs: Job[]; skipped: number }> {
  const jobs: Job[] = [];
  let skipped = 0;
  const remarkIdx = (remarkCols ?? []).filter((i) => i >= 0 && i < raw.columns.length);

  // code 重复行后者覆盖前者（契约 §4.3），用 Map 索引
  const byCode = new Map<string, Job>();

  raw.rows.forEach((row) => {
    const cell = (idx: number | null | undefined): string =>
      idx != null && idx >= 0 ? String(row[idx] ?? '') : '';
    const numCell = (idx: number | null | undefined): number | null => {
      const v = cell(idx);
      if (v === '') return null;
      const n = parseFloat(v);
      return isNaN(n) ? null : n;
    };

    const code = cell(mapping.code).trim();
    const unit = cell(mapping.unit).trim();
    if (!code || !unit) {
      skipped++;
      return;
    }

    const job: Job = {
      code,
      unit,
      title: cell(mapping.title),
      avgIncome: numCell(mapping.avgIncome),
      netIncome: numCell(mapping.netIncome),
      incomeScore: numCell(mapping.incomeScore),
      netScore: numCell(mapping.netScore),
      applicants: numCell(mapping.applicants),
      hires: numCell(mapping.hires),
      region: cell(mapping.region).trim(),
      degree: cell(mapping.degree).trim(),
      major: cell(mapping.major),
      intro: cell(mapping.intro),
      remark: remarkIdx
        .map((i) => {
          const v = String(row[i] ?? '').trim();
          return v ? `${raw.columns[i]}: ${v}` : '';
        })
        .filter(Boolean)
        .join('\n'),
      marks: Array.from({ length: roundsLength }, () => 'pending' as const),
    };

    // 打分默认规则：未映射/为空时按年收入万数四舍五入（F-02 规则 7）
    if (job.incomeScore == null) job.incomeScore = roundIncomeScore(job.avgIncome);
    if (job.netScore == null) job.netScore = roundIncomeScore(job.netIncome);

    // 重新映射同一数据时轮次标记按岗位代码保留（F-02 规则 8）
    if (prevMarksByCode) {
      const prev = prevMarksByCode.get(code);
      if (prev) {
        // 标记长度对齐当前轮次数（新增轮次补 pending）
        job.marks = Array.from({ length: roundsLength }, (_, r) => prev[r] ?? 'pending');
      }
    }

    if (byCode.has(code)) {
      skipped++; // 重复 code 后者覆盖前者，计 skipped
    }
    byCode.set(code, job);
  });

  byCode.forEach((j) => jobs.push(j));
  return ok({ jobs, skipped });
}

/** 必填字段（岗位代码/招聘单位）未映射 → E_MAP_REQUIRED（向导第 2 步进入下一步前校验） */
export function validateMapping(mapping: Mapping): Result<null> {
  const missing = FIELDS.filter((f) => f.required && mapping[f.key] == null).map((f) => f.name);
  if (missing.length) {
    return err('E_MAP_REQUIRED', `必填字段未映射：${missing.join('、')}`);
  }
  return ok(null);
}

/** demo 首行示例展示用：取某列首行值 */
export function sampleOf(raw: RawTable, colIdx: number | null | undefined): string {
  if (colIdx == null) return '';
  return String(raw.rows[0]?.[colIdx] ?? '');
}

export { num };
