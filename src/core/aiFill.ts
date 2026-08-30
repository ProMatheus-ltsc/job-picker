/**
 * AI 收入分析辅助（05 §4.7 / §5 契约；demo AI_PROMPT/doAIApply 迁移为契约函数）
 */
import type { AiEntry, ApplyAiSummary, Job, Result } from '../types';
import { err, ok } from '../types';
import { roundIncomeScore } from './scoring';
import { matchUnit } from './aiMatch';

export { matchUnit };

/** 提示词模板（05 §5.1 完整固化，与 demo/PRD §3.7 一致） */
export const AI_PROMPT_TEMPLATE = `# 任务
你是公共部门收入分析助手。请根据我提供的政府部门预算文件文本，估算该部门公务员的人均年收入，并严格按下方 JSON 结构返回。

# 输入格式
我会粘贴某部门年度预算的文本内容（通常包含：部门基本情况、人员编制数/实有人数、工资福利支出、对个人和家庭的补助、公用经费等）。

# 输出要求（严格遵守）
只输出一个 JSON 对象，不要输出任何解释文字、不要使用 Markdown 代码块标记。结构如下：
{
  "results": [
    {
      "单位名称": "与预算文件一致的部门全称",
      "平均收入": 49.88,
      "到手收入": 45.08,
      "说明": "一句话估算依据"
    }
  ]
}
字段约定：
- "单位名称"：字符串，与预算文件中的部门名称保持一致
- "平均收入"：数字，人均年度总收入（含工资、津贴补贴、公积金单位缴存等），单位：万元
- "到手收入"：数字，人均年度到手收入（扣除五险一金个人部分与个人所得税），单位：万元
- "说明"：字符串，简要给出估算方法

# 完整示例
【示例输入】
深圳市市场监督管理局2026年部门预算：……工资福利支出37,410万元，对个人和家庭的补助3,200万元，部门实有人数750人，其中行政编制620人……

【示例输出】
{"results":[{"单位名称":"深圳市市场监督管理局","平均收入":49.88,"到手收入":45.08,"说明":"按(工资福利支出+对个人和家庭补助)÷实有人数估算"}]}

# 待分析内容
（在此粘贴预算 PDF 文本内容）`;

/** JSON 解析错误的行列位置提示（demo jsonErrPos 迁移） */
function jsonErrPos(text: string, e: unknown): string {
  const m = /position\s+(\d+)/i.exec(String((e as Error)?.message || ''));
  if (!m) return '';
  const pos = +m[1];
  const before = text.slice(0, pos);
  const line = before.split('\n').length;
  const col = pos - before.lastIndexOf('\n');
  return `（错误大致位于第 ${line} 行第 ${col} 列附近）`;
}

/**
 * F-07 JSON 回填校验
 * 空文本 → E_INPUT_INVALID；JSON.parse 失败 → E_JSON_SYNTAX；顶层无 results 数组 → E_JSON_STRUCTURE；
 * 条目级无效归入 invalidEntries 单列不阻断
 */
export function validateAiJson(text: string): Result<{ results: AiEntry[]; invalidEntries: unknown[] }> {
  const t = text.trim();
  if (!t) return err('E_INPUT_INVALID', '请先粘贴 AI 返回的 JSON');
  let data: { results?: unknown[] };
  try {
    data = JSON.parse(t);
  } catch (e) {
    return err('E_JSON_SYNTAX', `JSON 非法：${(e as Error).message}${jsonErrPos(t, e)}`);
  }
  if (!data || !Array.isArray(data.results)) {
    return err('E_JSON_STRUCTURE', 'JSON 结构不符合约定：缺少 "results" 数组（见提示词模板中的结构约定）');
  }
  const results: AiEntry[] = [];
  const invalidEntries: unknown[] = [];
  data.results.forEach((item) => {
    const o = item as Record<string, unknown>;
    const unit = String(o?.['单位名称'] ?? '').trim();
    const avg = +(o?.['平均收入'] as number);
    const net = +(o?.['到手收入'] as number);
    if (!unit || (isNaN(avg) && isNaN(net))) {
      invalidEntries.push(item);
      return;
    }
    results.push({ unit, avgIncome: avg, netIncome: net, note: String(o?.['说明'] ?? '') });
  });
  return ok({ results, invalidEntries });
}

/**
 * 回填更新（F-07 规则 6 / Q-D4 双向包含匹配）
 * 每个命中岗位：avgIncome/netIncome 更新；打分重置为 roundIncomeScore(新值)；同单位多岗位一并更新
 * 注意：直接原地修改传入的 jobs（调用方随后 saveState + 重渲染）
 */
export function applyAiResults(jobs: Job[], entries: AiEntry[]): ApplyAiSummary {
  let updatedCount = 0;
  const matchedUnits: string[] = [];
  const unmatchedUnits: string[] = [];
  entries.forEach((e) => {
    const hits = jobs.filter((j) => matchUnit(String(j.unit ?? '').trim(), e.unit));
    if (!hits.length) {
      unmatchedUnits.push(e.unit);
      return;
    }
    matchedUnits.push(e.unit);
    hits.forEach((j) => {
      if (!isNaN(e.avgIncome)) {
        j.avgIncome = e.avgIncome;
        j.incomeScore = roundIncomeScore(e.avgIncome);
      }
      if (!isNaN(e.netIncome)) {
        j.netIncome = e.netIncome;
        j.netScore = roundIncomeScore(e.netIncome);
      }
      updatedCount++;
    });
  });
  return {
    unitCount: matchedUnits.length,
    updatedCount,
    matchedUnits,
    unmatchedUnits,
    invalidEntries: [],
  };
}
