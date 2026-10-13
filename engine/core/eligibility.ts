/**
 * 国考岗位「资格审查」引擎
 *
 * 依据考生画像对每个岗位做硬条件判定：pass（符合）/ fail（不符合）/ warn（需人工确认）。
 * 判定原则：**只对能从职位表文本确定性判断的条件下结论**；字段缺失或口径不明确时降级为 warn，
 * 避免因数据不完整误杀岗位（宁可多提示，不可错淘汰）。
 *
 * 另提供「备注风险扫描」：职位表备注栏藏着大量隐性门槛（体测、服务年限、性别、户籍、英语等），
 * 这里做成标签提示，供人工复核，不参与 pass/fail 判定。
 */
import type { Job, Profile } from '../types';
import { parseDegreeLevel } from './filter';

/* ---------- 类型 ---------- */

export type EligibilityStatus = 'pass' | 'fail' | 'warn';

export interface EligibilityReason {
  level: 'fail' | 'warn';
  field: string;
  text: string;
}

export interface Eligibility {
  status: EligibilityStatus;
  reasons: EligibilityReason[];
}

/* ---------- 解析辅助 ---------- */

/** 学历等级（与 filter.ts 口径一致） */
const DEGREE_LEVEL: Record<string, number> = { 大专: 1, 本科: 2, 硕士: 3, 博士: 4 };

/** 中文数字 → 阿拉伯数字（基层工作年限常见写法：「二年」） */
const CN_NUM: Record<string, number> = {
  一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
};

/**
 * 「基层工作最低年限」/ 身份限制文本 → 年数
 * 返回 null = 无法识别（调用方按 warn 处理）；0 = 无限制
 *
 * 适配三类真实写法：
 * - 国考「基层工作最低年限」：无限制 / 二年 / 三年
 * - 广东「是否要求2年以上基层工作经历」：**是 / 否**
 * - 浙江「现有身份要求」：不限 / 2年以上基层工作经历 / 应届毕业生 / 服务基层项目人员
 */
export function parseGrassrootsYears(text: string | null | undefined): number | null {
  const s = String(text ?? '').replace(/\s/g, '');
  if (!s) return 0;
  // 广东「是否要求2年以上基层工作经历」的是/否写法
  if (/^是$/.test(s)) return 2;
  if (/^否$/.test(s)) return 0;
  if (/无限制|不限|无要求|不要求|^无$/.test(s)) return 0;
  // 应届类取值（浙江「2025年应届毕业生」）：不是基层年限门槛，且其年份会被误当成年限
  if (/应届/.test(s)) return 0;
  // 只认「N年」这种带「年」单位的写法，且 N 前不能紧跟数字（排除「1988年」被截成「88年」）
  const cn = s.match(/([一二三四五六七八九十])\s*年/);
  if (cn) return CN_NUM[cn[1]] ?? null;
  const num = s.match(/(?:^|\D)(\d{1,2})\s*年/);
  if (num) return parseInt(num[1], 10);
  return null;
}

/** 定向招录身份（面向特定人群，普通考生不可报） */
const DIRECTED_IDENTITY_RE =
  /优秀村干部|优秀社区干部|服务基层项目人员|三支一扶|西部计划|大学生村官|高校毕业生退役军人|退役军人|退役士兵|人武学院|事业编制人员|残疾人|选调生|驻村/;

function firstDirectedIdentity(...texts: (string | null | undefined)[]): string {
  for (const t of texts) {
    const m = String(t ?? '').match(DIRECTED_IDENTITY_RE);
    if (m) return m[0];
  }
  return '';
}

/** 从自由文本中提取政治面貌硬性要求（用于独立列为空时的兜底，如广东把党员写在「其他要求」） */
function politicalFromText(text: string): string {
  const s = String(text ?? '').replace(/\s/g, '');
  if (!s) return '';
  if (/优先/.test(s) && !/必须|须为/.test(s)) return ''; // 「党员优先」非硬性门槛
  if (/中共党员或共青团员|党员或团员/.test(s)) return 'party-or-league';
  if (/中共党员|党员/.test(s)) return 'party';
  if (/共青团员|团员/.test(s)) return 'party-or-league';
  return '';
}

/**
 * 文本是否限定应届。
 * 国考的写法比预想复杂，实测有：**「2027届高校毕业生」「应届高校毕业生」「限2027届高校毕业生」**，
 * 而「应届毕业生」连写反而少见——只匹配后者会大面积漏判。
 */
function isFreshOnly(text: string): boolean {
  const s = String(text ?? '').replace(/\s/g, '');
  if (!s) return false;
  // 明确放开应届限制的写法 → 不算限制
  if (/非应届|不限应届|应届不限|应往届均可|应届往届均可/.test(s)) return false;
  return (
    /应届/.test(s) ||
    /\d{4}届(高校)?毕业生/.test(s) ||
    /\d{4}届高校/.test(s) ||
    /限.{0,4}\d{4}届/.test(s)
  );
}

/**
 * 专业匹配：**先按分隔符切段、剥离专业代码，再逐段精确比对**。
 *
 * 为什么不能整串 includes：岗位专业列常是超长列表（「数学类、物理学类、化学类…」），
 * 整串包含匹配会把「**大气物理学**与大气环境」（大气科学类）误判为命中「物理学」，
 * 也会让「计算机类」命中「计算」之类的子串。
 *
 * 命中规则：某一段 与 我的专业/大类 **相等**，或该段 = 我的大类（如 seg「物理学类」 vs mine「物理学」）。
 */
function majorHit(reqRaw: string, mine: string[]): boolean {
  const segs = reqRaw
    .replace(/[（(][^）)]*[）)]/g, '')
    .split(/[,，、;；/／]/)
    .map((s) =>
      s
        .replace(/^\d{4}[A-Za-z]?/, '') // 去掉开头的专业代码（如「0702物理学」）
        .replace(/^[^：:\s]{1,12}[：:]/, '') // 去掉「大学本科：」「研究生：」这类层别前缀
        .replace(/\s/g, '')
        .trim(),
    )
    .filter(Boolean);
  if (!segs.length) return true; // 无法分段（罕见）→ 不据此淘汰，避免误杀
  return mine.some((m) => {
    const mm = String(m ?? '').replace(/\s/g, '');
    if (!mm) return false;
    const cls = mm.endsWith('类') ? mm : `${mm}类`;
    return segs.some((seg) => seg === mm || seg === cls || (seg.endsWith('类') && mm.endsWith('类') && seg === mm));
  });
}

/** 岗位全文（用来扫证书/身份一类的隐性要求） */
function jobText(job: Job): string {
  return [job.title, job.intro, job.major, job.politicalStatus, job.institution, job.remark]
    .filter(Boolean)
    .join(' ');
}

/** 政治面貌要求 */
function parsePoliticalRequirement(text: string): 'none' | 'party' | 'party-or-league' | 'unknown' {
  const s = String(text ?? '').replace(/\s/g, '');
  if (!s || /不限/.test(s)) return 'none';
  if (/中共党员或共青团员|党员或团员/.test(s)) return 'party-or-league';
  if (/中共党员|党员/.test(s)) return 'party';
  if (/共青团员|团员/.test(s)) return 'party-or-league';
  return 'unknown';
}

/** 画像是否已填写（未填画像时不做任何淘汰判定，避免误杀） */
export function profileReady(profile: Profile): boolean {
  return !!(
    profile.degree ||
    profile.major ||
    profile.majorCategory ||
    profile.grassrootsYears != null ||
    profile.politicalStatus
  );
}

/* ---------- 逐岗判定 ---------- */

export function judgeJob(job: Job, profile: Profile): Eligibility {
  const reasons: EligibilityReason[] = [];
  const ready = profileReady(profile);

  // ① 学历
  if (profile.degree) {
    const need = parseDegreeLevel(job.degree);
    const mine = DEGREE_LEVEL[profile.degree] ?? 99;
    if (need > mine) {
      reasons.push({ level: 'fail', field: '学历', text: `要求「${job.degree || '未知'}」，高于你的${profile.degree}` });
    }
  }

  // ② 专业（职位表「专业」列 vs 我的专业 / 专业大类）
  //    分段精确匹配：见 majorHit 说明（整串 includes 会误命中「大气物理学」这类）
  if (ready && (profile.major || profile.majorCategory) && job.major) {
    if (!/不限|无限制/.test(job.major.replace(/\s/g, ''))) {
      const mine = [profile.major, profile.majorCategory].filter(Boolean);
      if (!majorHit(job.major, mine)) {
        reasons.push({ level: 'fail', field: '专业', text: `要求「${job.major}」` });
      }
    }
  }

  // ③ 基层工作经历（国考核心维度；广东是/否写法、浙江并入「现有身份要求」）
  const grassText = String(job.grassrootsYears ?? '').trim();
  const directed = firstDirectedIdentity(grassText, job.serviceProject, job.remark);
  const needYears = parseGrassrootsYears(grassText);
  if (needYears != null && needYears > 0) {
    if (profile.grassrootsYears == null) {
      reasons.push({ level: 'warn', field: '基层经历', text: `要求 ${needYears} 年，未填写你的年限` });
    } else if (profile.grassrootsYears < needYears) {
      reasons.push({ level: 'fail', field: '基层经历', text: `要求 ${needYears} 年，你 ${profile.grassrootsYears} 年` });
    }
  }
  // ③b 定向招录（优秀村干部 / 服务基层项目人员 / 退役军人…）：面向特定人群，普通考生不可报
  if (ready && directed) {
    reasons.push({ level: 'warn', field: '定向招录', text: `面向「${directed}」等特定身份，需确认是否符合` });
  } else if (ready && needYears == null && grassText) {
    // 无法识别的身份/年限文本 → 交人工确认，不静默放过
    reasons.push({ level: 'warn', field: '身份限制', text: `「${grassText}」需人工确认` });
  }

  // ④ 政治面貌（独立列为空时从备注/其他要求兜底：广东把「中共党员」写在「其他要求」列）
  if (ready) {
    const ownField = job.politicalStatus;
    const fallback = politicalFromText(jobText(job));
    // 注意：politicalFromText 返回的已是归一化枚举值，不可再喂回 parsePoliticalRequirement
    const need: 'none' | 'party' | 'party-or-league' | 'unknown' =
      (!ownField || /不限/.test(ownField)) && fallback
        ? (fallback as 'party' | 'party-or-league')
        : parsePoliticalRequirement(ownField);
    const mine = profile.politicalStatus;
    if (need === 'party' && mine && mine !== 'party') {
      reasons.push({ level: 'fail', field: '政治面貌', text: '仅限中共党员' });
    } else if (need === 'party-or-league' && mine === 'none') {
      reasons.push({ level: 'fail', field: '政治面貌', text: '要求党员或团员' });
    }
  }

  // ⑤ 法律职业资格（从标题/简介/备注文本判断）
  if (ready && /法律职业资格/.test(jobText(job)) && !profile.hasLegalCert) {
    reasons.push({ level: 'fail', field: '证书', text: '要求法律职业资格证书' });
  }

  // ⑥ 应届身份
  //    广东有独立「是否限应届毕业生报考」列；浙江写进「现有身份要求」；
  //    国考**没有独立列**，只能从备注/职位简介兜底（「2027届高校毕业生」等写法）
  if (ready && !profile.fresh) {
    const fc = String(job.freshRequired ?? '').trim();
    const identity = `${job.grassrootsYears ?? ''} ${jobText(job)}`;
    if (/^是$/.test(fc)) {
      reasons.push({ level: 'fail', field: '身份', text: '面向应届毕业生' });
    } else if (!/^否$/.test(fc) && isFreshOnly(identity)) {
      reasons.push({ level: 'fail', field: '身份', text: '面向应届毕业生（限 XX 届高校毕业生）' });
    }
  }

  // ⑦ 体能测评（公安/监狱/法警类的硬门槛，通过方能进面）：交人工确认，不当作「符合」
  if (ready) {
    const pt = String(job.physicalTest ?? '').trim();
    const byColumn = /^是$/.test(pt);
    const byText =
      /体能测评|体能测试|体测/.test(jobText(job)) ||
      /公安|警察|警长|警员|监狱|戒毒|司法警察/.test(`${job.institution} ${job.title}`);
    if ((byColumn || byText) && !/^否$/.test(pt)) {
      reasons.push({ level: 'warn', field: '体测', text: '需通过体能测评（公安/监狱/法警类）' });
    }
  }

  const status: EligibilityStatus = reasons.some((r) => r.level === 'fail')
    ? 'fail'
    : reasons.length
      ? 'warn'
      : 'pass';
  return { status, reasons };
}/** 批量判定（返回按岗位 code 索引的结果表） */
export function judgeAll(jobs: Job[], profile: Profile): Map<string, Eligibility> {
  const map = new Map<string, Eligibility>();
  jobs.forEach((j) => map.set(j.code, judgeJob(j, profile)));
  return map;
}

/* ---------- 备注风险扫描（提示用，不参与淘汰）---------- */

const RISK_RULES: Array<{ re: RegExp; label: string }> = [
  { re: /体能测评|体能测试|体测/, label: '需体测' },
  { re: /最低服务年限|服务年限|服务期/, label: '服务年限' },
  { re: /适合男性|仅限男性|限男性|男性/, label: '限男性' },
  { re: /法律职业资格/, label: '需法考' },
  { re: /英语|四级|六级|CET|专业八级|专八/, label: '英语要求' },
  { re: /夜班|倒班|轮班|值班|驻守|备勤/, label: '倒班' },
  { re: /经常出差|长期出差|出差|外派|驻外/, label: '出差' },
  { re: /户籍|生源/, label: '户籍限制' },
  { re: /限应届|应届毕业生/, label: '限应届' },
  { re: /艰苦边远|偏远|边远地区|乡镇|基层一线/, label: '艰苦边远' },
  { re: /中共党员|党员/, label: '限党员' },
  { re: /专业能力测试|专业科目/, label: '加试专业' },
  { re: /五年|5年|五年内不得|服务满/, label: '长服务期' },
];

/** 扫描岗位文本，返回命中的风险标签（去重保序） */
export function scanRisks(job: Job): string[] {
  const text = jobText(job);
  if (!text.trim()) return [];
  const hit: string[] = [];
  RISK_RULES.forEach((r) => {
    if (r.re.test(text) && !hit.includes(r.label)) hit.push(r.label);
  });
  return hit;
}

/** 汇总统计（用于筛选栏/工具条展示） */
export function summarize(jobs: Job[], profile: Profile): { pass: number; fail: number; warn: number } {
  let pass = 0;
  let fail = 0;
  let warn = 0;
  jobs.forEach((j) => {
    const s = judgeJob(j, profile).status;
    if (s === 'pass') pass += 1;
    else if (s === 'fail') fail += 1;
    else warn += 1;
  });
  return { pass, fail, warn };
}
