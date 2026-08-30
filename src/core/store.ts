/**
 * 持久化（05 §4.8 契约；@shared/core db.ts 封装，组装/拆解映射层）
 * - 元数据 8 KV 存 settings 表；jobs 每岗位一条 FormRecord 存 records 表
 * - configureDB/setCurrentAccountId 走 '@shared/core/services/db' 子路径导入（主入口未导出，04 §4.1）
 */
import {
  clearAllData,
  configureDB,
  deleteRecords,
  getAllRecords,
  getSetting,
  putRecord,
  setCurrentAccountId,
  setSetting,
} from '@shared/core/services/db';
import type { FormRecord } from '@shared/core';
import {
  DEFAULT_ROUNDS,
  emptyProfile,
  type AppState,
  type Job,
  type Mapping,
  type Profile,
  type RawTable,
  type Result,
} from '../types';
import { err, ok } from '../types';

export const SCHEMA_VERSION = 1;
const DB_PREFIX = 'job-picker-app';
const ACCOUNT = 'local';

/** 应用启动调用一次（main.tsx）：固定内置账户初始化 */
export function initDB(): void {
  configureDB(DB_PREFIX);
  setCurrentAccountId(ACCOUNT);
}

/* ---------- Job ↔ FormRecord 映射 ---------- */

function jobToRecord(j: Job, now: string): FormRecord {
  return {
    id: j.code,
    templateId: 'job',
    title: j.unit,
    data: {
      unit: j.unit,
      title: j.title,
      avgIncome: j.avgIncome,
      netIncome: j.netIncome,
      incomeScore: j.incomeScore,
      netScore: j.netScore,
      applicants: j.applicants,
      hires: j.hires,
      region: j.region,
      degree: j.degree,
      major: j.major,
      intro: j.intro,
      remark: j.remark,
      marks: j.marks,
    },
    status: 'completed',
    createdAt: now,
    updatedAt: now,
  };
}

function recordToJob(r: FormRecord): Job | null {
  const d = r.data as Record<string, unknown>;
  if (typeof r.id !== 'string' || typeof d.unit !== 'string') return null;
  const marks = Array.isArray(d.marks) ? (d.marks as Job['marks']) : [];
  return {
    code: r.id,
    unit: d.unit,
    title: String(d.title ?? ''),
    avgIncome: (d.avgIncome as number | null) ?? null,
    netIncome: (d.netIncome as number | null) ?? null,
    incomeScore: (d.incomeScore as number | null) ?? null,
    netScore: (d.netScore as number | null) ?? null,
    applicants: (d.applicants as number | null) ?? null,
    hires: (d.hires as number | null) ?? null,
    region: String(d.region ?? ''),
    degree: String(d.degree ?? ''),
    major: String(d.major ?? ''),
    intro: String(d.intro ?? ''),
    remark: String(d.remark ?? ''),
    marks,
  };
}

/* ---------- 读取与迁移（§3.10） ---------- */

/**
 * 读取并迁移；结构非法 → E_STORAGE_PARSE（调用方按空状态冷启动，不崩溃 F-10 规则 4）
 * 返回值用于启动路由决策：有数据 → '/'，无数据 → '/welcome'
 */
export async function loadState(): Promise<Result<AppState | null>> {
  try {
    const schemaVersion = await getSetting<number | null>('schemaVersion', null);
    if (schemaVersion == null) return ok(null); // 空库（首次使用/已清空）

    const source = await getSetting<'demo' | 'file'>('source', 'file');
    const importedAt = await getSetting<string>('importedAt', new Date().toISOString());
    const raw = await getSetting<RawTable | null>('raw', null);
    const mapping = await getSetting<Mapping | null>('mapping', null);
    const remarkCols = await getSetting<number[] | null>('remarkCols', null);
    const rounds = await getSetting<string[] | null>('rounds', null);
    const profile = await getSetting<Profile | null>('profile', null);

    if (!raw || !mapping || !rounds) {
      // 缺必要 KV：结构非法，冷启动
      return err('E_STORAGE_PARSE', '本地数据结构异常，已按空状态启动（可重新导入）');
    }

    const records = await getAllRecords();
    const jobs: Job[] = [];
    records.forEach((r) => {
      if (r.templateId !== 'job') return;
      const j = recordToJob(r);
      if (j) jobs.push(j);
    });

    // 只增字段不删迁移（无 schemaVersion 或 < 当前版本；> 当前版本忽略未知字段只读已知）
    const migrated = schemaVersion !== SCHEMA_VERSION;
    const roundsFinal = Array.isArray(rounds) && rounds.length ? rounds : DEFAULT_ROUNDS.slice();
    const state: AppState = {
      schemaVersion: SCHEMA_VERSION,
      source,
      importedAt,
      raw,
      mapping,
      remarkCols: Array.isArray(remarkCols) ? remarkCols : [],
      rounds: roundsFinal,
      profile:
        profile && typeof profile === 'object' && Array.isArray(profile.regions)
          ? profile
          : emptyProfile(),
      jobs: jobs.map((j) => ({
        ...j,
        // marks 长度 < rounds 长度时补 'pending'
        marks: Array.from({ length: roundsFinal.length }, (_, r) => j.marks[r] ?? 'pending'),
      })),
    };

    if (migrated) {
      await saveState(state); // 迁移后立即回写（保留用户数据）
    }
    return ok(state);
  } catch {
    return err('E_STORAGE_PARSE', '本地数据读取失败，已按空状态启动（可重新导入）');
  }
}

/* ---------- 写入（拆分映射 + 差集清理） ---------- */

/**
 * 拆分写入：元数据 8 项逐 KV setSetting；jobs 逐条 putRecord 整体覆盖；
 * 覆盖导入时旧 id 差集 deleteRecords 清除旧岗位行。
 * try/catch 全包裹 → E_STORAGE_QUOTA（隐私/无痕/禁用/配额耗尽，不静默，F-10 规则 4）
 */
export async function saveState(state: AppState): Promise<Result<null>> {
  try {
    await setSetting('schemaVersion', state.schemaVersion);
    await setSetting('source', state.source);
    await setSetting('importedAt', state.importedAt);
    await setSetting('raw', state.raw);
    await setSetting('mapping', state.mapping);
    await setSetting('remarkCols', state.remarkCols);
    await setSetting('rounds', state.rounds);
    await setSetting('profile', state.profile);

    const now = new Date().toISOString();
    const newIds = new Set(state.jobs.map((j) => j.code));
    for (const j of state.jobs) {
      await putRecord(jobToRecord(j, now));
    }
    // 差集清理：覆盖导入后不再存在的旧岗位行
    const olds = await getAllRecords();
    const staleIds = olds.filter((r) => r.templateId === 'job' && !newIds.has(r.id)).map((r) => r.id);
    if (staleIds.length) await deleteRecords(staleIds);
    return ok(null);
  } catch {
    return err('E_STORAGE_QUOTA', '存储写入失败，数据可能未保存（浏览器存储不可用或容量不足）');
  }
}

/** 清空 records + settings（F-10 规则 1；仅允许经二次确认后调用） */
export async function clearState(): Promise<void> {
  await clearAllData();
}
