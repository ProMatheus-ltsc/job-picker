/**
 * 业务类型定义（05-api-doc §3 数据结构契约的 TS 化）
 * Job 字段命名遵循契约：applicants/hires（demo 的 applyCount/hireCount 迁移时更名）
 */

/** 统一结果结构（05 §1.1） */
export type Result<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };

export function ok<T>(data: T): Result<T> {
  return { ok: true, data };
}

export function err<T = never>(code: string, message: string): Result<T> {
  return { ok: false, error: { code, message } };
}

/** 轮次三态标记（05 §3.4） */
export type MarkStatus = 'pending' | 'promote' | 'eliminate';

/** 源表数据（05 §3.2） */
export interface RawTable {
  sheetName: string | null;
  columns: string[];
  rows: (string | null)[][];
}

/** 13 标准字段定义（F-02 列映射目标，demo FIELDS 原样迁移） */
export interface FieldDef {
  key: StandardFieldKey;
  name: string;
  required?: boolean;
  /** 别名：外部表格（如国考/省考职位表）的常见列名，用于自动列匹配 */
  aliases?: string[];
  /**
   * 允许多列合并：源表把同一语义拆成多列时（如广东省考的专业分
   * 「研究生专业名称及代码 / 本科专业名称及代码 / 大专专业名称及代码」三列），
   * 全部命中的列合并为一个字段值。单列字段（默认）只取优先级最高的那一列。
   */
  multi?: boolean;
}

export type StandardFieldKey =
  | 'code'
  | 'unit'
  | 'title'
  | 'avgIncome'
  | 'netIncome'
  | 'incomeScore'
  | 'netScore'
  | 'applicants'
  | 'hires'
  | 'region'
  | 'degree'
  | 'major'
  | 'intro'
  // ===== 国考/省考职位表专有字段（资格审查用；不映射不影响基础使用）=====
  | 'politicalStatus'
  | 'grassrootsYears'
  | 'serviceProject'
  | 'institution'
  /** 是否限应届毕业生（广东省考独立成列，取值「是/否」） */
  | 'freshRequired'
  /** 是否体能测评（浙江独立成列；广东用「职位类型=公安机关执法勤务职位」等兜底） */
  | 'physicalTest';

export const FIELDS: FieldDef[] = [
  // 别名顺序 = 匹配优先级（越靠前越精确），单列字段按此顺序取第一个命中
  { key: 'code', name: '岗位代码', required: true, aliases: ['职位代码', '职位编码', '岗位编码'] },
  { key: 'unit', name: '招聘单位', required: true, aliases: ['用人司局', '招录单位名称', '招录机关名称', '招录机关', '招考单位', '部门名称', '单位名称'] },
  { key: 'title', name: '招考职位', aliases: ['职位名称', '岗位名称'] },
  { key: 'avgIncome', name: '平均收入(万)' },
  { key: 'netIncome', name: '到手收入(万)' },
  { key: 'incomeScore', name: '收入打分' },
  { key: 'netScore', name: '到手收入打分' },
  { key: 'applicants', name: '报名人数', aliases: ['过审人数', '报名过审人数', '报名人数统计'] },
  { key: 'hires', name: '录用人数', aliases: ['招考人数', '招录人数', '计划录用人数', '招聘人数'] },
  { key: 'region', name: '考区', aliases: ['工作地点', '落户地点', '工作地', '工作地区'] },
  { key: 'degree', name: '学历', aliases: ['学历要求'] },
  // multi：广东把专业按学历层拆成三列，全部命中即合并
  {
    key: 'major',
    name: '专业要求',
    multi: true,
    aliases: ['研究生专业名称及代码', '本科专业名称及代码', '大专专业名称及代码', '专业名称及代码', '所需专业', '专业'],
  },
  { key: 'intro', name: '职位简介', aliases: ['职位描述', '岗位职责'] },
  { key: 'politicalStatus', name: '政治面貌', aliases: ['政治面貌要求'] },
  // 广东写作「是否要求2年以上基层工作经历」（是/否）；浙江把基层经历并进「现有身份要求」
  {
    key: 'grassrootsYears',
    name: '基层工作最低年限',
    aliases: ['是否要求2年以上基层工作经历', '现有身份要求', '基层工作经历要求', '基层工作经历', '基层工作年限'],
  },
  { key: 'serviceProject', name: '服务基层项目工作经历', aliases: ['服务基层项目经历', '面向服务基层项目人员'] },
  // 广东用「职位类型」，浙江用「职位属性 / 职位大类」
  { key: 'institution', name: '机构性质', aliases: ['职位属性', '职位类型', '部门性质', '机构层级', '职位大类'] },
  // 广东独立成列（是/否）；浙江并入「现有身份要求」文本
  {
    key: 'freshRequired',
    name: '是否限应届',
    aliases: ['是否限应届毕业生报考', '限应届毕业生报考', '是否限应届毕业生', '应届生要求'],
  },
  // 浙江独立成列（是/否）；公安/监狱等即使不列也需体测（由 eligibility 兜底判断）
  {
    key: 'physicalTest',
    name: '是否体能测评',
    aliases: ['是否体能测试', '是否开展体能测评', '体能测评要求', '体能测试'],
  },
];

/**
 * 列映射值：标准字段 → 源列索引。**允许数组**（多列合并，如广东的三列专业）。
 * 兼容历史数据：旧版本存的是 number|null，读取时由 mappingIndices 统一归一化。
 */
export type MappingValue = number | number[] | null;

/** 列映射：标准字段 → 源列索引（05 §3.3，demo 的列名口径迁移为索引口径） */
export type Mapping = Partial<Record<StandardFieldKey, MappingValue>>;

/** 映射值 → 列索引数组（**全应用统一消费口径**，禁止各处自行解构） */
export function mappingIndices(v: MappingValue | undefined): number[] {
  if (v == null) return [];
  const arr = Array.isArray(v) ? v : [v];
  return arr.filter((i) => typeof i === 'number' && i >= 0);
}

/** 该字段是否已映射（任一列即可） */
export function isMapped(v: MappingValue | undefined): boolean {
  return mappingIndices(v).length > 0;
}

/** 政治面貌取值 */
export type PoliticalStatus = '' | 'party' | 'league' | 'none';

/**
 * 考生画像（05 §3.6 + 国考资格审查扩展）
 * 新增字段全部可选语义（空值 = 不限），旧数据加载时由 emptyProfile 兜底
 */
export interface Profile {
  degree: '' | '大专' | '本科' | '硕士' | '博士';
  regions: string[];
  /**
   * **目标城市**（选岗报告 + 过滤，模糊匹配）。
   * 职位表的「工作地点」是「广东省深圳市」这类全称，逐级写死无法穷举，
   * 故这里填城市简称即可——填「深圳」即可命中「广东省深圳市」「深圳市福田区」等。
   */
  targetCities: string[];
  /** 专业名称（如「法学」），与职位表「专业」列做包含匹配 */
  major: string;
  /** 专业大类（如「法学类」），职位表常按大类招录 */
  majorCategory: string;
  /** 基层工作经历年限（年）；国考核心筛选维度 */
  grassrootsYears: number | null;
  /** 政治面貌 */
  politicalStatus: PoliticalStatus;
  /** 是否持有法律职业资格证书（A 证） */
  hasLegalCert: boolean;
  /** 是否应届毕业生 */
  fresh: boolean;
}

/** 岗位记录（05 §3.4） */
export interface Job {
  /**
   * 岗位**唯一标识**（内部索引：标记 / 编辑 / 展开 / 重映射均以此为准）。
   *
   * 为什么不能直接用 code：国考正式表中「职位代码」跨部门重复——例如
   * `300110004001` 同时属于「北京市通信管理局·业务处室」和「内蒙古自治区通信管理局·政策法规处」，
   * 省级以下 sheet 18193 行里唯一职位代码只有 6339 个。若按 code 去重会丢掉 2/3 岗位。
   * 故唯一键 = 职位代码 + 用人司局（同表内仍冲突时追加序号）。
   */
  key: string;
  /** 真实职位代码（用于展示、报名、导出） */
  code: string;
  unit: string;
  title: string;
  avgIncome: number | null;
  netIncome: number | null;
  incomeScore: number | null;
  netScore: number | null;
  applicants: number | null;
  hires: number | null;
  region: string;
  degree: string;
  major: string;
  intro: string;
  /** ===== 国考职位表专有（资格审查依据）===== */
  /** 政治面貌原文，如「不限」「中共党员」「中共党员或共青团员」 */
  politicalStatus: string;
  /** 基层工作最低年限原文，如「无限制」「二年」「三年」 */
  grassrootsYears: string;
  /** 服务基层项目工作经历原文，如「无限制」「三支一扶」 */
  serviceProject: string;
  /** 机构性质原文，如「中央党群机关」「中央国家行政机关省级以下直属机构」 */
  institution: string;
  /** 是否限应届原文（广东省考独立列，取值「是/否」；国考/浙江多为空） */
  freshRequired: string;
  /** 是否体能测评原文（浙江独立列，取值「是/否」；广东/国考多为空） */
  physicalTest: string;
  remark: string;
  marks: MarkStatus[];
}

/** 内存态筛选条件（05 §3.8，不持久化） */
export interface Filters {
  region: string;
  degree: string;
  majorKeyword: string;
  applyMin: number | null;
  applyMax: number | null;
  /** 只看资格审查通过的岗位（国考扩展） */
  onlyEligible: boolean;
}

export type SortKey =
  | 'applicants'
  | 'hires'
  | 'ratio'
  | 'avgIncome'
  | 'netIncome'
  | 'incomeScore'
  | 'netScore'
  | 'total';

export interface SortState {
  key: SortKey;
  dir: 'asc' | 'desc';
}

/** 内存态全量业务状态（loadState 组装出参，05 §3.1） */
export interface AppState {
  schemaVersion: number;
  source: 'demo' | 'file';
  importedAt: string;
  raw: RawTable;
  mapping: Mapping;
  remarkCols: number[];
  rounds: string[];
  profile: Profile;
  jobs: Job[];
}

export const DEFAULT_ROUNDS = ['初筛', '二次筛选', '三次筛选', '最终'];

export function emptyProfile(): Profile {
  return {
    degree: '',
    regions: [],
    targetCities: [],
    major: '',
    majorCategory: '',
    grassrootsYears: null,
    politicalStatus: '',
    hasLegalCert: false,
    fresh: false,
  };
}

export function emptyFilters(): Filters {
  return {
    region: '',
    degree: '',
    majorKeyword: '',
    applyMin: null,
    applyMax: null,
    onlyEligible: false,
  };
}

/** AI 回填条目（05 §3.9） */
export interface AiEntry {
  unit: string;
  avgIncome: number;
  netIncome: number;
  note: string;
}

export interface ApplyAiSummary {
  unitCount: number;
  updatedCount: number;
  matchedUnits: string[];
  unmatchedUnits: string[];
  invalidEntries: unknown[];
}

/** 数值解析（demo num() 原样迁移：空/非数字 → null） */
export function num(v: string | number | null | undefined): number | null {
  if (v === '' || v == null) return null;
  const n = +v;
  return isNaN(n) ? null : n;
}
