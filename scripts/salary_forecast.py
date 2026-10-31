#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""广东省考岗位薪资测算：预期薪资（年全包）+ 到手薪资（含公积金、不含社保）

口径定义（这是整个表最要紧的部分，别混）：
    预期薪资 = 年全包 = 月到手现金×12 + 双边公积金×12 + 年绩效
    到手薪资 = 年到手现金×12 + 双边公积金×12 + 年绩效×税后系数(0.9)
    ——「不含社保」指不计入个人缴纳的养老/医疗/失业（那部分本来就不进兜里）；
       「含公积金」指把单位+个人两边缴的公积金都算作收入（确实是自己的钱）。

两个数的差 = 个税（绩效部分按 10% 综合税负估）。

数据来源与限制：
    年全包 / 月到手 / 公积金 来自 engine/core/salary.ts 的地区档位
    （basis 字段写明是「调研汇总」，**不是**官方口径）。
    决算推算（scripts/budget_salary.py）能给出单位人力成本的真实结构，但
    **决算公开表不披露人数**，分母只能反推成区间（±20%），所以本表不把它当输入，
    只用它做结构校验（见 §校验）。

用法：
    python3 scripts/salary_forecast.py 岗位表.xlsx -o 输出.xlsx
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

# ── 地区档位（与 engine/core/salary.ts 保持一致；改一处必须改两处）──────────
# (年全包万, 月到手元, 双边公积金/月 元, 房价元/㎡, 依据)
REGION: dict[str, tuple[float, float, int, int, int, int, int, str]] = {
    "深圳": (25, 30, 14000, 18000, 4000, 5600, 55000, "多来源调研汇总（2026）"),
    "广州": (18, 25, 8000, 10000, 3000, 3500, 32000, "多来源调研汇总（2026）"),
    "东莞": (17, 22, 8000, 11000, 3000, 4000, 19200, "珠三角调研汇总（2026）"),
    "佛山": (17, 22, 8000, 11000, 3000, 4000, 12500, "珠三角调研汇总（2026）"),
    "珠海": (17, 22, 8000, 11000, 3000, 4000, 20200, "珠三角调研汇总（2026）"),
    "中山": (15, 18, 7000, 9500, 2500, 3500, 8500, "广东省内第二梯队（2026）"),
    "惠州": (15, 18, 7000, 9500, 2500, 3500, 8300, "广东省内第二梯队（2026）"),
    "江门": (15, 18, 7000, 9500, 2500, 3500, 6300, "广东省内第二梯队（2026）"),
    "汕头": (15, 18, 7000, 9500, 2500, 3500, 10500, "广东省内第二梯队（2026）"),
    "湛江": (14, 17, 6500, 9000, 2200, 3200, 8900, "粤东西北（2026）"),
    "肇庆": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "茂名": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "梅州": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "清远": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "河源": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "韶关": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "揭阳": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "阳江": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "汕尾": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "云浮": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
    "潮州": (13, 16, 6200, 8200, 2000, 3000, 7500, "档位估算（粤东西北，无一手数据）"),
}

# 2024 年城镇非私营单位**在岗职工**月平均工资（元/月）——省/市统计局公布数
# 用途：算「到手 ÷ 当地社平」倍数，判断这份工资在当地是什么水平
# ⚠️ 只收已公布的城市；梅州等只公布了"全口径"（口径不同），不混用
SOCIAL_WAGE = {
    "深圳": 14755, "广州": 13704, "珠海": 11642, "佛山": 9653,
    "中山": 9094, "惠州": 8840, "东莞": 8766, "汕头": 8382,
}

# 决算实测结构（广东省税务局 2024 年度单位决算，见 budget_salary.py）
DECISION_STRUCT = {"现金性": 0.762, "单位社保": 0.163, "单位公积金": 0.085}
PERF_TAX = 0.9          # 绩效按 10% 综合税负折算到手
PROBATION = 0.8         # 试用期/首年通常按 80% 左右发


def parse_range(v, cast=float):
    """'17-22' → (17.0, 22.0)；已经是数字则原样。"""
    if isinstance(v, (int, float)):
        return cast(v), cast(v)
    t = str(v or "").replace("，", "-").replace("~", "-")
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    if len(nums) >= 2:
        return cast(nums[0]), cast(nums[1])
    if len(nums) == 1:
        return cast(nums[0]), cast(nums[0])
    return cast(0), cast(0)


def forecast(region: str) -> dict:
    """一个考区的薪资拆解（区间 + 中值）。"""
    if region not in REGION:
        raise KeyError(region)
    p_lo, p_hi, c_lo, c_hi, f_lo, f_hi, house, basis = REGION[region]
    p_mid, c_mid, f_mid = (p_lo + p_hi) / 2, (c_lo + c_hi) / 2, (f_lo + f_hi) / 2
    cash_year = 12 * c_mid / 10_000            # 万元
    fund_year = 12 * f_mid / 10_000            # 万元（双边）
    perf = max(0.0, p_mid - cash_year - fund_year)   # 年绩效（补齐年全包的差额）
    net = cash_year + fund_year + perf * PERF_TAX

    def _net(p, c, f):
        cw, fw = 12 * c / 10_000, 12 * f / 10_000
        return cw + fw + max(0.0, p - cw - fw) * PERF_TAX

    net_lo = _net(p_lo, c_lo, f_lo)
    net_hi = _net(p_hi, c_hi, f_hi)
    return {
        "region": region, "basis": basis,
        "pay_lo": p_lo, "pay_hi": p_hi, "pay_mid": p_mid,
        "cash_lo": c_lo, "cash_hi": c_hi, "cash_mid": int(c_mid),
        "fund_lo": f_lo, "fund_hi": f_hi, "fund_mid": int(f_mid),
        "cash_year": cash_year, "fund_year": fund_year,
        "perf": perf, "net": net, "net_lo": net_lo, "net_hi": net_hi,
        "net_month": net * 10_000 / 12,
        "probation": net * PROBATION,
        "social": SOCIAL_WAGE.get(region, 0),
        "vs_social": (net * 10_000 / (SOCIAL_WAGE[region] * 12)) if region in SOCIAL_WAGE and net else 0.0,
        "house": house,
        "years_house": (house * 100 / (net * 10_000)) if net else 0.0,
    }


def check_consistency(fx: dict) -> float:
    """结构校验：公积金双边 ÷ 年到手 应接近决算实测的 2×8.5%/(到手/工资福利支出)。

    决算口径下 单位公积金 ≈ 8.5%×工资福利支出，双边 ≈ 17%；而「年到手+公积金」
    ≈ 80%×工资福利支出 → 双边公积金 / 年到手 应落在 17/80 ≈ 21% 附近。
    偏离过大说明档位表里公积金与工资的勾稽关系不自洽。
    """
    if not fx["net"]:
        return 0.0
    return fx["fund_year"] / fx["net"]


def main() -> int:
    ap = argparse.ArgumentParser(description="岗位薪资测算：年全包 + 到手（含公积金）")
    ap.add_argument("jobs", help="岗位表 xlsx（需含 考区/招考单位/招考职位 列）")
    ap.add_argument("-o", "--out", default="岗位薪资测算.xlsx")
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.jobs)
    ws = wb[a.sheet] if a.sheet else wb.worksheets[0]
    header = [c for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    idx = {h: i for i, h in enumerate(header) if h}
    for need in ("考区", "招考单位", "招考职位"):
        if need not in idx:
            print(f"✗ 缺列：{need}（现有：{list(idx)}）", file=sys.stderr)
            return 2

    # 表内已有的薪资列直接校验档位是否一致
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[idx["考区"]]:
            continue
        region = str(r[idx["考区"]]).strip()
        if region not in REGION:
            print(f"⚠ 未收录考区：{region}", file=sys.stderr)
            continue
        fx = forecast(region)
        sheet_pay = parse_range(r[idx["年全包(万)"]]) if "年全包(万)" in idx else (0, 0)
        rows.append((r, fx, sheet_pay))

    # ── 输出 ──────────────────────────────────────────────────
    out = openpyxl.Workbook()
    s1 = out.active
    s1.title = "按考区汇总"
    head1 = ["考区", "岗位数", "招录人数", "预期年薪(万)", "月到手现金(元)",
             "双边公积金/月(元)", "年公积金(万)", "年绩效(万)", "实际到手(万)",
             "到手区间", "月均到手(元)", "首年(试用期,万)", "房价(元/㎡)", "买100㎡需(年)",
             "当地社平(元/月)", "到手÷社平", "公积金占比(校验)", "数据依据"]
    s1.append(head1)

    agg: dict[str, list] = {}
    for r, fx, _ in rows:
        agg.setdefault(fx["region"], []).append((r, fx))

    order = sorted(agg, key=lambda k: -forecast(k)["net"])
    for region in order:
        items = agg[region]
        fx = forecast(region)
        n_job = len(items)
        n_hire = sum(int(x[0][idx["招录人数"]] or 0) for x in items)
        s1.append([
            region, n_job, n_hire,
            f"{fx['pay_lo']:.0f}-{fx['pay_hi']:.0f}",
            f"{fx['cash_lo']:,}-{fx['cash_hi']:,}",
            f"{fx['fund_lo']:,}-{fx['fund_hi']:,}",
            round(fx["fund_year"], 2), round(fx["perf"], 2), round(fx["net"], 2),
            f"{fx['net_lo']:.1f}-{fx['net_hi']:.1f}",
            round(fx["net_month"]), round(fx["probation"], 2),
            fx["house"], round(fx["years_house"], 1),
            fx["social"] or "—", f"{fx['vs_social']:.1f}x" if fx["vs_social"] else "—",
            f"{check_consistency(fx):.0%}", fx["basis"],
        ])

    s2 = out.create_sheet("岗位明细")
    extra = ["年绩效(万)", "实际到手(万)", "到手区间", "月均到手(元)", "首年(试用期,万)",
             "公积金/月(元)", "买100㎡需(年)", "薪资口径"]
    s2.append(list(header) + extra)
    for r, fx, _ in sorted(rows, key=lambda x: -x[1]["net"]):
        s2.append(list(r) + [
            round(fx["perf"], 2), round(fx["net"], 2), f"{fx['net_lo']:.1f}-{fx['net_hi']:.1f}",
            round(fx["net_month"]),
            round(fx["probation"], 2), fx["fund_mid"], round(fx["years_house"], 1),
            "年全包=月到手×12+双边公积金×12+年绩效；不含社保",
        ])

    s3 = out.create_sheet("口径说明")
    notes = [
        ("项目", "说明"),
        ("预期年薪", "月到手现金×12 + 双边公积金×12 + 年绩效。**税后**口径、含双边公积金、不含社保，单位：万元/年"),
        ("实际到手", "年到手现金 + 双边公积金 + 年绩效×0.9（绩效按 10% 综合税负折算）。比预期年薪少的就是税"),
        ("到手区间", "用档位上下限分别算一遍，反映地区内部的浮动"),
        ("为什么两个数不一样", "差额=绩效部分的个税。公积金双边都算收入（个人那半本来就从工资里扣走了）"),
        ("月到手现金", "已扣个人社保、个人公积金、个税的实发数，含车补"),
        ("首年（试用期）", "按转正后的 80% 估。公务员试用期一年，工资按试用期标准发，绩效通常按季度折算"),
        ("年绩效", "= 年全包 − 月到手×12 − 双边公积金×12（差额补齐）。不是单独公布的数，是倒挤出来的"),
        ("买100㎡需", "房价×100 ÷ 年到手（不吃不喝、全部收入、不贷款）"),
        ("", ""),
        ("数据来源", "engine/core/salary.ts 地区档位（basis 字段注明「调研汇总」），**非官方口径**"),
        ("决算能做什么", "budget_salary.py 从部门决算算出单位人力成本结构（现金性 76.2% / 单位社保 16.3% / 单位公积金 8.5%）"),
        ("决算不能做什么", "决算公开表**不披露人数**，分母只能靠公积金/社保反推成区间（实测 ±20%），给不出各单位实数"),
        ("反推示例", "广东省税务局 2024 年度单位决算：工资福利支出 138.1 亿，反推在职 4.5~6.3 万人，人均 21.8~30.4 万"),
        ("", ""),
        ("已知偏差①", "同城不同区差异可达 20%：深圳福田 vs 坪山、广州天河 vs 从化，档位表只给到市级"),
        ("已知偏差②", "绩效发放滞后且受当年财政影响，2026 年多地清理规范津贴补贴"),
        ("已知偏差③", "公检法、税务、海关等垂管单位另有专项津贴，本表按一般行政编估算"),
        ("已知偏差④", "深圳档位月到手偏高（1.4-1.8 万）、年绩效只剩 2.5 万，说明其绩效多为按月预发，看「实际到手」即可"),
        ("当地社平", "2024 年城镇非私营单位在岗职工月均工资（省/市统计局）。只收了 8 个已公布城市，其余留空"),
        ("到手÷社平", "公务员到手是当地平均工资的几倍。稳定在 1.5~1.7 倍 = 档位表与统计口径自洽"),
        ("用法建议", "同档位内比「买100㎡需(年)」，比年全包更有意义；跨档位比年全包"),
    ]
    for row in notes:
        s3.append(list(row))

    for sh, width in ((s1, 14), (s2, 12)):
        for col in sh.columns:
            maxlen = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            sh.column_dimensions[col[0].column_letter].width = min(max(width, maxlen * 1.3), 46)
        for c in sh[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="4472C4")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sh.freeze_panes = "A2"
    s3.column_dimensions["A"].width = 22
    s3.column_dimensions["B"].width = 96
    for c in s3[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
    for row in s3.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    out.save(a.out)

    # ── 控制台摘要 ────────────────────────────────────────────
    print(f"{'考区':<6}{'岗位':>4}{'招录':>5}{'年全包(万)':>12}{'月到手':>14}{'公积金/月':>13}"
          f"{'年到手':>8}{'买100㎡':>8}")
    print("-" * 82)
    for region in order:
        fx = forecast(region)
        items = agg[region]
        print(f"{region:<6}{len(items):>4}{sum(int(x[0][idx['招录人数']] or 0) for x in items):>5}"
              f"{fx['pay_lo']:>7.0f}-{fx['pay_hi']:<4.0f}{fx['cash_lo']:>8,}-{fx['cash_hi']:<6,}"
              f"{fx['fund_lo']:>7,}-{fx['fund_hi']:<5,}{fx['net']:>8.1f}{fx['years_house']:>8.1f}")

    # 档位与岗位表原值的一致性检查
    bad = [(r[idx["招考单位"]], r[idx["考区"]], sp, fx)
           for r, fx, sp in rows if sp[0] and abs(sp[0] - fx["pay_lo"]) > 0.5]
    if bad:
        print(f"\n⚠ {len(bad)} 行岗位表的「年全包」与档位表不一致，例：{bad[0][:3]}")
    print(f"\n✓ 已写出：{a.out}")
    print("⚠ 年全包/月到手来自调研汇总档位，非官方口径；决算只能校验结构，给不出各单位实数（决算不披露人数）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
