/**
 * XLSX / XLS 解析（05 §4.2 契约；SheetJS 引入，S5 增补）
 * 动态 import 加载（xlsx chunk 不进首屏，04 §8 R4）；解析等待态由调用方以 LoadingSpinner 呈现
 *
 * 兼容两类真实职位表：
 * - .xlsx（国考、浙江省考）：标准 OOXML
 * - .xls（广东省考）：BIFF 旧格式，SheetJS 同样可读
 *
 * 表头行自动探测：真实职位表常在表头之上有标题/说明行（如广东「附件1」「广东省县级以上机关2025年…」），
 * 且**不同 sheet 的表头行号可能不同**，因此不再固定取首行。
 */
import { FIELDS, type Result } from '../types';
import { err, ok } from '../types';

export interface XlsxSheet {
  name: string;
  /** 原始二维数组（含说明行/表头行），供向导切换表头行时重新切分 */
  aoa: (string | null)[][];
  /** 自动探测到的表头行下标 */
  headerRowIndex: number;
  /** = aoa[headerRowIndex] */
  columns: string[];
  /** = aoa.slice(headerRowIndex + 1) */
  rows: (string | null)[][];
}

export interface XlsxFile {
  sheets: XlsxSheet[];
}

/** 列名归一化：去空白（含换行/全角空格） */
const normHeader = (s: unknown): string => String(s ?? '').replace(/[\s\u3000]/g, '');

/** 表头关键词词表（全部标准字段的本名 + 别名，归一化） */
const HEADER_KEYWORDS: string[] = (() => {
  const set = new Set<string>();
  FIELDS.forEach((f) => {
    const n = normHeader(f.name);
    if (n) set.add(n);
    (f.aliases ?? []).forEach((a) => {
      const na = normHeader(a);
      if (na) set.add(na);
    });
  });
  return [...set];
})();

/**
 * 表头行探测：在前 `limit` 行中选「命中已知列名最多」的一行。
 * 命中数相同时取非空单元格更多者；最高命中 < 2 视为无有效表头，回退第 0 行。
 * 从上往下扫描且要求严格更优，天然偏向靠前的行。
 */
export function detectHeaderRow(aoa: (string | null)[][], limit = 15): number {
  let bestIdx = 0;
  let bestScore = -1;
  let bestHit = 0;
  const n = Math.min(limit, aoa.length);
  for (let i = 0; i < n; i += 1) {
    const cells = (aoa[i] ?? []).map((c) => normHeader(c)).filter(Boolean);
    if (!cells.length) continue;
    let hit = 0;
    cells.forEach((c) => {
      if (HEADER_KEYWORDS.some((k) => k === c || (c.length >= 2 && k.includes(c)))) hit += 1;
    });
    if (!hit) continue;
    const score = hit * 100 + cells.length;
    if (score > bestScore) {
      bestScore = score;
      bestHit = hit;
      bestIdx = i;
    }
  }
  return bestHit >= 2 ? bestIdx : 0;
}

/** 由 aoa + 表头行下标切分 columns/rows；headerRowIndex < 0 表示无表头（自动生成列名） */
export function sliceSheetByHeader(
  aoa: (string | null)[][],
  headerRowIndex: number,
): { columns: string[]; rows: (string | null)[][] } {
  const width = aoa.reduce((m, r) => Math.max(m, r?.length ?? 0), 0);
  if (headerRowIndex < 0) {
    return {
      columns: Array.from({ length: width }, (_, i) => `列${i + 1}`),
      rows: aoa,
    };
  }
  const head = aoa[headerRowIndex] ?? [];
  // 表头单元格内常含换行（如广东「研究生专业\n名称及代码」）→ 去掉换行，保证展示与备注文本干净
  const columns = Array.from({ length: width }, (_, i) =>
    String(head[i] ?? '').replace(/[\r\n]+/g, '').trim(),
  );
  const rows = aoa.slice(headerRowIndex + 1).map((r) => Array.from({ length: width }, (_, i) => r?.[i] ?? null));
  return { columns, rows };
}

/**
 * F-01 表格解析与多 sheet（PRD F-01 规则 3）
 * - XLSX.read(buffer, {type:'array'})（同时支持 .xlsx 与 .xls）
 * - 逐 sheet sheet_to_json(ws, {header:1, raw:false, defval:null})（raw:false 统一取显示文本，日期/数值不变形）
 * - 表头行由 detectHeaderRow 自动探测（向导第 1 步可手动改）
 * 错误码：E_FILE_CORRUPT（XLSX.read 抛错 / zip 结构非法）
 */
export async function parseXlsx(buffer: ArrayBuffer): Promise<Result<XlsxFile>> {
  try {
    const XLSX = await import('xlsx');
    const wb = XLSX.read(buffer, { type: 'array' });
    const sheets: XlsxSheet[] = wb.SheetNames.map((name) => {
      const ws = wb.Sheets[name];
      const raw = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: false, defval: null });
      const aoa = raw.map((r) => (Array.isArray(r) ? r.map((c) => (c == null ? null : String(c))) : []));
      const headerRowIndex = detectHeaderRow(aoa);
      const { columns, rows } = sliceSheetByHeader(aoa, headerRowIndex);
      return { name, aoa, headerRowIndex, columns, rows };
    });
    if (!sheets.length) {
      return err('E_FILE_CORRUPT', '工作簿内没有任何工作表');
    }
    return ok({ sheets });
  } catch {
    return err('E_FILE_CORRUPT', '文件解析失败：不是有效的 .xlsx/.xls 工作簿（或文件已损坏）');
  }
}
