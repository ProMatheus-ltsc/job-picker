/**
 * V4 导出名单对话框（F-06 + S5 增补 .xlsx）
 * 范围 = 当前视图（当前轮次 ∩ 画像 ∩ 筛选 ∩ 排序）；CSV（BOM）/ TSV 复制 / XLSX
 */
import { useState } from 'react';
import { useToast } from '@shared/core/hooks/useToast';
import { DialogShell } from './DialogShell';
import { copyTsv, exportCsv, exportXlsx } from '../io/exporter';
import type { Job, Mapping } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  viewJobs: Job[];
  mapping: Mapping;
  remarkCols: number[];
  rounds: string[];
  round: number;
}

export function ExportDialog({ open, onClose, viewJobs, mapping, remarkCols, rounds, round }: Props) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);

  const scope = `当前视图：第 ${round + 1} 轮「${rounds[round]}」（经画像过滤 + 当前筛选 + 当前排序）`;

  const handleCsv = () => {
    if (!viewJobs.length) return;
    exportCsv(viewJobs, mapping, remarkCols, rounds, round);
    showToast(`已下载 CSV（${viewJobs.length} 条）`);
  };

  const handleTsv = async () => {
    if (!viewJobs.length) return;
    const r = await copyTsv(viewJobs, mapping, remarkCols, rounds, round);
    showToast(r.ok ? `已复制 TSV 文本（${viewJobs.length} 条），可直接粘贴 Excel` : r.error.message, r.ok ? 'success' : 'error');
  };

  const handleXlsx = async () => {
    if (!viewJobs.length) return;
    setBusy(true);
    try {
      await exportXlsx(viewJobs, mapping, remarkCols, rounds, round);
      showToast(`已下载 .xlsx（${viewJobs.length} 条）`);
    } catch {
      showToast('.xlsx 导出失败（解析库加载异常）', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogShell
      open={open}
      title="导出名单"
      subtitle={scope}
      onClose={onClose}
      width={560}
      footer={
        <>
          <button className="jp-btn" onClick={onClose}>
            关闭
          </button>
          <button className="jp-btn" disabled={!viewJobs.length} onClick={() => void handleTsv()}>
            复制文本（TSV）
          </button>
          <button className="jp-btn" disabled={!viewJobs.length} onClick={handleCsv}>
            下载 CSV
          </button>
          <button className="jp-btn primary" disabled={!viewJobs.length || busy} onClick={() => void handleXlsx()}>
            {busy ? '导出中…' : '下载 .xlsx'}
          </button>
        </>
      }
    >
      <div className="prompt-hint">
        导出范围 = <b>{viewJobs.length}</b> 条（当前视图）· 导出列 = 已映射标准字段
        {remarkCols.length ? ' + 备注' : ''} + 报录比 + 总分 + 当前轮次标记。
        CSV 前置 BOM（Excel 打开中文无乱码）；TSV 可直接粘贴 Excel。
      </div>
      {!viewJobs.length && <div className="result-box err">当前视图没有可导出的岗位。</div>}
    </DialogShell>
  );
}
