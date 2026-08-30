/**
 * XLSX 解析（05 §4.2 契约；SheetJS 引入，S5 增补）
 * 动态 import 加载（xlsx chunk 不进首屏，04 §8 R4）；解析等待态由调用方以 LoadingSpinner 呈现
 */
import type { Result } from '../types';
import { err, ok } from '../types';

export interface XlsxSheet {
  name: string;
  columns: string[];
  rows: (string | null)[][];
}

export interface XlsxFile {
  sheets: XlsxSheet[];
}

/**
 * F-01 .xlsx 真实解析与多 sheet（PRD F-01 规则 3）
 * - XLSX.read(buffer, {type:'array'})
 * - 逐 sheet sheet_to_json(ws, {header:1, raw:false, defval:null})（raw:false 统一取显示文本，日期/数值不变形）
 * - 首行默认视为表头（向导第 1 步可切换，切换后由调用方重建 columns/rows）
 * 错误码：E_FILE_CORRUPT（XLSX.read 抛错 / zip 结构非法）
 */
export async function parseXlsx(buffer: ArrayBuffer): Promise<Result<XlsxFile>> {
  try {
    const XLSX = await import('xlsx');
    const wb = XLSX.read(buffer, { type: 'array' });
    const sheets: XlsxSheet[] = wb.SheetNames.map((name) => {
      const ws = wb.Sheets[name];
      const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: false, defval: null });
      const rows = aoa.slice(1).map((r) => r.map((c) => (c == null ? null : String(c))));
      return { name, columns: (aoa[0] ?? []).map((c) => String(c ?? '')), rows };
    });
    if (!sheets.length) {
      return err('E_FILE_CORRUPT', '工作簿内没有任何工作表');
    }
    return ok({ sheets });
  } catch {
    return err('E_FILE_CORRUPT', '文件解析失败：不是有效的 .xlsx 工作簿（或文件已损坏）');
  }
}
