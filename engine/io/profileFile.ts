/**
 * 考生画像文件解析（assets/profile.md）
 *
 * 为什么需要：REQ-012 要求 profile.md 新增的 5 个字段「能被 CLI 读取」。
 * 只在文档里加字段、实现里没有读取入口，等于文档撒谎——用户填了不会生效。
 *
 * 输入：Markdown 表格（`| 项 | 值 | 说明 |`），刻意保持人工可读可编辑，
 *      不改成 JSON/YAML，因为这份文件是给人填的，格式越简单越不容易填错。
 *
 * 输出：结构化 Profile 扩展字段。**无法识别的项一律跳过**（不猜），
 *      需要在报告"待核"里提示的项由调用方决定。
 */

import { readFileSync } from 'node:fs';
import type { Profile } from '../types';

/** profile.md 中新增的可配置项（对应 SKILL §二 与 PRJ-2026-022 REQ-012） */
export interface ProfileExtras {
  /** 接受值班/夜间/轮班（否 → 判 heavy 排除） */
  acceptDuty: boolean | null;
  /** 接受应急/三防/消防/救援 */
  acceptEmergency: boolean | null;
  /** 接受执法勤务/一线/处突 */
  acceptEnforce: boolean | null;
  /** 接受信访/接访/维稳 */
  acceptPetition: boolean | null;
  /** 接受外派/常驻/出差 */
  acceptTravel: boolean | null;
  /** 接受 5 年最低服务期（否 → 乡镇机关岗位排除） */
  acceptServiceBond: boolean | null;
  /** 排除哪些区（如「越秀」） */
  excludeDistricts: string[];
  /** 可接受最低年薪（万元，年全包口径） */
  minAnnualPackage: number | null;
  /** 未能识别的行（报告待核用） */
  unparsed: Array<{ key: string; value: string; reason: string }>;
}

export function emptyProfileExtras(): ProfileExtras {
  return {
    acceptDuty: null,
    acceptEmergency: null,
    acceptEnforce: null,
    acceptPetition: null,
    acceptTravel: null,
    acceptServiceBond: null,
    excludeDistricts: [],
    minAnnualPackage: null,
    unparsed: [],
  };
}

/**
 * 占位符判定：画像模板用「—」「-」「／」「/」「无」「不限」表示"未填"。
 *
 * 这些值不能被当成真实取值。典型错误：把「目标城市 = —」解析成城市名「—」，
 * 结果 targetCities=['—']，过滤器把全部岗位排除，纳入判定 0 个
 * （用户明明只是还没填）。
 */
const PLACEHOLDER_VALUES = new Set([
  '—', '–', '-', '－', '／', '/', '\\', '无', '不限', '未填', '空', 'N/A', 'n/a', 'NA', 'tbd', 'TBD',
]);

export function isPlaceholder(value: string): boolean {
  const s = String(value ?? '').trim().replace(/\*\*/g, '');
  if (!s) return true;
  if (PLACEHOLDER_VALUES.has(s)) return true;
  // 「——」「--」「...」这类重复占位符也算未填
  return /^[—–\-－/／.。…\s]+$/.test(s);
}

/** 按分隔符切成有效取值列表（自动剔除占位符） */
export function splitValues(value: string): string[] {
  if (isPlaceholder(value)) return [];
  return String(value)
    .split(/[,，、;；/／\s]+/)
    .map((s) => s.trim())
    .filter((s) => s && !isPlaceholder(s));
}

/** 把「是/否/接受/不接受/—/空」归一化成三态布尔 */
function triState(raw: string): boolean | null {
  const s = String(raw ?? '').trim();
  if (isPlaceholder(s)) return null;
  if (/^(是|接受|可以|能|乐意)$/.test(s)) return true;
  if (/^(否|不接受|不可以|不能|不要|拒绝)$/.test(s)) return false;
  // 「接受但要看情况」这类模糊回答不猜，交给人工
  return null;
}

/** 从一行表格里抽出单元格 */
function cells(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.startsWith('|')) return [];
  return trimmed
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((s) => s.trim());
}

/**
 * 解析 profile.md 全文。
 *
 * 只认「表格行的第 1 列是已知项名」的形式；其余行（正文、示例）忽略。
 * 这样用户可以自由增删说明文字而不破坏解析。
 */
export function parseProfileMarkdown(text: string): { profile: Partial<Profile>; extras: ProfileExtras } {
  const extras = emptyProfileExtras();
  const profile: Partial<Profile> = {};

  for (const line of text.split(/\r?\n/)) {
    const cols = cells(line);
    if (cols.length < 2) continue;
    const key = cols[0].replace(/\*\*/g, '').trim();
    const value = cols[1].replace(/\*\*/g, '').trim();
    if (!key || /^-+$/.test(key)) continue;

    switch (true) {
      case /接受值班|值班|夜间|轮班/.test(key):
        extras.acceptDuty = triState(value);
        break;
      case /接受应急|三防|消防|救援/.test(key):
        extras.acceptEmergency = triState(value);
        break;
      case /接受执法|执法勤务|一线|处突/.test(key):
        extras.acceptEnforce = triState(value);
        break;
      case /接受信访|信访|接访|维稳/.test(key):
        extras.acceptPetition = triState(value);
        break;
      case /接受外派|常驻|出差/.test(key):
        extras.acceptTravel = triState(value);
        break;
      case /接受.*服务期|5 年最低服务期|最低服务期/.test(key):
        extras.acceptServiceBond = triState(value);
        break;
      case /排除.*区/.test(key):
        extras.excludeDistricts = splitValues(value);
        break;
      case /最低年薪|可接受最低年薪/.test(key): {
        const match = value.match(/(\d+(?:\.\d+)?)/);
        if (match) {
          extras.minAnnualPackage = Number(match[1]);
        } else if (value && !/^(—|-|\/|无)$/.test(value)) {
          extras.unparsed.push({ key, value, reason: '年薪需为数值（万元）' });
        }
        break;
      }
      // ── 既有硬条件字段（保持可读）──
      case /^学历$/.test(key):
        if (!isPlaceholder(value)) profile.degree = value as Profile['degree'];
        break;
      case /专业（主修）|专业\(主修\)|^专业$/.test(key):
        if (!isPlaceholder(value)) profile.major = value;
        break;
      case /专业大类/.test(key): {
        const categories = splitValues(value);
        if (categories.length) profile.majorCategory = categories[0];
        break;
      }
      case /政治面貌/.test(key):
        profile.politicalStatus = /党员/.test(value)
          ? 'party'
          : /团员/.test(value)
            ? 'league'
            : 'none';
        break;
      case /基层工作经历|基层经历/.test(key): {
        const match = value.match(/(\d+)/);
        profile.grassrootsYears = match ? Number(match[1]) : null;
        break;
      }
      case /法律职业资格/.test(key):
        profile.hasLegalCert = !/^(无|没有|否)$/.test(value);
        break;
      case /应届身份/.test(key): {
        const state = triState(value);
        if (state != null) profile.fresh = state;
        break;
      }
      case /目标城市/.test(key): {
        const cities = splitValues(value);
        if (cities.length) profile.targetCities = cities;
        break;
      }
      default:
        break;
    }
  }

  return { profile, extras };
}

/** 读取 profile.md 文件；文件不存在返回空结果（不抛错，便于画像可选） */
export function loadProfileFile(path: string): {
  profile: Partial<Profile>;
  extras: ProfileExtras;
  found: boolean;
} {
  try {
    const text = readFileSync(path, 'utf-8');
    const parsed = parseProfileMarkdown(text);
    return { ...parsed, found: true };
  } catch {
    return { profile: {}, extras: emptyProfileExtras(), found: false };
  }
}
