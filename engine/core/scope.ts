/**
 * 范围外提示（防「池内最优」陷阱）
 *
 * 背景（2026-11-04 的真实漏项）：当天只扫了广州、深圳 → 漏掉中山两个更优岗。
 * 这是选岗里最隐蔽的一类错误：**候选池内部的最优解，不等于全局最优解**。
 * 范围一旦定死，重大漏项一定在范围外。
 *
 * 因此本模块做成报告末尾**强制**输出的一节：即使结论很好，也要提醒"你没看哪一块"。
 *
 * 注意：本节**不得虚构范围外岗位的具体数量或竞争比**——那些数字需要重新抓取。
 * 缺统计时只给方向性描述并明确"需重新抓取"。
 */

export interface ScopeContext {
  /** 本次分析的目标城市 */
  cities: string[];
  /** 范围内岗位数 */
  inScopeTotal: number;
  /** 距离最近的可扩展区域名称（如「珠三角」） */
  adjacentRegions?: string[];
  /** 范围外已知的同类岗位（可选；缺失时不虚构） */
  outsideCandidates?: Array<{ region: string; note: string }>;
  /** 是否已做全量分析（未限定城市） */
  fullScan?: boolean;
}

/**
 * 渲染「范围外提示」Markdown 小节。
 *
 * 三种情形：
 * 1. 未限定城市（全量分析）→ 明确说明无范围外缺口；
 * 2. 限定了城市且有范围外统计 → 列出区域与说明，并提示需重新抓报录比；
 * 3. 限定了城市但无统计 → 只给方向性描述 + 需重新抓取，不编造数字。
 */
export function renderScopeNotice(ctx: ScopeContext): string {
  const out: string[] = [];
  out.push('## ⚠️ 范围外提示');
  out.push('');

  const cities = (ctx.cities ?? []).filter(Boolean);
  if (ctx.fullScan || !cities.length) {
    out.push(
      `本次为**全量分析**（未限定城市），纳入 ${ctx.inScopeTotal} 个岗位，不存在"范围外漏项"问题。`,
    );
    out.push('');
    out.push('> 提醒：全量分析时，范围不再是风险，但**数据完整性**仍是——缺报名人数的岗位不参与概率排序。');
    return out.join('\n');
  }

  out.push(
    `本次分析范围：**${cities.join('、')}**（共 ${ctx.inScopeTotal} 个岗位）。`,
  );
  out.push('');

  const outside = ctx.outsideCandidates ?? [];
  if (outside.length) {
    out.push('范围外还有：');
    out.push('');
    for (const item of outside) {
      out.push(`- ${item.region}：${item.note}`);
    }
    out.push('');
    out.push('> 是否纳入？纳入需**重新抓取**报名人数与进面分，现有结论不能直接外推。');
  } else {
    const adjacent = (ctx.adjacentRegions ?? []).filter(Boolean);
    if (adjacent.length) {
      out.push(`范围外相邻区域（${adjacent.join('、')}）**尚未统计**，因此无法判断是否藏着更优岗。`);
    } else {
      out.push('范围外同类岗位**尚未统计**，无法判断是否藏着更优岗。');
    }
    out.push('');
    out.push(
      '> 结论只对上述范围内的岗位成立。要扩展到范围外，需**重新抓取**对应地区的职位表、报名人数与进面分；' +
        '本报告不提供范围外岗位的任何数字（缺失即不写，不用估算填充）。',
    );
  }

  return out.join('\n');
}
