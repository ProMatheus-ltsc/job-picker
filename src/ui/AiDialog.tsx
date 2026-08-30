/**
 * V6 AI 收入分析对话框（F-07）：Tab① 提示词模板（一键复制）Tab② JSON 粘贴回填
 * 回填 = validateAiJson 校验 → applyAiResults 单位双向包含匹配更新（Q-D4）
 */
import { useEffect, useState } from 'react';
import { useToast } from '@shared/core/hooks/useToast';
import { DialogShell } from './DialogShell';
import { buildAiPrompt, validateAiJson } from '../core/aiFill';
import type { AiEntry, ApplyAiSummary, Job } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 当前岗位列表，用于动态注入提示词的岗位清单 */
  jobs: Job[];
  /** 校验通过后由父级执行 applyAiResults + 持久化，返回回填摘要 */
  onApply: (entries: AiEntry[]) => ApplyAiSummary;
}

export function AiDialog({ open, onClose, jobs, onApply }: Props) {
  const { showToast } = useToast();
  const [tab, setTab] = useState<1 | 2>(1);
  const [text, setText] = useState('');
  const [summary, setSummary] = useState<ApplyAiSummary | null>(null);
  /** 校验产生的无效条目（本地保存直接回显，避免从父级返回值重复携带，CR-001） */
  const [invalidEntries, setInvalidEntries] = useState<unknown[]>([]);
  /** 展示/复制用：动态注入当前岗位清单的提示词 */
  const prompt = buildAiPrompt(jobs);

  useEffect(() => {
    if (open) {
      setSummary(null);
      setText('');
      setInvalidEntries([]);
    }
  }, [open]);

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      showToast('提示词已复制，粘贴给 AI 即可');
    } catch {
      showToast('复制失败，请手动全选复制', 'error');
    }
  };

  const handleApply = () => {
    const v = validateAiJson(text);
    if (!v.ok) {
      showToast(v.error.message, 'error');
      return;
    }
    if (!v.data.results.length) {
      showToast('JSON 中没有有效条目（单位名称与收入均缺失）', 'error');
      return;
    }
    setInvalidEntries(v.data.invalidEntries);
    const s = onApply(v.data.results);
    setSummary(s);
    showToast(`AI 回填完成：${s.updatedCount} 个岗位已更新`);
  };

  return (
    <DialogShell
      open={open}
      title="AI 收入分析"
      subtitle="用 AI 分析部门预算文本估算收入 → 回填岗位表：平均收入/到手收入更新，打分按「万数四舍五入」重置（Q-D1），同单位多岗位一并更新"
      onClose={onClose}
      width={720}
      footer={
        tab === 2 ? (
          <>
            <button className="jp-btn" onClick={onClose}>
              关闭
            </button>
            <button className="jp-btn primary" onClick={handleApply}>
              校验并回填
            </button>
          </>
        ) : (
          <button className="jp-btn" onClick={onClose}>
            关闭
          </button>
        )
      }
    >
      <div className="dlg-tabs" role="tablist" aria-label="AI 收入分析">
        <button role="tab" aria-selected={tab === 1} className={tab === 1 ? 'on' : ''} onClick={() => setTab(1)}>
          ① 提示词模板
        </button>
        <button role="tab" aria-selected={tab === 2} className={tab === 2 ? 'on' : ''} onClick={() => setTab(2)}>
          ② JSON 回填
        </button>
      </div>

      {tab === 1 && (
        <div>
          <div className="prompt-hint">
            提示词已按当前岗位表自动注入「岗位清单」（共 <b>{jobs.length}</b> 个岗位：单位｜职位）。复制下方提示词
            → 粘贴部门预算 PDF 文本发给 AI → 将 AI 返回的 JSON 切到「② JSON 回填」粘贴即可。
          </div>
          <textarea
            readOnly
            value={prompt}
            rows={14}
            aria-label="AI 提示词模板"
            onFocus={(e) => e.currentTarget.select()}
          />
          <div className="dlg-actions" style={{ justifyContent: 'flex-start' }}>
            <button className="jp-btn primary" onClick={() => void copyPrompt()}>
              一键复制提示词
            </button>
          </div>
        </div>
      )}

      {tab === 2 && (
        <div>
          <div className="prompt-hint">
            粘贴 AI 返回的 JSON（结构：
            <code>{'{"results":[{"单位名称":…,"平均收入":…,"到手收入":…,"说明":…}]}'}</code>
            ）。单位匹配为双向包含（Q-D4）；未命中单位会在下方列出，条目级无效不阻断整体回填。
          </div>
          <textarea
            value={text}
            rows={10}
            placeholder='{"results":[{"单位名称":"深圳市市场监督管理局","平均收入":49.88,"到手收入":45.08,"说明":"…"}]}'
            aria-label="AI 返回的 JSON"
            onChange={(e) => setText(e.target.value)}
          />
          {summary && (
            <div className="result-box">
              <div className="ok">
                回填完成：命中 {summary.unitCount} 个单位，更新 {summary.updatedCount} 个岗位
                {invalidEntries.length ? `，忽略无效条目 ${invalidEntries.length} 条` : ''}
              </div>
              {summary.matchedUnits.length > 0 && (
                <ul>
                  <li>命中单位：{summary.matchedUnits.join('、')}</li>
                </ul>
              )}
              {summary.unmatchedUnits.length > 0 && (
                <div className="err">
                  未命中单位（岗位表中无匹配）：
                  <ul>
                    {summary.unmatchedUnits.map((u) => (
                      <li key={u}>{u}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </DialogShell>
  );
}
