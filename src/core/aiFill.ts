/**
 * AI 收入分析辅助（05 §4.7 / §5 契约；demo AI_PROMPT/doAIApply 迁移为契约函数）
 */
import type { AiEntry, ApplyAiSummary, Job, Result } from '../types';
import { err, ok } from '../types';
import { roundIncomeScore } from './scoring';
import { matchUnit } from './aiMatch';

export { matchUnit };

/** 提示词模板（05 §5.1 完整固化，与 demo/PRD §3.7 一致；岗位清单由 buildAiPrompt 动态注入） */
export const AI_PROMPT_TEMPLATE = `# 任务
你是公共部门收入分析助手。请结合下方「岗位清单」列出的单位，根据我粘贴的部门预算文本，估算每个单位公务员的人均年收入，并严格按下方 JSON 结构返回。

# 输入格式
我会粘贴某部门年度预算的文本内容（通常包含：部门基本情况、人员编制数/实有人数、工资福利支出、对个人和家庭的补助、社会保险缴费、住房公积金缴存、公用经费等）。
注意：多数预算报表并不单独列示在岗人数。若未给出编制数/实有人数，请依据报表中的职工住房公积金月/年缴存额、社会保险（养老/医疗等）缴费基数或单位缴纳额等数据反推在岗职工数，再进行人均估算；实在无法测算时给出合理区间并在「说明」中注明。

# 输出要求（严格遵守）
只输出一个 JSON 对象，不要输出任何解释文字、不要使用 Markdown 代码块标记。结构如下：
{
  "results": [
    {
      "单位名称": "与岗位清单一致的部门（单位）名称",
      "平均收入": 49.88,
      "到手收入": 45.08,
      "说明": "一句话估算依据"
    }
  ]
}
字段约定：
- "单位名称"：字符串，需与「岗位清单」中的招聘单位保持一致；同一单位仅输出一条
- "平均收入"：数字，人均年度总收入（含工资、津贴补贴、单位缴存的住房公积金与社会保险、职业年金及福利补贴等全部口径），单位：万元
- "到手收入"：数字，人均年度到手薪资（仅指工资现金部分，扣除个人所得税与个人缴纳的五险一金后实发；不含住房公积金、福利等非薪资/非现金项目），单位：万元
- "说明"：字符串，简要给出估算方法；若采用公积金/社保测算在岗人数，请一并说明依据

# 岗位清单（以下单位需给出估算，一个单位一条记录）
{JOBS}

# 完整示例
【示例输入】
深圳市市场监督管理局2026年部门预算：……工资福利支出37,410万元，对个人和家庭的补助3,200万元，部门实有人数750人，其中行政编制620人……

【示例输出】
{"results":[{"单位名称":"深圳市市场监督管理局","平均收入":49.88,"到手收入":45.08,"说明":"按(工资福利支出+对个人和家庭补助)÷实有人数估算"}]}

# 待分析内容
（在此粘贴预算 PDF 文本内容）`;

/**
 * F-07 生成带当前岗位清单的提示词：把 {JOBS} 占位替换为「岗位代码｜招聘单位｜招考职位」列表，
 * 供 AiDialog 展示/一键复制；无岗位时占位为空提示
 */
export function buildAiPrompt(jobs: Job[]): string {
  const list = jobs.length
    ? jobs
        .map((j) => `- ${j.unit}${j.title ? `｜${j.title}` : ''}`)
        .join('\n')
    : '（当前无岗位可分析）';
  return AI_PROMPT_TEMPLATE.replace('{JOBS}', list);
}

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
