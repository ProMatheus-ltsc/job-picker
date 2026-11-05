/**
 * 考试类型分支（国考 gk / 省考 sk）
 *
 * 为什么必须有这个分支：`interview_scores.py` 的数据链依赖「面试名单含最低分数」——
 * 国考税务局**有**（附件里带"进入面试最低分数"列），**广东省考没有**（名单只有姓名+准考证号，
 * 分数列根本不存在）。若不分模式，省考会整条链失效或产出空结论。
 *
 * 两套数据链（改造方案 §五 P0-2）：
 *
 * | 环节 | 国考（gk） | 省考（sk） |
 * |------|-----------|-----------|
 * | 进面分 | 官方面试名单附件（A 级） | **无**，用区级/层级实测代理 + 明确标注推算（C 级） |
 * | 报录比 | 官方报名期逐日 | 官方报名期逐日（广东确有）+ 机构排行榜回填（D 级，禁用） |
 * | 职位表 | 招考简章.xls 单表 | 多 sheet（县以上/公安/法院/检察院/监狱/乡镇），**来源表决定 5 年服务期** |
 */

import type { DataGrade } from './datagrade';

export type ExamType = 'gk' | 'sk';

export const EXAM_TYPE_LABEL: Record<ExamType, string> = {
  gk: '国考',
  sk: '省考',
};

/** 解析 --exam-type 取值；非法返回 null（由 CLI 决定退出码） */
export function parseExamType(raw: string | null | undefined): ExamType | null {
  const value = String(raw ?? '').trim().toLowerCase();
  if (!value) return 'gk'; // 缺省按国考（与改造前的历史行为一致）
  if (value === 'gk' || value === 'sk') return value;
  return null;
}

export const EXAM_TYPE_USAGE = '--exam-type <gk|sk>（gk=国考，缺省；sk=省考）';

/**
 * 省考职位表的 6 类来源表 → 最低服务年限。
 *
 * ★ 关键规律：来源表决定了 5 年最低服务期。
 * 广东省考职位表按「县以上机关 / 公安机关 / 法院 / 检察院 / 监狱戒毒 / 乡镇机关」分 sheet；
 * **乡镇机关**普遍要求「在乡镇机关最低服务 5 年」，这是硬约束（考上就不能走）。
 *
 * 规则：**已知来源表才给年限；未知一律 null（不猜）**。
 */
export const SOURCE_SHEET_SERVICE_YEARS: Record<string, number | null> = {
  县以上机关: null,
  县以上: null,
  公安机关: null,
  公安: null,
  法院: null,
  检察院: null,
  监狱戒毒: null,
  监狱: null,
  乡镇机关: 5,
  乡镇: 5,
};

/**
 * 来源表 → 最低服务年限；未知来源表返回 null（不猜）。
 *
 * 真实职位表的 sheet 名几乎都带前缀（「附件1：乡镇机关职位表」「附件2-县以上机关」），
 * 因此不能要求精确相等。这里按**最长匹配**取值：
 * 「附件1：乡镇机关职位表」同时包含「乡镇」与「乡镇机关」，取更长的「乡镇机关」，
 * 避免因为命中两个别名而放弃判定（那是把"已知"退化成"未知"）。
 */
export function minServiceYears(sourceSheet: string | null | undefined): number | null {
  const key = String(sourceSheet ?? '').trim();
  if (!key) return null;
  if (key in SOURCE_SHEET_SERVICE_YEARS) return SOURCE_SHEET_SERVICE_YEARS[key];
  const matched = Object.keys(SOURCE_SHEET_SERVICE_YEARS)
    .filter((name) => key.includes(name))
    .sort((a, b) => b.length - a.length);
  if (!matched.length) return null;
  return SOURCE_SHEET_SERVICE_YEARS[matched[0]];
}

/** 该岗位是否受「5 年最低服务期」约束 */
export function hasLongServiceBond(sourceSheet: string | null | undefined): boolean {
  const years = minServiceYears(sourceSheet);
  return years != null && years >= 5;
}

/** 进面分在该考试类型下的数据级别：国考税务有官方名单（A），省考无逐岗线（C） */
export function cutoffGrade(examType: ExamType): DataGrade {
  return examType === 'gk' ? 'A' : 'C';
}

/** 进面分在省考下的来源说明（报告口径声明直接引用） */
export const SK_CUTOFF_SOURCE =
  '省考官方只公布合格线，不公布逐岗进面线；本值为区级/层级实测代理（C 级，只读方向）';

export const GK_CUTOFF_SOURCE = '国考招录机关面试公告附件（面试人员名单含进入面试最低分数）';

/** 一句话说明该模式下的数据链差异（写进报告） */
export function examTypeNote(examType: ExamType): string {
  if (examType === 'sk') {
    return '省考模式：进面线采用区级/层级代理（C 级，不进排序公式）；来源表=乡镇机关的岗位标 5 年最低服务期。';
  }
  return '国考模式：进面分取自招录机关面试公告附件（A 级，一手）。';
}
