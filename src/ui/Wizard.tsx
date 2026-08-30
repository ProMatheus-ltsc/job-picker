/**
 * V2 导入向导（三步：预览[含多 sheet 选择/表头切换] → 列映射[含备注列勾选] → 确认导入）
 * demo 交互基线 React 重写 + S5 增补 .xlsx 多 sheet（04 §6.1）
 */
import { useEffect, useMemo, useState } from 'react';
import { useToast } from '@shared/core/hooks/useToast';
import type { Mapping, RawTable } from '../types';
import { FIELDS } from '../types';
import { autoSuggestMapping, buildJobs, sampleOf, validateMapping } from '../core/mapping';
import type { XlsxSheet } from '../io/parseXlsx';

export interface ImportPayload {
  fileName: string;
  /** xlsx 路径：全部 sheet（第 1 步选择） */
  xlsxSheets?: XlsxSheet[];
  /** CSV 路径：含表头行的全部行 */
  csvRows?: string[][];
  /** 重新映射模式（V3 顶栏「列映射」入口；保留标记） */
  remap?: boolean;
}

interface Props {
  payload: ImportPayload;
  /** 当前轮次（marks 长度基准） */
  currentRounds: string[];
  onComplete: (raw: RawTable, mapping: Mapping, remarkCols: number[]) => void;
  onCancel: () => void;
}

export function Wizard({ payload, currentRounds, onComplete, onCancel }: Props) {
  const { showToast } = useToast();
  const [step, setStep] = useState(1);
  const [headerRow, setHeaderRow] = useState(true);
  const [sheetIdx, setSheetIdx] = useState(0);
  const [mapping, setMapping] = useState<Mapping>({});
  const [remarkCols, setRemarkCols] = useState<number[]>([]);

  /** 全部数据行（不含表头）：xlsx 为选中 sheet 的 rows；csv 为 csvRows 去首行 */
  const allRows: (string | null)[][] = useMemo(() => {
    if (payload.xlsxSheets) return payload.xlsxSheets[sheetIdx]?.rows ?? [];
    return (payload.csvRows ?? []).slice(1).map((r) => r.map((c) => c ?? ''));
  }, [payload, sheetIdx]);

  /** 首行（表头判定基准） */
  const firstRow: string[] = useMemo(() => {
    if (payload.xlsxSheets) return payload.xlsxSheets[sheetIdx]?.columns ?? [];
    return (payload.csvRows ?? [])[0] ?? [];
  }, [payload, sheetIdx]);

  /** 表头切换/sheet 切换 → 重建 RawTable（列名去重，demo rebuildWizardRaw 迁移） */
  const raw: RawTable = useMemo(() => {
    const rows = allRows;
    const columns = headerRow
      ? firstRow.map((v, i) => String(v ?? '').trim() || `列${i + 1}`)
      : firstRow.map((_, i) => `列${i + 1}`);
    const seen: Record<string, number> = {};
    const deduped = columns.map((c) => {
      seen[c] = (seen[c] ?? 0) + 1;
      return seen[c] > 1 ? `${c}(${seen[c]})` : c;
    });
    return {
      sheetName: payload.xlsxSheets ? payload.xlsxSheets[sheetIdx]?.name ?? null : null,
      columns: deduped,
      rows,
    };
  }, [allRows, firstRow, headerRow, payload.xlsxSheets, sheetIdx]);

  /** 表头/sheet 切换（columns 变化）→ 重置映射为自动预填（demo rebuildWizardRaw+autoGuessMapping 时机） */
  useEffect(() => {
    setMapping(autoSuggestMapping(raw.columns));
    setRemarkCols([]);
  }, [raw.columns]);

  /** 生效映射（自动预填已并入 mapping 状态，此处即最终口径） */
  const effectiveMapping = mapping;

  const usedCols = new Set(
    Object.entries(mapping)
      .filter(([, v]) => v != null)
      .map(([, v]) => v as number),
  );
  const availRemark = raw.columns.map((_, i) => i).filter((i) => !usedCols.has(i));

  const goNext = () => {
    if (step === 2) {
      const v = validateMapping(mapping);
      if (!v.ok) {
        showToast(v.error.message, 'error');
        return;
      }
    }
    setStep(Math.min(step + 1, 3));
  };

  const stepNames = ['① 数据预览', '② 列映射', '③ 确认导入'];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <section className="jp-card">
        <h2 className="m-0 mb-2.5 text-[17px] font-bold">导入向导{payload.remap ? '（重新映射）' : ''}</h2>
        <div className="wiz-steps">
          {stepNames.map((s, i) => (
            <span key={s} className={step === i + 1 ? 'on' : step > i + 1 ? 'done' : ''}>
              {s}
            </span>
          ))}
        </div>

        {step === 1 && (
          <div>
            <p className="jp-step-flow">
              文件：<b>{payload.fileName}</b> · 解析结果：<b>{allRows.length}</b> 行 ×{' '}
              <b>{raw.columns.length}</b> 列（前 5 行预览如下）
            </p>
            {payload.xlsxSheets && payload.xlsxSheets.length > 1 && (
              <div className="dlg-tabs">
                {payload.xlsxSheets.map((s, i) => (
                  <button key={s.name} className={i === sheetIdx ? 'on' : ''} onClick={() => setSheetIdx(i)}>
                    {s.name}（{s.rows.length} 行）
                  </button>
                ))}
              </div>
            )}
            <label className="mb-2.5 inline-flex items-center gap-1.5 text-[13px]">
              <input
                type="checkbox"
                checked={headerRow}
                onChange={(e) => setHeaderRow(e.target.checked)}
              />
              首行为列名（表头）
            </label>
            <div className="preview-scroll">
              <table style={{ minWidth: 600, borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr>
                    {raw.columns.map((c) => (
                      <th key={c} style={{ border: '1px solid var(--jp-border)', padding: '4px 8px', background: '#f1f5fb' }}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {allRows.slice(0, 5).map((r, ri) => (
                    <tr key={ri}>
                      {raw.columns.map((_, ci) => (
                        <td key={ci} style={{ border: '1px solid #eef1f6', padding: '4px 8px' }}>
                          {r[ci] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <p className="jp-step-flow">
              将源表列映射到标准字段；<b>未映射的标准字段不会出现在岗位列表与导出中</b>
              （打分列未映射时按「年收入万数」自动打分）。
            </p>
            <div>
              {FIELDS.map((f) => {
                const col = effectiveMapping[f.key] ?? null;
                const sample = col != null ? sampleOf(raw, col) : '';
                return (
                  <div key={f.key} className="map-row">
                    <span className="fname">
                      {f.name}
                      {f.required && <span className="req">*必填</span>}
                    </span>
                    <select
                      value={col ?? ''}
                      onChange={(e) => {
                        const v = e.target.value === '' ? null : +e.target.value;
                        setMapping((m) => {
                          const next = { ...m, [f.key]: v };
                          return next;
                        });
                        if (v != null) {
                          // 已映射到标准字段的列从备注列移除（CHG-01）
                          setRemarkCols((rc) => rc.filter((c) => c !== v));
                        }
                      }}
                    >
                      <option value="">（不映射）</option>
                      {raw.columns.map((c, i) => (
                        <option key={i} value={i}>
                          {c}
                        </option>
                      ))}
                    </select>
                    <span className="sample">首行示例：{sample || '—'}</span>
                  </div>
                );
              })}
            </div>
            <div className="remark-block">
              <div className="rb-title">并入「备注」字段的源列（可选 · 多选）</div>
              <div className="rb-hint">
                勾选需要保留的重要源列（如「工作经历」「其他要求」），导入后按「<b>列名: 内容</b>」逐行换行拼接为岗位备注，在列表行展开详情与导出中展示。已映射到标准字段的列不在此处出现。
              </div>
              {availRemark.length ? (
                <div className="remark-cols">
                  {availRemark.map((i) => (
                    <label key={i}>
                      <input
                        type="checkbox"
                        checked={remarkCols.includes(i)}
                        onChange={(e) =>
                          setRemarkCols((rc) =>
                            e.target.checked ? [...rc, i] : rc.filter((c) => c !== i),
                          )
                        }
                      />
                      {raw.columns[i]}
                    </label>
                  ))}
                </div>
              ) : (
                <div className="rb-hint" style={{ margin: 0 }}>
                  所有源列均已映射到标准字段，暂无可并入备注的列。
                </div>
              )}
            </div>
            {(() => {
              const v = validateMapping(effectiveMapping);
              return <div className="map-err">{v.ok ? '' : v.error.message}</div>;
            })()}
          </div>
        )}

        {step === 3 && (
          <Step3Confirm
            raw={raw}
            mapping={effectiveMapping}
            remarkCols={remarkCols}
            roundsLength={currentRounds.length}
            remap={!!payload.remap}
          />
        )}

        <div className="dlg-actions" style={{ justifyContent: 'flex-start' }}>
          {step > 1 && (
            <button className="jp-btn" onClick={() => setStep(Math.max(step - 1, 1))}>
              上一步
            </button>
          )}
          {step < 3 && (
            <button className="jp-btn primary" onClick={goNext}>
              下一步
            </button>
          )}
          {step === 3 && (
            <button
              className="jp-btn primary"
              onClick={() => onComplete(raw, effectiveMapping, remarkCols)}
            >
              确认导入，进入岗位列表
            </button>
          )}
          <button className="jp-btn" onClick={onCancel}>
            取消
          </button>
        </div>
      </section>
    </div>
  );
}

/** 第 3 步确认预览（demo wizFinish 前置预览迁移） */
function Step3Confirm({
  raw,
  mapping,
  remarkCols,
  roundsLength,
  remap,
}: {
  raw: RawTable;
  mapping: Mapping;
  remarkCols: number[];
  roundsLength: number;
  remap: boolean;
}) {
  const built = buildJobs(raw, mapping, remarkCols, roundsLength);
  const mapped = FIELDS.filter((f) => mapping[f.key] != null);
  const autoScore: string[] = [
    '收入/到手收入/收入打分/到手收入打分导入时默认为空：需通过「AI 收入分析」回填或手动编辑填入（不读源收入列、不自动推导打分）',
  ];
  const jobs = built.ok ? built.data.jobs : [];

  return (
    <div>
      <p className="jp-step-flow">
        映射后预览（前 3 行，仅展示已映射字段{remarkCols.length ? '与备注' : ''}）· 共{' '}
        <b>{jobs.length}</b> 个有效岗位
        {built.ok && built.data.skipped ? `（跳过 ${built.data.skipped} 行岗位代码或单位为空/重复）` : ''}
      </p>
      <div className="preview-scroll">
        <table style={{ minWidth: 700, borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {mapped.map((f) => (
                <th key={f.key} style={{ border: '1px solid var(--jp-border)', padding: '4px 8px', background: '#f1f5fb' }}>
                  {f.name}
                </th>
              ))}
              {remarkCols.length > 0 && (
                <th style={{ border: '1px solid var(--jp-border)', padding: '4px 8px', background: '#f1f5fb' }}>备注</th>
              )}
            </tr>
          </thead>
          <tbody>
            {jobs.slice(0, 3).map((j) => (
              <tr key={j.code}>
                {mapped.map((f) => (
                  <td key={f.key} style={{ border: '1px solid #eef1f6', padding: '4px 8px' }}>
                    {String((j as unknown as Record<string, unknown>)[f.key] ?? '')}
                  </td>
                ))}
                {remarkCols.length > 0 && (
                  <td className="remark-text" style={{ border: '1px solid #eef1f6', padding: '4px 8px', maxWidth: 260 }}>
                    {j.remark || '—'}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {autoScore.length > 0 && (
        <div className="prompt-hint">导入说明：{autoScore[0]}</div>
      )}
      {remap && (
        <div className="jp-notice">
          重新映射将按原始数据重建岗位数值（打分/报名人数等恢复为源表值），轮次标记将按岗位代码保留。
        </div>
      )}
    </div>
  );
}
