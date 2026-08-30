/**
 * V1 欢迎页（空状态导入引导；04 §6.1 全屏路由不进壳）
 * 核心引导卡复用 @shared/core EmptyState（带 icon 形态，05 §7.4）
 */
import { FileSpreadsheet, FileText, PlayCircle, Sparkles } from 'lucide-react';
import { EmptyState } from '@shared/core';

interface Props {
  onLoadDemo: () => void;
  onPickFile: () => void;
  onDemoCsv: () => void;
}

export function Welcome({ onLoadDemo, onPickFile, onDemoCsv }: Props) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="jp-card">
        <EmptyState
          icon={Sparkles}
          title="开始使用"
          description="流程：导入岗位表 → 手动映射列（可勾选源列并入备注）→ 自动打分与总分排序 →（可选）设置考生画像强筛选 → 多轮淘汰筛选 → 导出名单"
          action={
            <div className="jp-btns mt-4">
              <button className="jp-btn primary" onClick={onLoadDemo}>
                <PlayCircle size={14} className="mr-1 inline align-[-2px]" />
                加载演示数据（13 个岗位 · 2026 省考结构）
              </button>
              <button className="jp-btn" onClick={onPickFile}>
                <FileSpreadsheet size={14} className="mr-1 inline align-[-2px]" />
                导入文件（CSV / .xlsx 真实解析）
              </button>
              <button className="jp-btn" onClick={onDemoCsv}>
                <FileText size={14} className="mr-1 inline align-[-2px]" />
                用演示 CSV 体验完整导入向导
              </button>
            </div>
          }
        />
        <div className="jp-notice welcome-inner">
          支持 CSV（UTF-8）与 .xlsx（多 sheet 可选）。所有数据仅保存在本浏览器（IndexedDB），刷新不丢失，可随时用「清空数据」重置。
        </div>
        <div className="jp-card" style={{ margin: 0, background: '#f8fafd' }}>
          <b style={{ fontSize: 13 }}>打分逻辑说明</b>
          <ul>
            <li>报录比 = 报名人数 ÷ 录用人数</li>
            <li>总分 =（平均收入 + 到手收入 + 收入打分 + 到手收入打分）÷ 报录比</li>
            <li>收入打分默认 = 年收入万数（40 万 = 40 分），每条岗位的打分可手动修改，总分实时重算</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
