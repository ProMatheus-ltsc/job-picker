/**
 * CSV 解析（05 §4.1 契约；demo parseCSVText 状态机原样迁移 + 契约错误码封装）
 */
import type { RawTable, Result } from '../types';
import { err, ok } from '../types';

/**
 * 分隔符自动检测：返回该行中 , \t ; 出现频率最高者（全零返回 ,）
 */
export function detectDelimiter(line: string): string {
  const counts: Record<string, number> = { ',': 0, '\t': 0, ';': 0 };
  for (const c of line) {
    if (c in counts) counts[c]++;
  }
  let best = ',';
  let max = -1;
  for (const [d, n] of Object.entries(counts)) {
    if (n > max) {
      max = n;
      best = d;
    }
  }
  return best;
}

/**
 * 引号转义状态机解析（demo 原样迁移）：BOM 去除 → 分隔符检测 → 状态机 → 尾部空行剔除
 * 返回 string[][]（含表头行）；不返回错误（结构问题由上层按行列数判断）
 */
export function parseCsvRows(text: string): string[][] {
  text = String(text).replace(/^\uFEFF/, '');
  const nl = text.indexOf('\n');
  const firstLine = nl >= 0 ? text.slice(0, nl) : text;
  const delim = detectDelimiter(firstLine);
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQ = false;
      } else field += c;
    } else {
      if (c === '"') inQ = true;
      else if (c === delim) {
        row.push(field);
        field = '';
      } else if (c === '\n') {
        row.push(field);
        field = '';
        rows.push(row);
        row = [];
      } else if (c === '\r') {
        /* 跳过 CR */
      } else field += c;
    }
  }
  if (field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  while (rows.length && rows[rows.length - 1].every((v) => v.trim() === '')) rows.pop();
  return rows;
}

/**
 * F-01 CSV 解析入口：完整文本 → RawTable（sheetName = null）
 * 错误码：E_CSV_ENCODING（U+FFFD 占比 > 1%）
 */
export function parseCsv(text: string): Result<RawTable> {
  const bad = (text.match(/\uFFFD/g) || []).length;
  if (bad > text.length * 0.01) {
    return err(
      'E_CSV_ENCODING',
      '文件疑似非 UTF-8 编码（检测到大量乱码字符），请用记事本/Excel 将 CSV 另存为 UTF-8 后重试',
    );
  }
  const rows = parseCsvRows(text);
  if (rows.length < 2) {
    return err('E_FILE_CORRUPT', '解析结果不足 2 行，请确认 CSV 含表头与数据');
  }
  return ok({ sheetName: null, columns: rows[0], rows: rows.slice(1) });
}

/** RawTable → CSV 文本（demo rawToCSV 迁移：演示 CSV 体验完整向导用） */
export function rawToCsv(raw: RawTable): string {
  const escC = (v: unknown) => {
    const s = String(v ?? '');
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  return [raw.columns.map(escC).join(',')]
    .concat(raw.rows.map((r) => r.map((c) => escC(c ?? '')).join(',')))
    .join('\n');
}
