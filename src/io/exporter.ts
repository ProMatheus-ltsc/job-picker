/**
 * 导出（05 §4.6 契约；demo doExportCsv/doCopyText 迁移 + S5 增补 .xlsx）
 * 导出列 = 已映射标准字段 + 备注（有值时）+ 报录比 + 总分 + 当前轮次标记
 */
import { FIELDS, type Job, type Mapping, type Result, type MarkStatus } from '../types';
import { err, ok } from '../types';
import { calcRatio, calcTotal } from '../core/scoring';

const MARK_LABEL: Record<MarkStatus, string> = { pending: '待定', promote: '晋级', eliminate: '淘汰' };

interface ExportCol {
  key: string;
  name: string;
}

function exportColumns(mapping: Mapping, remarkCols: number[], roundName: string): ExportCol[] {
  const cols: ExportCol[] = [];
  FIELDS.forEach((f) => {
    if (mapping[f.key] != null) cols.push({ key: f.key, name: f.name });
  });
  if (remarkCols.length) cols.push({ key: 'remark', name: '备注' });
  cols.push({ key: '_ratio', name: '报录比' }, { key: '_total', name: '总分' }, { key: '_mark', name: `${roundName}标记` });
  return cols;
}

function exportRows(viewJobs: Job[], mapping: Mapping, remarkCols: number[], currentRound: number): Record<string, string>[] {
  return viewJobs.map((j) => {
    const o: Record<string, string> = {};
    FIELDS.forEach((f) => {
      if (mapping[f.key] != null) o[f.key] = String((j as unknown as Record<string, unknown>)[f.key] ?? '');
    });
    if (remarkCols.length) o.remark = j.remark || '';
    const ratio = calcRatio(j.applicants, j.hires);
    const total = calcTotal(j);
    o._ratio = ratio != null ? ratio.toFixed(1) : '';
    o._total = total != null ? total.toFixed(2) : '';
    o._mark = MARK_LABEL[j.marks[currentRound] ?? 'pending'];
    return o;
  });
}

function timestamp(): string {
  const d = new Date();
  const pad = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

function download(blob: Blob, filename: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** F-06 CSV 下载（前置 \uFEFF BOM，Excel 打开中文无乱码；RFC 4180 转义） */
export function exportCsv(viewJobs: Job[], mapping: Mapping, remarkCols: number[], rounds: string[], currentRound: number): void {
  const cols = exportColumns(mapping, remarkCols, rounds[currentRound]);
  const rows = exportRows(viewJobs, mapping, remarkCols, currentRound);
  const escC = (v: unknown) => {
    const s = String(v ?? '');
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const csv = [cols.map((c) => escC(c.name)).join(',')]
    .concat(rows.map((o) => cols.map((c) => escC(o[c.key])).join(',')))
    .join('\r\n');
  download(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }), `选岗名单_${rounds[currentRound]}_${timestamp()}.csv`);
}

/** TSV 文本复制（单元格内换行替换为空格）；剪贴板失败 → execCommand 降级 → 均失败 E_CLIPBOARD */
export async function copyTsv(viewJobs: Job[], mapping: Mapping, remarkCols: number[], rounds: string[], currentRound: number): Promise<Result<null>> {
  const cols = exportColumns(mapping, remarkCols, rounds[currentRound]);
  const rows = exportRows(viewJobs, mapping, remarkCols, currentRound);
  const text = [cols.map((c) => c.name).join('\t')]
    .concat(rows.map((o) => cols.map((c) => String(o[c.key] ?? '').replace(/\n/g, ' ')).join('\t')))
    .join('\n');
  return copyToClipboard(text).then((success) =>
    success ? ok(null) : err('E_CLIPBOARD', '复制失败，请手动复制'),
  );
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return legacyCopy(text);
    }
  }
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let okFlag = false;
  try {
    okFlag = document.execCommand('copy');
  } catch {
    /* ignore */
  }
  ta.remove();
  return okFlag;
}

/** P1 增补（S5 SheetJS 后）: .xlsx 导出（与 CSV 同范围同列；动态 import 按需加载） */
export async function exportXlsx(viewJobs: Job[], mapping: Mapping, remarkCols: number[], rounds: string[], currentRound: number): Promise<void> {
  const XLSX = await import('xlsx');
  const cols = exportColumns(mapping, remarkCols, rounds[currentRound]);
  const rows = exportRows(viewJobs, mapping, remarkCols, currentRound);
  const aoa = [cols.map((c) => c.name), ...rows.map((o) => cols.map((c) => o[c.key] ?? ''))];
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(aoa);
  XLSX.utils.book_append_sheet(wb, ws, rounds[currentRound].slice(0, 31) || '名单');
  XLSX.writeFile(wb, `选岗名单_${rounds[currentRound]}_${timestamp()}.xlsx`);
}
