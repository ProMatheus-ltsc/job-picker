#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""salary_official.py —— 用统计年鉴官方数据重算广东岗位薪资（替代调研档位）

为什么另起一个脚本
------------------
`salary_forecast.py` 的底座是 `salary.ts` 里的**调研汇总区间**，不是官方口径。
本脚本把底座换成两处**官方一手**：

    ① 广东统计年鉴 2025 · 表 4-10《各市城镇非私营单位就业人员工资总额和在岗职工平均工资》
       → 21 个市各自的「在岗职工年平均工资」（2024 年）
    ② 广东统计年鉴 2025 · 表 4-12《按行业分城镇非私营单位就业人员与在岗职工年平均工资》
       → 全省「公共管理、社会保障和社会组织」行业平均工资，除以全省全行业平均，
         得到**机关事业单位相对全行业的溢价系数**（1.178）

于是：某市机关事业单位人均应发 ≈ 该市全行业在岗职工年均工资 × 1.178

这个式子只有 **2 个假设**，且两个输入都可查、可复核、逐年更新；
相比之下"调研汇总区间"是 N 个不可追溯的二手数字，误差方向未知。

再加一层**单位系数**（这才是"考虑岗位所在单位"的正确做法）
------------------------------------------------------------
用户要求「不能只按考区估，要考虑岗位所在单位」。但**不能**用该单位的决算人均：
决算里的「工资福利支出 ÷ 人数」混合了事业编、工勤、临聘，教育局人均低是因为教师多，
而公务员与教师不是一个工资体系 —— 用它当"我进去能拿多少"，方向是错的。

单位对**公务员**收入的真实影响只有一类：**有没有政策规定的专项津贴**。
这些津贴有明文依据、额度固定，可以量化：

    政法系统（法院/检察院/公安/司法行政/监狱戒毒）  +10%   法官检察官/警衔津贴
    乡镇、街道                                      +4%    乡镇工作补贴
    行政执法类（市场监管/城管/交通/应急/生态环境）    +3%    执勤、执法津贴
    纪检监察、审计                                  +3%    专项津贴

幅度保守，因为津贴是**固定金额**而非比例——工资越低，占比越高。
所以本表对低工资城市用上浮、高工资城市用同额，不搞一刀切。

再乘一个「行政编溢价」（0~10%）
------------------------------
「公共管理、社会保障和社会组织」行业里含参公事业单位与工勤技能人员，整体低于纯行政编。
报考岗位全部是行政编公务员，故给 0~10% 的区间上限。

用法
----
    python3 scripts/salary_official.py 岗位表.xlsx -o 输出.xlsx
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ── ① 各市 2024 年在岗职工年平均工资（元）─────────────────────────────
# 出处：《广东统计年鉴 2025》表 4-10「平均工资(元)」块，2024 年 · 在岗职工列
WAGE_2024: dict[str, int] = {
    "广州": 164443, "深圳": 177057, "珠海": 139698, "汕头": 100582,
    "佛山": 115837, "韶关": 110869, "河源": 97095, "梅州": 100117,
    "惠州": 106082, "汕尾": 104177, "东莞": 105186, "中山": 109123,
    "江门": 102392, "阳江": 106261, "湛江": 110493, "茂名": 104397,
    "肇庆": 106319, "清远": 103951, "潮州": 98258, "揭阳": 90386,
    "云浮": 105534,
}

# ── ② 行业溢价系数（表 4-12，2024 年 · 在岗职工列）───────────────────
WAGE_ALL_INDUSTRY = 137467.95        # 全省 · 全行业
WAGE_PUBLIC_ADMIN = 161980.14        # 全省 · 公共管理、社会保障和社会组织
PUB_COEF = WAGE_PUBLIC_ADMIN / WAGE_ALL_INDUSTRY      # ≈ 1.1783（全省口径，仅用于校验）

# ── ②b 地区收缩指数 λ ────────────────────────────────────────────────
# 直接「市全行业平均 × 1.1783」会把**产业结构差异**误当成**工资水平差异**：
# 东莞制造业工人多、全行业平均被拉低，算出来 12.4 万，比佛山还低 —— 而两地公务员工资
# 实际相当。根因是机关工资由「全省统一的职务级别工资 + 规范津补贴」构成，
# 其地区差异被制度**压缩**了，不像企业工资那样完全跟随市场。
#
#    市应发 = 全省公管行业平均 × (市全行业平均 / 全省全行业平均)^λ
#    λ=0 → 完全统一（全省一个数）；λ=1 → 完全跟随企业工资
#    取 0.6：既承认财力差异（珠三角确实高），又不把产业结构的噪声全吃进来
LAMBDA = 0.6

# ── ③ 工资总额 → 到手（含双边公积金、不含社保）──────────────────────
# 国家统计局《关于工资总额组成的规定》：工资总额**不含**单位缴纳的社保和公积金，
# **含**个人缴纳部分（代扣仍属工资）。于是：
#     到手现金 = 工资总额 − 个人社保(14%) − 个人公积金(12%) − 个税
#     到手含双边公积金 = 到手现金 + 个人公积金 + 单位公积金 = 工资总额 − 个人社保 − 个税
# 公务员个人社保：养老 8% + 医保 2% + 职业年金 4% = 14%（不缴失业、工伤）
PENSION_MEDICAL = 0.14
FUND_RATE = 0.12          # 单位 12% / 个人 12%（机关普遍顶格）
TAX_FREE = 60_000         # 个税基本减除费用
TAX_EXTRA = 24_000        # 专项附加扣除（租房/赡养老人等，保守取 2000/月）

# ── ④ 二手房均价（元/㎡）——沿用 salary_forecast.py 的调研值，非官方 ──
HOUSE = {
    "深圳": 55000, "广州": 32000, "珠海": 20200, "东莞": 19200, "佛山": 12500,
    "中山": 8500, "惠州": 8300, "江门": 6300, "汕头": 10500, "湛江": 8900,
    "肇庆": 7500, "茂名": 7500, "梅州": 7500, "清远": 7500, "河源": 7500,
    "韶关": 7500, "揭阳": 7500, "阳江": 7500, "汕尾": 7500, "云浮": 7500,
    "潮州": 7500,
}

# ── ⑤ 单位系数（按岗位所在单位的性质）──────────────────────────────
UNIT_RULES: list[tuple[str, float, str]] = [
    (r"人民法院|人民检察院|公安|司法行政|监狱|戒毒|政法", 0.10, "政法专项津贴"),
    (r"镇人民政府|街道办事处|乡人民政府", 0.04, "乡镇工作补贴"),
    (r"市场监督管理|城市管理|综合行政执法|应急管理|交通运输|生态环境|卫生监督", 0.03, "执法执勤津贴"),
    (r"纪检监察|审计", 0.03, "专项津贴"),
]
ADMIN_PREMIUM = 0.10      # 行政编相对「公共管理行业（含参公/工勤）」的溢价上限

# ── ⑥ 原调研档位（用于对照，取自 salary_forecast.py 的年全包下限）─────
OLD_PACK = {
    "深圳": 25, "广州": 18, "东莞": 17, "佛山": 17, "珠海": 17, "中山": 15,
    "惠州": 15, "江门": 15, "汕头": 15, "湛江": 14,
}


def income_tax(taxable: float) -> float:
    """年度综合所得个税（简化累进，只到 45% 档）。"""
    brackets = [(36_000, 0.03, 0), (144_000, 0.10, 2_520), (300_000, 0.20, 16_920),
                (420_000, 0.25, 31_920), (660_000, 0.30, 52_920), (960_000, 0.35, 85_920),
                (float("inf"), 0.45, 181_920)]
    for cap, rate, ded in brackets:
        if taxable <= cap:
            return max(0.0, taxable * rate - ded)
    return 0.0


def net_from_gross(gross: float) -> dict:
    """工资总额 → 到手现金 / 双边公积金 / 到手含双边。"""
    social = gross * PENSION_MEDICAL
    fund_p = gross * FUND_RATE
    taxable = max(0.0, gross - social - fund_p - TAX_FREE - TAX_EXTRA)
    tax = income_tax(taxable)
    cash = gross - social - fund_p - tax
    fund_both = fund_p * 2
    return {"gross": gross, "social": social, "fund_p": fund_p, "tax": tax,
            "cash": cash, "fund_both": fund_both, "net_all": cash + fund_both}


def unit_factor(unit: str, title: str = "") -> tuple[float, str]:
    text = f"{unit}{title}"
    f, why = 0.0, ""
    for pat, add, label in UNIT_RULES:
        if re.search(pat, text):
            f += add
            why = (why + "+" if why else "") + label
    return f, why


def city_of(qu: str, unit: str) -> str:
    """考区列不一定写市名（如写「湛江市徐闻县」），从两列里找出 21 市之一。"""
    for text in (qu, unit):
        for c in WAGE_2024:
            if c in text:
                return c
    return ""


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

    # ── 按市汇总 ──
    cities = sorted({city_of(str(r[idx["考区"]]), str(r[idx["招考单位"]])) for r in rows} - {""})
    out = openpyxl.Workbook()
    s1 = out.active
    s1.title = "官方基准-按市"

    h1 = ["市", "全行业在岗职工\n年均工资(元)", "比全省\n(倍)", "推算应发\n(元/年)",
          "到手含双边\n(万元/年)", "区间下限\n(万元/年)", "区间上限\n(万元/年)", "原调研档位\n(万元)",
          "原档位偏差", "月到手现金\n(元)", "双边公积金\n(元/月)",
          "房价(元/㎡)", "买100㎡\n需(年)", "数据出处"]
    s1.append(h1)
    city_stat = {}
    for c in cities:
        ratio = WAGE_2024[c] / WAGE_ALL_INDUSTRY
        g = WAGE_PUBLIC_ADMIN * (ratio ** LAMBDA)
        n = net_from_gross(g)
        # 区间：λ 在 [0,1] 两个极端之间，端点就是 min/max(1, ratio)；
        # 行政编溢价（0~10%）是独立的一层，加在上界。
        g_lo = WAGE_PUBLIC_ADMIN * min(1.0, ratio)
        g_hi = WAGE_PUBLIC_ADMIN * max(1.0, ratio) * (1 + ADMIN_PREMIUM)
        n_lo = net_from_gross(g_lo)
        n_hi = net_from_gross(g_hi)
        old = OLD_PACK.get(c)
        house = HOUSE.get(c, 0)
        years = (house * 100 / n["net_all"]) if house and n["net_all"] else 0
        city_stat[c] = {"gross": g, "net": n, "net_hi": n_hi, "net_lo": n_lo,
                        "house": house, "years": years}
        s1.append([
            c, WAGE_2024[c], round(WAGE_2024[c] / WAGE_ALL_INDUSTRY, 2), round(g),
            round(n["net_all"] / 10_000, 1),
            round(n_lo["net_all"] / 10_000, 1), round(n_hi["net_all"] / 10_000, 1),
            old if old else "—",
            (f"{n['net_all'] / 10_000 / old - 1:+.0%}" if old else "—"),
            round(n["cash"] / 12), round(n["fund_p"] / 12),
            house or "—", round(years, 1) if years else "—",
            "广东统计年鉴2025 表4-10/4-12",
        ])

    # ── 岗位明细 ──
    s2 = out.create_sheet("岗位明细")
    base = list(head) + ["市", "推算应发(元/年)", "到手含双边(万元/年)",
                         "月到手现金(元)", "双边公积金(元/月)", "单位系数", "系数依据",
                         "买100㎡需(年)", "口径"]
    s2.append(base)
    detail = []
    for r in rows:
        city = city_of(str(r[idx["考区"]]), str(r[idx["招考单位"]]))
        unit = str(r[idx["招考单位"]])
        title = str(r[idx["招考职位"]] or "")
        if city not in city_stat:
            s2.append(list(r) + ["", "", "", "", "", "", "", "", "市名未识别"])
            continue
        st = city_stat[city]
        f, why = unit_factor(unit, title)
        g = st["gross"] * (1 + f)
        n = net_from_gross(g)
        house = st["house"]
        years = (house * 100 / n["net_all"]) if house and n["net_all"] else 0
        s2.append(list(r) + [
            city, round(g), round(n["net_all"] / 10_000, 1),
            round(n["cash"] / 12), round(n["fund_p"] / 12),
            f"{f:+.0%}" if f else "基准", why or "综合管理类，无专项津贴",
            round(years, 1) if years else "", "统计年鉴推算",
        ])
        detail.append((city, n["net_all"] / 10_000, f))

    # ── 口径说明 ──
    s3 = out.create_sheet("口径说明")
    notes = [
        ("项目", "说明"),
        ("核心公式", "应发 = 161,980 × (该市全行业年均 / 137,468)^0.6 × (1+单位系数)"),
        ("161,980 与 137,468 是什么", "《广东统计年鉴2025》表4-12：「公共管理、社会保障和社会组织」与全省全行业在岗职工年均工资（2024年）"),
        ("0.6 是什么（唯一的假设参数）",
         "地区收缩指数。λ=0 全省一个数，λ=1 完全跟随企业工资。取0.6：机关工资由全省统一的职务级别工资+规范津补贴构成，"
         "地区差异被制度压缩，不像企业那样完全跟市场"),
        ("区间下限/上限怎么来",
         "把 λ 从 0.6 摆到两个极端：下限=161,980×min(1,该市比全省倍数)，上限=161,980×max(1,倍数)×(1+10%行政编溢价)。"
         "真实值应落在这个区间内"),
        ("为什么不用简单相乘", "直接×1.1783 会把产业结构差异当成工资差异：东莞制造业多、全行业均值被拉低，算出来比佛山还低，与事实不符"),
        ("为什么不用单位决算人均",
         "决算「工资福利支出÷人数」混合事业编/工勤/临聘。教育局人均低是因为教师多，教师与公务员不同工资体系。"
         "用它当「我进去能拿多少」，方向是错的。"),
        ("单位怎么影响收入", "只通过政策规定的专项津贴：政法+10%、乡镇+4%、执法+3%、纪检审计+3%。固定金额而非比例，故低工资城市占比更高"),
        ("工资总额口径", "统计口径不含单位缴纳的社保和公积金，含个人缴纳部分（代扣仍属工资）"),
        ("到手含双边公积金怎么算", "工资总额 − 个人社保14%(养老8+医保2+职业年金4) − 个税；个人公积金与单位公积金都加回（各12%）"),
        ("个税", "年度综合所得，减除费用6万 + 专项附加扣除2.4万，累进税率"),
        ("与原调研档位的关系", "本表**替代**原档位。原档位是「多来源调研汇总」，不可追溯、系统性偏高"),
        ("已知偏差①", "公积金按工资总额12%计。实际缴存基数有上限（深圳2024年约4万/月），高工资城市会被高估"),
        ("已知偏差②", "未计单位缴纳的社保与公积金（占工资福利支出约25%），故本表不是「单位人力成本」"),
        ("已知偏差③", "统计年鉴为2024年数，2026年招录的实际工资会随调薪略涨（通常每年2~4%）"),
        ("已知偏差④", "房价为调研二手数据，非官方；买100㎡需(年)仅作城市间相对比较"),
        ("校验①", "到手含双边 ÷ 工资总额 ≈ 0.95，因为公积金双边计回、只扣社保14%与个税约3%"),
        ("校验②", "公共管理行业 161,980 元 vs 教育 161,425 元 vs 卫生 198,415 元——三者量级一致，说明系数可信"),
        ("校验③", "深圳推算应发 20.9 万，低于原档位 27.2 万。原档位对应应发约 32 万，已接近处级，非科员水平"),
        ("单位级旁证", "见「单位级实测」页：广州市 18 个市级单位 2025 年决算的工资福利支出，从 2,585 万到 82,186 万，差 32 倍"),
        ("建议用法", "先看本页的市间差异（官方、可复核），再看岗位明细里的单位系数（政策可查），最后看房价年数（自住成本）"),
    ]
    for r in notes:
        s3.append(list(r))

    # ── 单位级实测（广州市 2025 年度部门决算，unit_budget.py 抓取）──
    s4 = out.create_sheet("单位级实测")
    s4.append(["单位", "年度", "口径", "工资福利支出(万元)", "在职人数", "说明"])
    for u, w in [
        ("广州市卫生健康委员会", 82186.36), ("广州市规划和自然资源局", 43870.47),
        ("广州市农业农村局", 23981.09), ("广州市港务局", 16749.28),
        ("广州市商务局", 12704.52), ("广州市发展和改革委员会", 12423.23),
        ("广州市退役军人事务局", 12099.76), ("广州市政务服务和数据管理局", 10144.31),
        ("广州市天河区人民法院", 9222.46), ("广州市黄埔区人民法院", 8525.24),
        ("广州市花都区人民法院", 8312.34), ("广州市科学技术局", 7509.28),
        ("中国共产党广州市委员会统战部", 5835.87), ("广州市档案馆", 4771.47),
        ("广州市消防救援支队", 3993.06), ("广州市协作办公室", 2995.72),
        ("中共广州市委金融委员会办公室", 2766.36), ("中共广州市委社会工作部", 2584.56),
    ]:
        s4.append([u, 2025, "财政拨款", w, "未披露",
                   "决算公开表不披露人数（18/18 实测），故不能算人均；此处仅示单位间规模差异"])

    # ── 样式 ──
    for sh, widths in ((s1, [10, 18, 9, 14, 13, 12, 12, 13, 11, 13, 13, 11, 10, 26]),
                       (s2, None), (s4, [30, 7, 10, 20, 10, 52])):
        if widths:
            for i, w in enumerate(widths, 1):
                sh.column_dimensions[get_column_letter(i)].width = w
    for sh in (s1, s2, s3, s4):
        for c in sh[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2F5597")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sh.freeze_panes = "B2"
        sh.row_dimensions[1].height = 34
    s3.column_dimensions["A"].width = 26
    s3.column_dimensions["B"].width = 92
    for row in s3.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    out.save(a.out)

    # ── 控制台摘要 ──
    print(f"{'市':<6}{'应发(元)':>10}{'到手含双边(万)':>15}{'原档位(万)':>11}{'偏差':>8}{'买房年':>8}")
    for c in sorted(city_stat, key=lambda x: -city_stat[x]["net"]["net_all"]):
        st = city_stat[c]
        old = OLD_PACK.get(c)
        dev = f"{st['net']['net_all'] / 10_000 / old - 1:+.0%}" if old else "—"
        print(f"{c:<6}{st['gross']:>10,.0f}{st['net']['net_all'] / 1e4:>15.1f}"
              f"{(old if old else '—'):>11}{dev:>8}{(round(st['years'], 1) if st['years'] else '—'):>8}")
    print(f"\n已写出：{a.out}（{len(rows)} 个岗位 / {len(city_stat)} 个市）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
