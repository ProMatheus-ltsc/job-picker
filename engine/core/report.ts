/**
 * 选岗分析报告引擎
 *
 * 把「导入 → 资格审查 → 结论」一次算完，供界面展示与导出：
 * 总览计数 · 目标城市逐城命中 · 淘汰原因分布 · 风险提示分布 · 符合岗位清单。
 *
 * 设计目标（对应真实使用场景）：
 * 用户导入官方职位表 + 填画像 + 填目标城市，**一键得到「哪些城市有几个能报」的结论**，
 * 不必再人工翻表。判定口径全部复用 eligibility，保证与表格列的 ✅/❌/⚠️ 完全一致。
 */
import type { Job, Profile } from '../types';
import { inTargetCity } from './filter';
import { judgeJob, scanRisks, type EligibilityStatus } from './eligibility';
import { estimateCompetition, hardGates, recommendStar, type CompetitionResult } from './competition';
import { estimateSalary, yearsForHousing, type CitySalary } from './salary';

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
}

export interface SelectionReport {
  /** 参与判定的岗位数（已按目标城市收窄；未填目标城市则为全量） */
  total: number;
  pass: number;
  fail: number;
  warn: number;
  /** 是否符合条件（有 fail 即不符） */
  cityStats: RegionStat[];
  /** 符合岗位最多的工作地点（全量降序，用于发现计划外的好去处） */
  topRegions: RegionStat[];
  /** 淘汰原因分布（按维度计次） */
  failReasons: CountStat[];
  /** 符合岗位里的风险提示分布（服务年限 / 英语 / 体测…） */
  riskTags: CountStat[];
  /** 符合条件的岗位（已按地点 + 单位排序） */
  candidates: Job[];
  /** 综合排序（推荐指数降序；含无门槛的排在前） */
  ranked: RankedCandidate[];
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

/**
 * 生成选岗分析报告。
 * @param jobs 全量岗位（不做轮次/标记过滤，报告是"这份表能报什么"的全景）
 * @param profile 考生画像（含 targetCities）
 */
export function buildSelectionReport(jobs: Job[], profile: Profile): SelectionReport {
  const cities = profile.targetCities ?? [];
  const scope = cities.length ? jobs.filter((j) => inTargetCity(j.region, cities)) : jobs.slice();

  const failMap = new Map<string, number>();
  const riskMap = new Map<string, number>();
  const regionAgg = new Map<string, RegionStat>();
  const statusByKey = new Map<string, EligibilityStatus>();
  const candidates: Job[] = [];
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
      candidates.push(j);
      scanRisks(j).forEach((t) => bump(riskMap, t));
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
      const salary = estimateSalary(job.region);
      const years = yearsForHousing(salary);
      const gates = hardGates(job).filter((g) => g !== '性别限制');
      return {
        job,
        comp,
        salary,
        yearsForHousing: years,
        star: recommendStar(years, comp.score, job.hires),
        gates,
      };
    })
    .sort(
      (a, b) =>
        (a.gates.length ? 1 : 0) - (b.gates.length ? 1 : 0) ||
        b.star - a.star ||
        a.yearsForHousing - b.yearsForHousing ||
        a.comp.score - b.comp.score,
    );

  return {
    total: scope.length,
    pass,
    fail,
    warn,
    cityStats,
    topRegions,
    failReasons: topStats(failMap),
    riskTags: topStats(riskMap),
    candidates,
    ranked,
  };
}
