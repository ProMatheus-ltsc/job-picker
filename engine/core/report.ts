/**
 * 选岗分析报告引擎
 *
 * 把「导入 → 资格审查 → 强度筛查 → 区级薪酬 → 进面概率 → 帕累托前沿 → 结论」一次算完，
 * 供界面展示与导出。
 *
 * ★ 2026-11-04 改造要点（对应改造方案 P0/P1）：
 * - **P0-3 强度筛查**：heavy 岗位直接排除出候选（当天一次筛掉 265/433 岗，占 61%）；
 * - **P0-4 区级薪酬**：薪酬档下沉到区，荔湾与南沙不再被判成同一档；
 * - **P1-2 概率模型**：替换原先「收入 ÷ 报录比」的量纲混杂公式；
 * - **P1-3 帕累托**：剔除"没有理由选它"的岗位；
 * - **P1-4 范围提示**：报告末尾强制输出范围外缺口。
 *
 * 设计目标（对应真实使用场景）：
 * 用户导入官方职位表 + 填画像 + 填目标城市，**一键得到「哪些城市有几个能报、哪些值得纠结」的结论**。
 * 判定口径全部复用 eligibility，保证与表格列的 ✅/❌/⚠️ 完全一致。
 */
import type { Job, Profile } from '../types';
import { inTargetCity } from './filter';
import { judgeJob, scanRisks, type EligibilityStatus } from './eligibility';
import { estimateCompetition, hardGates, recommendStar, type CompetitionResult } from './competition';
import {
  estimateSalaryForJob,
  salaryLabel,
  salaryMidpoint,
  yearsForHousing,
  type CitySalary,
} from './salary';
import { scanIntensity, type IntensityResult } from './intensity';
import { estimateProbability, type ProbabilityInput, type ProbabilityResult } from './probability';
import { nonDominated, type ParetoResult } from './pareto';
import {
  GK_CUTOFF_SOURCE,
  SK_CUTOFF_SOURCE,
  cutoffGrade,
  type ExamType,
} from './examMode';

export interface RegionStat {
  region: string;
  total: number;
  pass: number;
}

export interface CountStat {
  label: string;
  count: number;
}

/** 综合排序候选（性价比 × 竞争激烈度） */
export interface RankedCandidate {
  job: Job;
  comp: CompetitionResult;
  salary: CitySalary & { precise: boolean };
  /** 买 100㎡ 需多少年收入 */
  yearsForHousing: number;
  /** 推荐指数 0.5~5 星 */
  star: number;
  /** 额外门槛（英语/法考/加试/户籍）——非空表示需先自评是否满足 */
  gates: string[];
  /** 工作强度（P0-3） */
  intensity: IntensityResult;
  /** 进面概率（P1-2）；无输入时为 null */
  probability: ProbabilityResult | null;
  /** 薪酬中位（万元），帕累托与散点图的薪酬轴 */
  salaryMid: number;
}

export interface SelectionReport {
  /** 参与判定的岗位数（已按目标城市收窄；未填目标城市则为全量） */
  total: number;
  pass: number;
  fail: number;
  warn: number;
  examType: ExamType;
  /** 是否符合条件（有 fail 即不符） */
  cityStats: RegionStat[];
  /** 符合岗位最多的工作地点（全量降序，用于发现计划外的好去处） */
  topRegions: RegionStat[];
  /** 淘汰原因分布（按维度计次） */
  failReasons: CountStat[];
  /** 符合岗位里的风险提示分布（服务年限 / 英语 / 体测…） */
  riskTags: CountStat[];
  /** 强度信号分布 */
  intensityTags: CountStat[];
  /** 符合条件且强度可接受的岗位（已按地点 + 单位排序） */
  candidates: Job[];
  /** 因工作强度被排除的岗位（heavy） */
  excludedByIntensity: Array<{ job: Job; intensity: IntensityResult }>;
  /** 因画像偏好被排除的岗位（排除区/最低年薪/不接受服务期/不接受某类强度） */
  excludedByPreference?: Array<{ job: Job; reasons: string[] }>;
  /** 综合排序（推荐指数降序；含无门槛的排在前） */
  ranked: RankedCandidate[];
  /** 帕累托前沿（薪酬 × 概率） */
  pareto: ParetoResult;
}

/** 该岗位命中的 heavy 类别是否**全部**已被画像接受（全部接受才放行） */
function allAccepted(intensity: IntensityResult, accepted: Set<string>): boolean {
  const heavyHits = intensity.hits.filter((hit) =>
    ['duty', 'enforce', 'emergency'].includes(hit.category),
  );
  if (!heavyHits.length) return false;
  return heavyHits.every((hit) => accepted.has(hit.category));
}

const TOP_N = 12;

function bump(map: Map<string, number>, key: string): void {
  map.set(key, (map.get(key) ?? 0) + 1);
}

function topStats(map: Map<string, number>, n = TOP_N): CountStat[] {
  return [...map.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'zh'))
    .slice(0, n);
}

/** 概率输入模板：按岗位组装（报名人数可从职位表「报名人数」列或外部文件来） */
export interface ProbabilityContext {
  mu: number | null;
  sigma: number | null;
  /** 进面线区间下沿（来自区级/层级代理或官方数据） */
  cutoffMin: number | null;
  /** 进面线区间上沿 */
  cutoffMax: number | null;
  /** 进面比，默认 3 */
  interviewRatio?: number | null;
}

export interface BuildReportOptions extends Partial<ProbabilityContext> {
  examType?: ExamType;
  /**
   * 是否保留 heavy 岗位（默认 false = 排除）。
   * 设为 true 时，强度等级进入候选并在报告中标注，用于"我就想看看有哪些值班岗"的场景。
   */
  keepHeavy?: boolean;
  /**
   * 画像明确接受的强度类别（如用户说"接受值班"→ ['duty']）。
   *
   * 这些类别命中的岗位仍会在结果里标注 `intensity.level='heavy'`，
   * 但**不因该类别被排除**——因为用户已经明确接受它。
   * 与 `keepHeavy` 的区别：keepHeavy 是"全部保留"（调试用），
   * acceptedCategories 是"只放行我接受的类别"，其余类别照常排除。
   */
  acceptedCategories?: string[];
}

/** 按岗位组装概率输入 */
function probabilityInputFor(job: Job, ctx: BuildReportOptions): ProbabilityInput {
  const examType = ctx.examType ?? 'gk';
  return {
    mu: ctx.mu ?? null,
    sigma: ctx.sigma ?? null,
    cutoffMin: ctx.cutoffMin ?? null,
    cutoffMax: ctx.cutoffMax ?? ctx.cutoffMin ?? null,
    hires: job.hires ?? null,
    interviewRatio: ctx.interviewRatio ?? 3,
    applicants: job.applicants ?? null,
    // ★ 进面线级别必须随考试类型走，否则国考会显示 A 级概率却标 C 级线（CRITICAL）
    cutoffGrade: cutoffGrade(examType),
    cutoffSource: examType === 'sk' ? SK_CUTOFF_SOURCE : GK_CUTOFF_SOURCE,
  };
}

/**
 * 生成选岗分析报告。
 * @param jobs 全量岗位（不做轮次/标记过滤，报告是"这份表能报什么"的全景）
 * @param profile 考生画像（含 targetCities）
 * @param options 概率模型输入与强度开关
 */
export function buildSelectionReport(
  jobs: Job[],
  profile: Profile,
  options: BuildReportOptions = {},
): SelectionReport {
  const cities = profile.targetCities ?? [];
  const scope = cities.length ? jobs.filter((j) => inTargetCity(j.region, cities)) : jobs.slice();
  const examType: ExamType = options.examType ?? 'gk';
  const accepted = new Set(options.acceptedCategories ?? []);

  const failMap = new Map<string, number>();
  const riskMap = new Map<string, number>();
  const intensityMap = new Map<string, number>();
  const regionAgg = new Map<string, RegionStat>();
  const statusByKey = new Map<string, EligibilityStatus>();
  const candidates: Job[] = [];
  const excludedByIntensity: Array<{ job: Job; intensity: IntensityResult }> = [];
  let pass = 0;
  let fail = 0;
  let warn = 0;

  for (const j of scope) {
    const e = judgeJob(j, profile);
    statusByKey.set(j.key, e.status);

    const rk = j.region || '（未标注）';
    const rs = regionAgg.get(rk) ?? { region: rk, total: 0, pass: 0 };
    rs.total += 1;

    if (e.status === 'pass') {
      pass += 1;
      rs.pass += 1;
      scanRisks(j).forEach((t) => bump(riskMap, t));

      // ★ P0-3 强度筛查：heavy 直接排除（除非显式 keepHeavy，或该类别已被画像接受）
      const intensity = scanIntensity(j);
      intensity.hits.forEach((h) => bump(intensityMap, `${h.category}:${h.kw}`));
      if (intensity.level === 'heavy' && !options.keepHeavy && !allAccepted(intensity, accepted)) {
        excludedByIntensity.push({ job: j, intensity });
        regionAgg.set(rk, rs);
        continue;
      }
      candidates.push(j);
    } else if (e.status === 'fail') {
      fail += 1;
      e.reasons.filter((r) => r.level === 'fail').forEach((r) => bump(failMap, r.field));
    } else {
      warn += 1;
    }
    regionAgg.set(rk, rs);
  }

  // 目标城市逐城命中（模糊匹配：填「深圳」即可命中「广东省深圳市」）
  const cityStats: RegionStat[] = cities
    .map((c) => {
      let total = 0;
      let p = 0;
      for (const j of scope) {
        if (!inTargetCity(j.region, [c])) continue;
        total += 1;
        if (statusByKey.get(j.key) === 'pass') p += 1;
      }
      return { region: c, total, pass: p };
    })
    .sort((a, b) => b.pass - a.pass || b.total - a.total);

  const topRegions = [...regionAgg.values()]
    .filter((r) => r.pass > 0)
    .sort((a, b) => b.pass - a.pass || b.total - a.total)
    .slice(0, TOP_N);

  candidates.sort(
    (a, b) => a.region.localeCompare(b.region, 'zh') || a.unit.localeCompare(b.unit, 'zh'),
  );

  // 综合排序：无额外门槛优先 → 推荐指数降序 → 买房年数升序 → 竞争度升序
  const ranked: RankedCandidate[] = candidates
    .map((job) => {
      const comp = estimateCompetition(job);
      const salary = estimateSalaryForJob(job);
      const years = yearsForHousing(salary);
      const gates = hardGates(job).filter((g) => g !== '性别限制');
      const probability = estimateProbability(probabilityInputFor(job, options));
      return {
        job,
        comp,
        salary,
        yearsForHousing: years,
        star: recommendStar(years, comp.score, job.hires),
        gates,
        intensity: scanIntensity(job),
        probability,
        salaryMid: salaryMidpoint(salary),
      };
    })
    .sort(
      (a, b) =>
        (a.gates.length ? 1 : 0) - (b.gates.length ? 1 : 0) ||
        b.star - a.star ||
        a.yearsForHousing - b.yearsForHousing ||
        a.comp.score - b.comp.score,
    );

  // ★ P1-3 帕累托：薪酬 × 概率两轴非支配排序
  const pareto = nonDominated(
    ranked.map((r) => ({
      key: r.job.code,
      label: `${r.job.unit}·${r.job.title}`,
      salaryMid: r.salaryMid,
      probability: r.probability?.p ?? null,
    })),
  );

  return {
    total: scope.length,
    pass,
    fail,
    warn,
    examType,
    cityStats,
    topRegions,
    failReasons: topStats(failMap),
    riskTags: topStats(riskMap),
    intensityTags: topStats(intensityMap),
    candidates,
    excludedByIntensity,
    ranked,
    pareto,
  };
}

/** 报告里某条候选的展示名 */
export function candidateLabel(job: Job): string {
  return `${job.unit}${job.title ? `·${job.title}` : ''}`;
}

/** 报告里某条候选的地区展示（带区） */
export function candidateRegion(job: Job): string {
  return salaryLabel(estimateSalaryForJob(job));
}
