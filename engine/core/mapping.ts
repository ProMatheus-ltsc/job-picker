/**
 * 列映射（05 §4.3 契约；demo buildJobs/autoGuessMapping 逻辑迁移为索引口径）
 *
 * 兼容三类真实职位表：
 * - 国考（.xlsx，表头首行）：用人司局 / 招考人数 / 基层工作最低年限 …
 * - 广东省考（.xls，表头可能在第 2~3 行）：招考单位 / 录用人数 / 是否要求2年以上基层工作经历 …
 * - 浙江省考（.xlsx）：招录单位名称 / 招录人数 / 现有身份要求 / 专业要求 …
 */
import {
  FIELDS,
  isMapped,
  mappingIndices,
  num,
  type Job,
  type Mapping,
  type MappingValue,
  type RawTable,
  type Result,
  type StandardFieldKey,
} from '../types';
import { err, ok } from '../types';

/** 列名归一化：去空白（含换行/全角空格），用于跨表匹配 */
const norm = (s: string): string => String(s ?? '').replace(/[\s\u3000]/g, '');

/** 「本名 / 别名」对源列的包含式宽松匹配 */
function looseMatch(col: string, fieldName: string, aliases: string[]): boolean {
  const c = norm(col);
  const base = norm(fieldName.replace(/\(.*\)/, ''));
  if (!c) return false;
  if (c.includes(base) || base.includes(c)) return true;
  return aliases.some((a) => {
    const na = norm(a);
    return !!na && (c.includes(na) || na.includes(c));
  });
}

/**
 * 同名精确相等或包含关系的源列自动预填（F-02 规则 2）
 * - 单列字段：按「本名 → 别名顺序」取**第一个精确命中**，否则取第一个包含命中
 * - 多列字段（multi）：**全部精确命中合并**为数组（如广东的三列专业）
 */
export function autoSuggestMapping(columns: string[]): Mapping {
  const mapping: Mapping = {};
  FIELDS.forEach((f) => {
    const aliases = f.aliases ?? [];
    const order = [f.name, ...aliases].map(norm);

    // 精确命中集合（归一化后相等）
    const exact = columns.filter((c) => {
      const n = norm(c);
      return !!n && order.includes(n);
    });

    let hits: string[] = [];
    if (f.multi) {
      // 多列合并：精确命中全收；无精确命中则收全部包含命中
      hits = exact.length ? exact : columns.filter((c) => looseMatch(c, f.name, aliases));
    } else {
      // 单列：按优先级顺序找第一个精确命中（如 unit 的「用人司局」必须先于「部门名称」）
      let picked: string | undefined;
      for (const o of order) {
        picked = columns.find((c) => norm(c) === o);
        if (picked) break;
      }
      if (!picked) picked = columns.find((c) => looseMatch(c, f.name, aliases));
      hits = picked ? [picked] : [];
    }

    const idxs = hits.map((h) => columns.indexOf(h)).filter((i) => i >= 0);
    mapping[f.key] =
      idxs.length === 0 ? null : idxs.length === 1 ? idxs[0] : (idxs as number[]);
  });
  return mapping;
}

/** 映射值 → 行内文本（多列以空格拼接） */
function rowText(
  row: (string | null)[],
  v: MappingValue | undefined,
): string {
  const idxs = mappingIndices(v);
  if (!idxs.length) return '';
  return idxs
    .map((i) => String(row[i] ?? ''))
    .filter((s) => s.trim() !== '')
    .join(' ');
}


/**
 * F-02 按映射生成岗位数组（demo 逻辑原样迁移，列名口径 → 索引口径）
 * - 数值字段 parseFloat（失败 → null）
 * - 收入/收入打分/到手打分导入时恒为空（null）：由 F-07 AI 收入分析回填后填入（Q-D4），
 *   导入阶段不读源收入列、不自动推导打分；收入为空时总分按`收入项=0`参与，报录比无效 →「—」
 * - remarkCols 按勾选拼接「列名: 内容」换行并入备注
 * - 岗位代码或招聘单位为空的行跳过并计入 skipped
 */
export function buildJobs(
  raw: RawTable,
  mapping: Mapping,
  remarkCols: number[],
  roundsLength: number,
  prevMarksByKey?: Map<string, Job['marks']>,
): Result<{ jobs: Job[]; skipped: number }> {
  const jobs: Job[] = [];
  let skipped = 0;
  const remarkIdx = (remarkCols ?? []).filter((i) => i >= 0 && i < raw.columns.length);

  // 去重按**唯一键**（职位代码 + 用人司局），不是按职位代码单列（见 types Job.key 说明）
  const byKey = new Map<string, Job>();

  raw.rows.forEach((row) => {
    // 多列字段（如广东三列专业）在此合并为一段文本
    const cell = (v: MappingValue | undefined): string => rowText(row, v);
    const numCell = (v: MappingValue | undefined): number | null => {
      const s = cell(v).trim();
      if (s === '') return null;
      const n = parseFloat(s);
      return isNaN(n) ? null : n;
    };

    const code = cell(mapping.code).trim();
    const unit = cell(mapping.unit).trim();
    if (!code || !unit) {
      skipped++;
      return;
    }

    // 唯一键：国考正式表「职位代码」跨部门重复，单用 code 会丢 2/3 岗位
    const key = `${code}\u0000${unit}`;
    if (byKey.has(key)) {
      skipped++; // 完全重复行（同职位代码 + 同用人司局）只保留首次出现
      return;
    }

    const job: Job = {
      key,
      code,
      unit,
      title: cell(mapping.title),
      // 收入/收入打分/到手收入/到手打分：导入时恒为空（null），不读源收入列、不自动推导打分，
      // 由 F-07 AI 收入分析回填或手动编辑填入（Q-D4）
      avgIncome: null,
      netIncome: null,
      incomeScore: null,
      netScore: null,
      applicants: numCell(mapping.applicants),
      hires: numCell(mapping.hires),
      region: cell(mapping.region).trim(),
      degree: cell(mapping.degree).trim(),
      major: cell(mapping.major),
      intro: cell(mapping.intro),
      // 职位表专有列（未映射则为空串 → 资格审查按「无限制」处理）
      politicalStatus: cell(mapping.politicalStatus).trim(),
      grassrootsYears: cell(mapping.grassrootsYears).trim(),
      serviceProject: cell(mapping.serviceProject).trim(),
      institution: cell(mapping.institution).trim(),
      freshRequired: cell(mapping.freshRequired).trim(),
      physicalTest: cell(mapping.physicalTest).trim(),
      remark: remarkIdx
        .map((i) => {
          const v = String(row[i] ?? '').trim();
          return v ? `${raw.columns[i]}: ${v}` : '';
        })
        .filter(Boolean)
        .join('\n'),
      marks: Array.from({ length: roundsLength }, () => 'pending' as const),
    };

    // 重新映射同一数据时轮次标记按唯一键保留（F-02 规则 8）
    if (prevMarksByKey) {
      const prev = prevMarksByKey.get(key);
      if (prev) {
        // 标记长度对齐当前轮次数（新增轮次补 pending）
        job.marks = Array.from({ length: roundsLength }, (_, r) => prev[r] ?? 'pending');
      }
    }

    byKey.set(key, job);
  });

  byKey.forEach((j) => jobs.push(j));
  return ok({ jobs, skipped });
}

/** 必填字段（岗位代码/招聘单位）未映射 → E_MAP_REQUIRED（向导第 2 步进入下一步前校验） */
export function validateMapping(mapping: Mapping): Result<null> {
  const missing = FIELDS.filter((f) => f.required && !isMapped(mapping[f.key])).map((f) => f.name);
  if (missing.length) {
    return err('E_MAP_REQUIRED', `必填字段未映射：${missing.join('、')}`);
  }
  return ok(null);
}

/** demo 首行示例展示用：取某列（或多列合并后）首行值 */
export function sampleOf(raw: RawTable, v: MappingValue | undefined): string {
  if (!raw.rows.length) return '';
  return rowText(raw.rows[0], v);
}

/** 常见「备注类」列名（省考/国考把隐性门槛写在这些列里） */
const REMARK_HINT = ['其他要求', '备注', '说明', '备注说明', '其他条件', '资格条件', '职位要求', '附加要求'];

/**
 * 建议并入「备注」的源列：未被标准字段映射、且列名命中备注类词表。
 * 目的：把「其他要求」里的隐性门槛（党员、服务年限、体测、性别…）带进备注，
 * 供风险扫描与资格审查兜底（如广东把「中共党员」写在「其他要求」列）。
 */
export function suggestRemarkCols(columns: string[], mapping: Mapping): number[] {
  const used = new Set(Object.values(mapping).flatMap((v) => mappingIndices(v)));
  return columns
    .map((c, i) => ({ c: norm(c), i }))
    .filter(({ c, i }) => !used.has(i) && REMARK_HINT.some((k) => c.includes(norm(k))))
    .map(({ i }) => i);
}

export { num };
