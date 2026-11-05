#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""salary_by_unit.py —— 按「岗位所在单位」批量算薪资（单位预算/决算 → 反推人数 → 人均）

这是对用户诉求「去根据单位的预算来」的端到端落地：
    1. 读可报岗位筛选表，取每个岗位的 (考区, 招考单位)
    2. 判断单位属于哪个站点（市级 / 县级 / 区级），匹配 unit_budget.SITES
    3. 已配置站点的单位 → 抓该单位决算 → 工资福利支出(分子)
       → 抽不到人数就用公积金/社保反推(分母) → 人均人力成本 / 应发 / 到手含公积金
    4. 站点未配置的单位 → 如实标注「未取得：需配 X 站点」，绝不拿考区档位冒充

用法
----
    python3 scripts/salary_by_unit.py 可报岗位筛选表.xlsx -o 单位级薪资.xlsx
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unit_budget as UB

# 广东县级市（含"市"字，容易误判为地级市 → 显式列出，其余地级市在 UB.SITES）
_COUNTY_CITY = {
    "雷州市", "吴川市", "廉江市", "陆丰市", "兴宁市", "罗定市", "高州市",
    "化州市", "信宜市", "台山市", "开平市", "恩平市", "鹤山市", "乐昌市",
    "南雄市", "英德市", "连州市", "四会市", "普宁市", "阳春市",
}


def classify(qu: str, unit: str) -> tuple[str, str]:
    """把单位分到站点，返回 (站点名 or "", 说明)。

    规则：单位名里第一个「X县 / X区 / 县级市」即县级站点；
    否则取「X市」前缀作市级站点。站点未配置时返回空串 + 说明。
    """
    text = unit or qu
    # 县级市优先（名字含"市"但其实是县）
    for cc in _COUNTY_CITY:
        if cc in text:
            return cc, f"县级市 {cc}（站点未配置）" if cc not in UB.SITES else ""
    # 县 / 区
    m = re.search(r"([\u4e00-\u9fa5]{2,6}[县区])", text)
    if m:
        site = m.group(1)
        return site, f"区县 {site}（站点未配置）" if site not in UB.SITES else ""
    # 地级市前缀
    m = re.search(r"([\u4e00-\u9fa5]{2,3}市)", text)
    if m:
        site = m.group(1)
        return site, f"市 {site}（站点未配置）" if site not in UB.SITES else ""
    return "", "考区/单位名无法识别站点"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", help="可报岗位筛选表")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.xlsx)
    ws = wb.active
    head = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(head) if h}
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[idx["招考单位"]]]

    out = openpyxl.Workbook()
    s1 = out.active
    s1.title = "单位级薪资"
    ext = ["站点", "单位层级", "工资福利支出(万元)", "人数(反推)",
           "人均人力成本(万/年)", "人均应发(万/年)", "到手含公积金(万/年)", "取数状态"]
    s1.append(list(head) + ext)

    # 去重缓存：同一单位只抓一次
    cache: dict[str, UB.UnitResult] = {}
    done = unconfig = failed = 0
    for r in rows:
        qu, unit = str(r[idx["考区"]]), str(r[idx["招考单位"]])
        site, why = classify(qu, unit)
        if not site or why:
            s1.append(list(r) + ["", "", "", "", "", "", "", f"未取得：{why}"])
            unconfig += 1
            continue
        if unit not in cache:
            cache[unit] = UB.analyze_unit(site, unit, "决算")
        ur = cache[unit]
        if ur.wage_wan is None:
            s1.append(list(r) + [site, "", "", "", "", "", "", f"抓取失败：{ur.note}"])
            failed += 1
            continue
        done += 1
        hc = (f"{ur.headcount}" if ur.headcount
              else f"{ur.hc_low:,.0f}~{ur.hc_high:,.0f}" if ur.hc_low else "—")
        rng = lambda lo, hi: (f"{lo:.1f}~{hi:.1f}" if (lo and abs(hi - lo) > 0.05) else
                              (f"{lo:.1f}" if lo else "—"))
        flag = "直接取到人数" if ur.headcount else ("反推不可信" if not ur.overlap else "反推")
        s1.append(list(r) + [site, "市级" if not re.search(r"[县区]", unit) else "区县",
                             round(ur.wage_wan, 2), hc,
                             rng(ur.per_capita_wan_low, ur.per_capita_wan_high),
                             rng(ur.salary_wan_low, ur.salary_wan_high),
                             rng(ur.net_wan_low, ur.net_wan_high), flag])

    # 样式
    for i, w in enumerate([9, 10, 10, 16, 12, 16, 14, 16, 12], 1):
        s1.column_dimensions[openpyxl.utils.get_column_letter(i + len(head) - len(ext) + 1)].width = w
    for c in s1[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5597")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    s1.freeze_panes = "B2"

    # 汇总页
    s2 = out.create_sheet("汇总")
    s2.append(["项目", "数量"])
    total = len(rows)
    s2.append(["可报岗位总数", total])
    s2.append(["已用单位决算算出薪资", done])
    s2.append(["站点未配置（县/区/县级市）", unconfig])
    s2.append(["抓取失败", failed])
    s2.append(["备注", "县级单位需逐一配置各县政府门户决算栏目；已配置："
               + "、".join(UB.SITES)])

    out.save(a.out)
    print(f"岗位 {total}：已算 {done}，站点未配置 {unconfig}，抓取失败 {failed}")
    print(f"已写出：{a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
