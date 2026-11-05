#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部门决算 → 人均工资福利支出（推算）

口径（data-sources.md §六）：
    人均工资福利支出（年） = 工资福利支出 ÷ 在职人数

用法：
    # 单个单位
    python3 scripts/budget_salary.py 决算表.xls --headcount 120

    # 人数已在决算说明里 → 自动抽取
    python3 scripts/budget_salary.py 决算表.xlsx

    # 多个单位横向对比 + 落盘
    python3 scripts/budget_salary.py a.xls b.xlsx c.pdf --json out.json --md out.md

    # 自检（会临时造 4 份不同版式的表，断言计算结果）
    python3 scripts/budget_salary.py --selftest

设计约束（都是被真实决算表坑出来的，改动请保留）：
  1. **金额单位必须显式识别**：「单位：万元 / 元 / 千元」写在表头，但常被合并单元格吃掉；
     识别不到时按数量级推断，并**一定**在 warnings 里留痕——单位错一位，结论差 10000 倍。
  2. **分母优先「在职/实有」，绝不默认用「编制人数」**：编制 ≥ 实有（空编常见 10~20%），
     用编制当分母会系统性低估人均 10~20%。只能用编制时必须降级标注。
  3. **同一份文件里「工资福利支出」会出现 2~3 次**（支出决算表 / 基本支出表 / 财政拨款表），
     取数要按上下文打分选表，值不一致时报警而不是随便挑一个。
  4. **明细（基本工资/津贴补贴/…）之和 ≠ 合计** 很常见（有「其他」或未列示项），
     只做提示，不阻断。
  5. 输出里的每个数字都要能回溯到「哪张表、哪一行、哪段文字」，否则等于编数据。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ── 科目表 ────────────────────────────────────────────────────────
# 工资福利支出下的 12 个款级科目。cash=现金性（能进工资卡），employer=单位缴费（进社保/公积金账户）
SUBITEMS: list[tuple[str, str]] = [
    ("基本工资", "cash"),
    ("津贴补贴", "cash"),
    ("奖金", "cash"),
    ("伙食补助费", "cash"),
    ("绩效工资", "cash"),
    ("机关事业单位基本养老保险缴费", "employer"),
    ("职业年金缴费", "employer"),
    ("职工基本医疗保险缴费", "employer"),
    ("公务员医疗补助缴费", "employer"),
    ("其他社会保障缴费", "employer"),
    ("住房公积金", "employer"),
    ("医疗费", "employer"),
    ("其他工资福利支出", "cash"),
]

UNIT_FACTOR = {"元": 1, "千元": 1_000, "万元": 10_000, "亿元": 100_000_000}

# 人均合理区间（元/年）。超出只告警不阻断——真有极端单位。
SANITY_LOW, SANITY_HIGH = 50_000, 400_000


# ── 基础工具 ──────────────────────────────────────────────────────
def norm(s) -> str:
    """全角转半角 + 去掉所有空白。决算表里的空格是灾难源（'工 资 福 利 支 出'）。"""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", "", t)


EMPTY_TOKENS = {"", "—", "-", "－", "/", "…", "——", "0"}


def to_num(v) -> float | None:
    """单元格 → 数字。'2,400.00' / '２４００' / '—' / None 都要正确处理。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = norm(v)
    if s in EMPTY_TOKENS:
        return 0.0 if s == "0" else None
    s = s.replace(",", "").replace("，", "")
    s = s.rstrip("元")
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return float(s)
    return None


def wlen(s: str) -> int:
    """终端显示宽度（中文占 2 列），用于表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int, align: str = "left") -> str:
    gap = max(0, width - wlen(s))
    return (" " * gap + s) if align == "right" else (s + " " * gap)


def money(v: float | None, nd: int = 2) -> str:
    return "—" if v is None else f"{v:,.{nd}f}"


# ── 读表 ──────────────────────────────────────────────────────────
@dataclass
class Sheet:
    name: str
    rows: list[list]


def _split_inline(line: str) -> list:
    """PDF/纯文本行 → [标签, 数字...]。'工资福利支出 2,400.00 2,400.00 0.00'"""
    nums = re.findall(r"-?\d[\d,]*\.?\d*", line)
    if not nums:
        return [line]
    head = line[: line.find(nums[0])]
    return [head, *[n.replace(",", "") for n in nums]]


def load_sheets(path: Path) -> list[Sheet]:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        out = [Sheet(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        wb.close()
        return out
    if suf == ".xls":
        import xlrd

        wb = xlrd.open_workbook(str(path))
        out = []
        for sh in wb.sheets():
            rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
            out.append(Sheet(sh.name, rows))
        return out
    if suf in (".csv", ".txt"):
        import csv

        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = [r for r in csv.reader(f)]
        return [Sheet("csv", [[c for c in r] for r in rows])]
    if suf in (".html", ".htm", ".shtml"):
        from bs4 import BeautifulSoup

        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for i, tbl in enumerate(soup.find_all("table"), 1):
            rows = []
            # 表格标题常在 <table> 外面（上一个 <p>/<div>），而「一般公共预算财政拨款
            # 基本支出决算明细表」这几个字正是判断口径的依据 —— 补进首行
            node = tbl
            for _ in range(3):          # 标题可能挂在 table 的 1~3 层祖先之前
                for sib in list(node.find_previous_siblings())[:4]:
                    cap = sib.get_text(" ", strip=True)
                    if cap and len(cap) <= 60 and ("决算" in cap or "支出" in cap):
                        rows.append([cap])
                        node = None
                        break
                if node is None or node.parent is None:
                    break
                node = node.parent
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append(cells)
            if len(rows) >= 2:          # 单行表/布局表直接丢掉
                out.append(Sheet(f"table{i}", rows))
        if not out:
            raise SystemExit(f"✗ {path.name}：网页里没有表格，请确认是决算正文页而非列表页")
        # 正文段落也留一份（「年末在职职工人数 XX 人」常在表格外）
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        txt = [_split_inline(ln) for p in paras for ln in p.splitlines() if ln.strip()]
        if txt:
            out.append(Sheet("正文", txt))
        return out
    if suf == ".pdf":
        import pdfplumber

        out = []
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages):
                rows: list[list] = []
                for tbl in page.extract_tables() or []:
                    rows.extend([[c for c in r] for r in tbl])
                if rows:
                    out.append(Sheet(f"page{i + 1}", rows))
                # ⚠️ 表格页的**非表格文本**必须单独留一份：
                #    「金额单位：万元」「年末在职职工人数 XX 人」「人员经费说明」
                #    都在表格外，只靠 extract_tables 会全部丢掉（实测广东局决算 PDF 即如此）
                txt = [_split_inline(ln) for ln in (page.extract_text() or "").splitlines() if ln.strip()]
                if txt:
                    out.append(Sheet(f"page{i + 1}-text", txt))
        return out
    raise SystemExit(f"✗ 不支持的文件类型：{suf}（支持 .xls/.xlsx/.csv/.pdf/.html）")


# ── 单位识别 ──────────────────────────────────────────────────────
def detect_unit(sheets: list[Sheet]) -> tuple[str | None, str]:
    """返回 (单位, 依据)。只看前 12 行表头区域，避免正文里的「万元」误伤。"""
    for sh in sheets:
        for r, row in enumerate(sh.rows[:12]):
            for c in row:
                t = norm(c)
                if not t:
                    continue
                if "单位" in t and ":" in t:
                    for u in ("亿元", "万元", "千元", "元"):
                        if u in t:
                            return u, f"{sh.name}!R{r + 1}C?「{str(c).strip()[:24]}」"
    # 兜底：整表扫一遍「单位：X元」
    for sh in sheets:
        for r, row in enumerate(sh.rows):
            for c in row:
                t = norm(c)
                if t.startswith("单位:") and "元" in t:
                    for u in ("亿元", "万元", "千元", "元"):
                        if u in t:
                            return u, f"{sh.name}!R{r + 1}「{str(c).strip()[:24]}」(兜底扫描)"
    return None, "未识别"


# ── 工资福利支出定位 ──────────────────────────────────────────────
@dataclass
class Candidate:
    sheet: str
    row: int
    col: int
    value: float  # 原始单位
    context: str
    score: int



def adjacent_value(row: list, label_col: int) -> float | None:
    """取「标签右侧紧邻的那个非空单元格」的值；右边紧邻是文字则判定该行无值。

    两个必须守住的坑（都来自同一张真实表：广东省税务局 2024 年度单位决算 p16）：

    ① 基本支出决算明细表是**三栏并排**（人员经费 / 公用经费 / 资本性支出，
       每栏「科目名称 + 决算数」）。若某科目决算数为空，往右找第一个数字会落到
       **下一栏的别的科目**上去 —— 所以只能看紧邻，不能一路往右找。

    ② 更阴的是**科目编码长得像金额**：`30107 绩效工资` 后面空着，再往右是
       下一栏的编码 `30205`，`to_num('30205')` 返回 30205.0 —— 于是「绩效工资」
       被算成 30,205 万元，明细合计比总额凭空多出 4.3%。
       判据：纯整数、3~8 位、且右侧紧邻还是文字 → 这是编码不是钱。
    """
    for j in range(label_col + 1, len(row)):
        cell = row[j]
        t = norm(cell)
        if t == "":
            continue                      # 跳过空单元格（合并单元格常见）
        v = to_num(cell)
        if v is None:
            return None                   # 紧邻非空是文字 → 该行此项无值
        if isinstance(cell, str) and re.fullmatch(r"\d{3,8}", t):
            nxt = next((norm(x) for x in row[j + 1:] if norm(x) != ""), "")
            if nxt and to_num(nxt) is None:
                return None               # 形如科目编码 + 右边接文字 → 不取
        return v
    return None


def _row_header_hit(sheet: Sheet, row_idx: int, col_idx: int) -> bool:
    """上方 6 行内是否有「…合计」表头落在同列（排除「基本支出/项目支出」）。"""
    for r in range(max(0, row_idx - 6), row_idx):
        if col_idx < len(sheet.rows[r]):
            h = norm(sheet.rows[r][col_idx])
            if "合计" in h and "基本" not in h and "项目" not in h:
                return True
    return False


def find_wage_total(sheets: list[Sheet]) -> tuple[list[Candidate], list[str]]:
    warns: list[str] = []
    cands: list[Candidate] = []
    for sh in sheets:
        head = " ".join(norm(c) for row in sh.rows[:8] for c in row if c)
        for r, row in enumerate(sh.rows):
            for c, cell in enumerate(row):
                label = norm(cell)
                if not label:
                    continue
                # 允许「工资福利支出」「工资福利支出合计」「1.工资福利支出」
                if not re.fullmatch(r"(?:\d+[.、])?(?:其中[:：])?工资福利支出(?:合计)?", label):
                    continue
                pick = adjacent_value(row, c)
                # 表头里已经指明「合计」列时优先按列定位（应对「合计/基本支出/项目支出」多列）
                if _row_header_hit(sh, r, c):
                    for j in range(c + 1, len(row)):
                        v = to_num(row[j])
                        if v is not None and _row_header_hit(sh, r, j):
                            pick = v
                            break
                if pick is None:
                    continue
                score = 0
                if "基本支出" in head or "基本支出" in sh.name:
                    score += 3
                if "经济分类" in head or "经济分类" in sh.name:
                    score += 2
                # 有子科目行跟随 → 更像正表
                nxt = sh.rows[r + 1] if r + 1 < len(sh.rows) else []
                if any(norm(v).startswith(("基本工资", "津贴补贴")) for v in nxt if v):
                    score += 2
                cands.append(Candidate(sh.name, r + 1, c + 1, pick, f"{sh.name} 第{r + 1}行", score))
    cands.sort(key=lambda x: -x.score)
    uniq: dict[float, Candidate] = {}
    for cd in cands:
        key = round(cd.value, 2)
        if key not in uniq:
            uniq[key] = cd
    picked = list(uniq.values())
    if len(picked) > 1:
        vals = sorted(uniq)
        if vals[-1] - vals[0] > max(1.0, vals[-1] * 0.01):
            detail = "；".join(f"{c.sheet}第{c.row}行={money(c.value)}" for c in picked)
            warns.append(f"同一文件出现多个不同口径的工资福利支出（{detail}），已取上下文得分最高者，请人工确认口径")
    return picked, warns


def resolve_wan(sheets: list[Sheet], cand: "Candidate", unit_override: str = "") -> tuple[float, str, str]:
    """把一个「工资福利支出」候选值换算成万元，并说明依据。

    抽成独立函数，是因为 `unit_budget.py` 只取分子、不取分母时也要用同一套换算
    —— 单位错一位结论差 10000 倍，绝不能两个脚本各写一份。
    """
    if unit_override:
        unit, basis = unit_override, "命令行指定"
    else:
        unit, basis = detect_unit(sheets)
    if unit is None:
        v = cand.value
        if v >= 1e7:
            unit, basis = "元", "按数量级推断（≥1e7 视为元）"
        elif v >= 1e2:
            unit, basis = "万元", "按数量级推断（1e2~1e7 视为万元）"
        else:
            raise SystemExit(f"✗ 无法判断金额单位（工资福利支出={v}），请用 --unit 元|万元 指定")
    return cand.value * UNIT_FACTOR[unit] / 10_000, unit, basis


def find_subitems(sheets: list[Sheet], prefer: str = "") -> tuple[dict[str, float], list[str]]:
    """按款级科目抽明细。**优先只在总额所在那张表里找**——跨页找会把
    财政拨款表 / 上年数 / 说明段里的同名科目混进来（口径不同，不能相加）。"""
    warns: list[str] = []
    ordered = ([sh for sh in sheets if sh.name == prefer] +
               [sh for sh in sheets if sh.name != prefer]) if prefer else sheets
    out: dict[str, float] = {}
    for name, _ in SUBITEMS:
        for sh in ordered:
            hit = None
            for row in sh.rows:
                for c, cell in enumerate(row):
                    lab = norm(cell)
                    if lab == name or lab == f"其中:{name}":
                        v = adjacent_value(row, c)
                        if v is not None:
                            hit = v
                            break
                if hit is not None:
                    break
            if hit is not None:
                out[name] = hit
                if prefer and sh.name != prefer:
                    warns.append(f"「{name}」取自 {sh.name}（不在总额所在表 {prefer} 内，口径可能不同）")
                break
    return out, warns


# ── 人数识别 ──────────────────────────────────────────────────────
HC_PATTERNS = [
    (r"(?:年末|年底|本年末)?在职(?:职工|人员)?(?:人数|人员数|职工人数)?[为共]?[:：]?(\d{1,5})人", "在职人数"),
    (r"实有(?:在职)?(?:人员|人数|职工)(?:人数)?[为共]?[:：]?(\d{1,5})", "实有人数"),
    (r"在职(?:人员|职工)?(?:总数|总人数)[:：]?(\d{1,5})", "在职总人数"),
    (r"(\d{1,5})名在职", "在职人数"),
    (r"职工人数[:：]?(\d{1,5})", "职工人数"),
]
HC_ESTAB = [
    (r"编制(?:人数|数)?[:：]?(\d{1,5})", "编制人数"),
    (r"核定编制[:：]?(\d{1,5})", "核定编制"),
]


def find_headcount(sheets: list[Sheet]) -> tuple[int | None, str, bool]:
    """返回 (人数, 依据, 是否降级用编制)。

    ⚠️ 匹配必须跑在 norm() 之后的文本上：「在职职工人数 120 人」中间那个空格
    会让 `(\\d+)` 直接失配，而决算表里 100% 带空格。
    """
    texts: list[tuple[str, str, str]] = []  # (位置, 原文, 归一化文本)
    for sh in sheets:
        for r, row in enumerate(sh.rows):
            line = " ".join(str(c) for c in row if c is not None)
            if line.strip():
                texts.append((f"{sh.name}!R{r + 1}", line, norm(line)))

    for pat, label in HC_PATTERNS:
        for loc, raw, flat in texts:
            m = re.search(pat, flat)
            if m and 1 <= int(m.group(1)) <= 200_000:
                return int(m.group(1)), f"{label}「{raw.strip()[:40]}」({loc})", False
    # 跨行/跨单元格的兜底：整篇拼起来再试一次
    blob = "".join(flat for _, _, flat in texts)
    for pat, label in HC_PATTERNS:
        m = re.search(pat, blob)
        if m and 1 <= int(m.group(1)) <= 200_000:
            return int(m.group(1)), f"{label}「{m.group(0)}」(全篇拼接命中，建议人工核对)", False
    # 降级：编制人数（≥ 实有，会把人均压低）
    for pat, label in HC_ESTAB:
        for loc, raw, flat in texts:
            m = re.search(pat, flat)
            if m and 1 <= int(m.group(1)) <= 200_000:
                return int(m.group(1)), f"{label}「{raw.strip()[:40]}」({loc})（⚠️ 非实有）", True
    return None, "未找到", False



# ── 缴费反推人数（带锚的区间解）──────────────────────────────────
# 数学前提（必须先讲清，否则就是在编数）：
#   缴费额 = 人数 N × 人均月缴费基数 b × 费率 r × 12
#   其中 b 与 N **同时未知**，一个方程两个未知数 → **无解**。
#   想解 N，只能给 b 加一个外部锚（当地社平工资的 k 倍），
#   于是得到的是一个**区间**，不是一个数。
#
#   锚定后的三条独立线索（费率都是法定/公开口径）：
#     ① 养老 + 职业年金：单位 16% + 8% = 24%（同基数，最稳的一条）
#     ② 住房公积金：单位 5%~12%（机关普遍顶格，但地区差异大）
#     ③ 职工医保：单位 6%~10%（含生育，各地不同）
#   三条线索**互不共用参数**，若区间有交集 → 可信；若三线互相打架 → 说明该单位
#   存在大量非在编人员、或基数触顶、或某项由财政统缴 → 反推作废。
CONTRIB = {
    "pension": 0.24,      # 养老 16% + 年金 8%，固定
    "fund": (0.05, 0.12),
    "medical": (0.06, 0.10),
}


def estimate_headcount(items: dict[str, float], social_wage: float,
                       k_low: float = 1.0, k_high: float = 2.0) -> dict:
    """用公积金/社保反推在职人数区间。

    social_wage: 当地全口径城镇单位就业人员**月**平均工资（元），
                 取自省统计局/人社厅公布数（一手）。
    k_low/k_high: 机关事业单位人均缴费基数 ÷ 社平工资 的倍数区间，默认 1.0~2.0。
                  → 这个倍数就是全部的误差来源，必须写明。
    """
    if social_wage <= 0:
        raise ValueError("social_wage 必须 > 0（单位：元/月）")

    b_low, b_high = social_wage * k_low, social_wage * k_high

    def rng(amount_wan: float, rate_low: float, rate_high: float) -> tuple[float, float]:
        """N 的下界 = 金额 / (高费率 × 高基数)；上界 = 金额 / (低费率 × 低基数)。"""
        if amount_wan <= 0:
            return (0.0, 0.0)
        amt = amount_wan * 10_000
        return (amt / (rate_high * 12 * b_high), amt / (rate_low * 12 * b_low))

    lines = []
    p = items.get("机关事业单位基本养老保险缴费", 0) + items.get("职业年金缴费", 0)
    if p > 0:
        lo, hi = rng(p, CONTRIB["pension"], CONTRIB["pension"])
        lines.append({"线索": "养老+职业年金（24%）", "金额(万元)": p, "N下界": lo, "N上界": hi})
    f = items.get("住房公积金", 0)
    if f > 0:
        lo, hi = rng(f, *CONTRIB["fund"])
        lines.append({"线索": "住房公积金（5%~12%）", "金额(万元)": f, "N下界": lo, "N上界": hi})
    m = items.get("职工基本医疗保险缴费", 0) + items.get("公务员医疗补助缴费", 0)
    # 守卫：医保费率(6~10%) 约为养老+年金(24%) 的 1/3。若医保额 < 养老额 1/10，
    # 说明该单位医保由财政统筹/公务员医疗补助单独列支，决算表里的数不可用（广州实测 3.25 万 vs 577 万）。
    if m > 0 and (p <= 0 or m >= p * 0.1):
        lo, hi = rng(m, *CONTRIB["medical"])
        lines.append({"线索": "职工医保（6%~10%）", "金额(万元)": m, "N下界": lo, "N上界": hi})
    elif m > 0:
        lines.append({"线索": "职工医保（6%~10%）", "金额(万元)": m,
                      "N下界": 0, "N上界": 0, "跳过": "医保额异常小（<养老10%），疑财政统缴，弃用"})

    if not lines:
        return {"ok": False, "reason": "没有养老/公积金/医保任一项，无法反推", "lines": []}

    # 交集：下界取各线最大，上界取各线最小（弃用的线 N=0，不参与）
    active = [l for l in lines if l.get("N上界", 0) > 0]
    lo = max(l["N下界"] for l in active)
    hi = min(l["N上界"] for l in active)
    overlap = lo <= hi
    if not overlap:
        lo = min(l["N下界"] for l in active)
        hi = max(l["N上界"] for l in active)
    return {
        "ok": True, "lines": lines, "overlap": overlap,
        "n_low": lo, "n_high": hi,
        "b_low": b_low, "b_high": b_high,
        "social_wage": social_wage, "k": (k_low, k_high),
    }


# ── 计算 ──────────────────────────────────────────────────────────
@dataclass
class Result:
    file: str
    sheet: str
    row: int
    unit_name: str
    year: str | None
    unit: str
    factor: int
    wage_wan: float
    headcount: int
    headcount_basis: str
    scope: str
    per_capita_yuan: float
    per_capita_wan: float
    items: dict[str, float] = field(default_factory=dict)
    cash_wan: float = 0.0
    employer_wan: float = 0.0
    cash_share: float | None = None
    net_hint_yuan: float | None = None
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    hc_est: dict | None = None
    per_capita_low: float | None = None
    per_capita_high: float | None = None

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["formula"] = "人均工资福利支出 = 工资福利支出 ÷ 在职人数（推算）"
        return d



def guess_unit_name(sheets: list[Sheet], fallback: str) -> str:
    """从「部门：XXX」「单位：XXX」取单位名——文件名常被改成简称。"""
    best = ""
    for sh in sheets[:8]:
        for row in sh.rows[:40]:
            for c in row:
                t = norm(c)
                m = re.fullmatch(r"(?:部门|单位)[:：](.{4,40})", t)
                if not m:
                    continue
                cand = m.group(1)
                if "金额" in cand or "元" in cand[-3:]:
                    continue
                if len(cand) > len(best):
                    best = cand
    return best or fallback


def detect_scope(sheet_name: str, sheets: list[Sheet]) -> str:
    """取数口径：全口径 / 财政拨款 / 基本支出。
    三者数值可能不同——教育局这类有事业收入的单位，绩效工资可能不走财政拨款。"""
    head = sheet_name
    for sh in sheets:
        # 表名 + 本表前 6 行 + 同页文本（PDF 的表标题「六、基本支出决算明细表」在表格外）
        if sh.name in (sheet_name, f"{sheet_name}-text"):
            n = 8 if sh.name.endswith("-text") else 6
            head += " " + " ".join(norm(c) for row in sh.rows[:n] for c in row if c)
    if "财政拨款" in head:
        return "财政拨款"
    if "基本支出" in head:
        return "基本支出"
    return "全口径"


def guess_name_year(path: Path, sheets: list[Sheet]) -> tuple[str, str | None]:
    name = path.stem
    year = None
    m = re.search(r"(20\d{2})", name)
    if m:
        year = m.group(1)
    if year is None:
        blob = " ".join(str(c) for sh in sheets[:2] for row in sh.rows[:15] for c in row if c)
        m = re.search(r"(20\d{2})\s*年度", blob) or re.search(r"(20\d{2})年", blob)
        if m:
            year = m.group(1)
    return name, year


def analyze(path: Path, headcount: int | None, unit_override: str, sheet_hint: str,
            net_factor: float, strict: bool, no_headcount: bool = False,
            social_wage: float = 0.0, k_low: float = 1.0, k_high: float = 2.0) -> Result:
    sheets = load_sheets(path)
    if sheet_hint:
        picked = [s for s in sheets if sheet_hint in s.name]
        if not picked:
            raise SystemExit(f"✗ 找不到 sheet：{sheet_hint}（现有：{[s.name for s in sheets]}）")
        sheets = picked

    name, year = guess_name_year(path, sheets)
    name = guess_unit_name(sheets, name)
    cands, warns = find_wage_total(sheets)
    if not cands:
        raise SystemExit(f"✗ {path.name}：没有定位到「工资福利支出」行，请确认是决算表（经济分类）而非预算表/收入表")

    best = cands[0]
    wage_wan, unit, unit_basis = resolve_wan(sheets, best, unit_override)
    if unit_override:
        pass
    elif "数量级推断" in unit_basis:
        warns.append(f"未在表头找到「单位：X元」，{unit_basis}；单位错一位结论差 10000 倍，建议人工核一遍")

    factor = UNIT_FACTOR[unit]
    if wage_wan <= 0:
        raise SystemExit(f"✗ 工资福利支出为 0（{best.context}），无法计算人均")

    items_raw, sub_warns = find_subitems(sheets, best.sheet)
    warns.extend(sub_warns)
    items_wan = {k: v * factor / 10_000 for k, v in items_raw.items()}
    cash = sum(v for k, v in items_wan.items() if dict(SUBITEMS)[k] == "cash")
    employer = sum(v for k, v in items_wan.items() if dict(SUBITEMS)[k] == "employer")

    if headcount:
        hc, hc_basis, degraded = headcount, "命令行指定 --headcount", False
    else:
        hc, hc_basis, degraded = find_headcount(sheets)
    hc_est = None
    if not hc and social_wage > 0:
        est = estimate_headcount(items_wan, social_wage, k_low, k_high)
        hc_est = est
        if est["ok"]:
            hc = int(round((est["n_low"] + est["n_high"]) / 2))
            hc_basis = (f"缴费反推区间 {est['n_low']:,.0f}~{est['n_high']:,.0f} 人，"
                        f"取中位 {hc:,} 人（锚：社平月薪 {social_wage:,.0f} 元 × {k_low}~{k_high}）")
            warns.append(
                f"分母是**反推值**不是实数：区间 {est['n_low']:,.0f}~{est['n_high']:,.0f} 人，"
                f"宽度 ±{(est['n_high'] - est['n_low']) / max(1, hc) / 2:.0%}；"
                "人均只能当量级参考，引用时必须同时给出区间"
            )
            if not est["overlap"]:
                warns.append("三条缴费线索的区间**没有交集** → 存在非在编人员/基数触顶/统缴，反推不可信")
    if not hc and no_headcount:
        hc, hc_basis, degraded = 0, "未提供（--no-headcount，仅出总额与结构）", False
        warns.append("没有在职人数：只输出分子与结构，人均一栏为空")
    elif not hc:
        raise SystemExit(
            f"✗ {path.name}：没有找到在职人数，无法算人均。\n"
            "  实测结论：**决算公开表普遍不披露人数**（广东省税务局 2024/2025 年度单位决算、\n"
            "  荆门市东宝区教育局 2024 年度部门决算，正文与表格里都没有「在职 XX 人」）。\n"
            "  人数的官方取数处（按可靠性排序）：\n"
            "    1) 本单位**部门预算说明**「人员编制及实有情况」段（预算公开与决算同栏目）\n"
            "    2) 机构编制部门年度统计 / 单位「三定」方案\n"
            "    3) 上级主管部门人事年报、招录公告里的编制数（⚠️ 编制≠实有，只能当上限）\n"
            "  取到后用 --headcount 传入；只想看总额和结构可加 --no-headcount。"
        )
    if degraded:
        warns.append("分母用的是「编制人数」而非实有在职人数，人均会被系统性低估 10~20%，仅作上限参考")

    per_capita = (wage_wan * 10_000 / hc) if hc else 0.0
    pc_low = (wage_wan * 10_000 / hc_est["n_high"]) if (hc_est and hc_est.get("ok")) else None
    pc_high = (wage_wan * 10_000 / hc_est["n_low"]) if (hc_est and hc_est.get("ok")) else None
    if hc and (per_capita < SANITY_LOW or per_capita > SANITY_HIGH):
        warns.append(f"人均 {per_capita:,.0f} 元/年 超出常规区间（{SANITY_LOW / 1e4:.0f}~{SANITY_HIGH / 1e4:.0f} 万），请核对分子分母")

    sub_sum = cash + employer
    if sub_sum:
        gap = (sub_sum - wage_wan) / wage_wan
        if abs(gap) > 0.02:
            warns.append(f"明细合计 {sub_sum:,.2f} 万元 与 工资福利支出 {wage_wan:,.2f} 万元 相差 {gap:+.1%}（有未列示项或明细不全）")
    else:
        warns.append("未取到款级明细，只能给总额口径")

    cash_share = (cash / wage_wan) if wage_wan else None   # 结构占比与人次无关，没人数也算得出
    r = Result(
        file=str(path), sheet=best.sheet, row=best.row, unit_name=name, year=year,
        unit=unit, factor=factor, wage_wan=wage_wan, headcount=hc,
        headcount_basis=hc_basis, scope=detect_scope(best.sheet, sheets),
        per_capita_yuan=per_capita, per_capita_wan=per_capita / 10_000,
        items=items_wan, cash_wan=cash, employer_wan=employer, cash_share=cash_share,
        net_hint_yuan=(per_capita * cash_share * net_factor) if (cash_share and per_capita) else None,
        warnings=warns, degraded=degraded, hc_est=hc_est,
        per_capita_low=pc_low, per_capita_high=pc_high,
    )
    r.warnings.insert(0, f"金额单位：{unit}（{unit_basis}）")
    if strict and len(r.warnings) > 1:
        print("\n".join("  ⚠ " + w for w in r.warnings), file=sys.stderr)
        raise SystemExit(f"✗ --strict：{path.name} 存在 {len(r.warnings) - 1} 条告警，拒绝出数")
    return r


# ── 输出 ──────────────────────────────────────────────────────────
def trunc(s: str, width: int) -> str:
    """按显示宽度截断，避免长文件名把整张表挤歪。"""
    if wlen(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > width - 1:
            break
        out, w = out + ch, w + cw
    return out + "…"


def render(results: list[Result], net_factor: float) -> str:
    L: list[str] = []
    L.append("部门决算 → 人均工资福利支出（推算）")
    L.append("=" * 84)
    L.append("口径：人均工资福利支出 = 工资福利支出 ÷ 在职人数   ← 单位口径人力成本，不是到手")
    L.append("")
    cols = [("单位", 26), ("年度", 6), ("口径", 10), ("工资福利支出(万元)", 18), ("在职", 6),
            ("人均(万元/年)", 14), ("人均(元/年)", 12), ("现金性", 8)]
    L.append("  ".join(pad(h, w, "right" if i else "left") for i, (h, w) in enumerate(cols)).rstrip())
    L.append("-" * 84)
    for r in results:
        row = [
            (trunc(r.unit_name, cols[0][1]), "left"),
            (r.year or "—", "left"),
            (r.scope, "left"),
            (money(r.wage_wan), "right"),
            (str(r.headcount or "—"), "right"),
            (f"{r.per_capita_wan:.2f}" if r.headcount else "—", "right"),
            (money(r.per_capita_yuan, 0) if r.headcount else "—", "right"),
            (f"{r.cash_share:.1%}" if r.cash_share is not None else "—", "right"),
        ]
        L.append("  ".join(pad(v, w, a) for (v, a), (_, w) in zip(row, cols)).rstrip())
    L.append("")

    for r in results:
        L.append(f"── {r.unit_name} ──")
        L.append(f"  分子  {money(r.wage_wan)} 万元 = 工资福利支出（{r.sheet} 第 {r.row} 行，单位：{r.unit}，口径：{r.scope}）")
        L.append(f"  分母  {r.headcount or '—'} 人（{r.headcount_basis}）")
        if r.hc_est and r.hc_est.get("ok"):
            L.append("  反推  缴费额 ÷ (人均缴费基数 × 费率 × 12)，三条线索各给一个区间：")
            for ln in r.hc_est["lines"]:
                L.append(f"    {pad(ln['线索'], 24)}{pad(money(ln['金额(万元)']), 12, 'right')}"
                         f"   → {ln['N下界']:>8,.0f} ~ {ln['N上界']:<8,.0f} 人")
            L.append(f"    合并区间 {r.hc_est['n_low']:,.0f} ~ {r.hc_est['n_high']:,.0f} 人"
                     f"{'（三线有交集）' if r.hc_est['overlap'] else '（三线无交集，不可信）'}")
        if r.headcount:
            L.append(f"  人均  {money(r.per_capita_yuan, 0)} 元/年 = {r.per_capita_wan:.2f} 万元/年  〔推算〕")
            if r.per_capita_low:
                L.append(f"  区间  {money(r.per_capita_low, 0)} ~ {money(r.per_capita_high, 0)} 元/年"
                         f"（{r.per_capita_low / 1e4:.1f}~{r.per_capita_high / 1e4:.1f} 万元/年）")
        else:
            L.append("  人均  —（缺分母，未计算）")
        if r.items:
            L.append("  结构（万元 / 占工资福利支出）")
            for name, _ in SUBITEMS:
                if name in r.items:
                    v = r.items[name]
                    L.append(f"    {pad(name, 26)}{pad(money(v), 12, 'right')}{v / r.wage_wan:>9.1%}")
            L.append(f"    {pad('现金性小计', 26)}{pad(money(r.cash_wan), 12, 'right')}{r.cash_wan / r.wage_wan:>9.1%}")
            L.append(f"    {pad('单位缴费小计', 26)}{pad(money(r.employer_wan), 12, 'right')}{r.employer_wan / r.wage_wan:>9.1%}")
            if r.net_hint_yuan and r.headcount:
                L.append(f"  参考  人均现金性 {r.cash_wan * 1e4 / r.headcount:,.0f} 元/年；"
                         f"按 ×{net_factor:.2f} 折算到手约 {r.net_hint_yuan:,.0f} 元/年（经验系数，仅定档用）")
        for w in r.warnings:
            L.append(f"  ⚠ {w}")
        L.append("")
    L.append("⚠ 推算值，非官方发布口径；引用须同时给出：分子（决算表名+行）、分母（人数出处）、年度。")
    return "\n".join(L)


def render_md(results: list[Result], net_factor: float) -> str:
    L = ["# 部门决算 → 人均工资福利支出", "",
         "> **推算**，非官方口径。公式：`人均工资福利支出 = 工资福利支出 ÷ 在职人数`（单位口径人力成本，含单位缴纳的社保与公积金，≠ 到手）。", "",
         "| 单位 | 年度 | 口径 | 工资福利支出(万元) | 在职(人) | 人均(万元/年) | 人均(元/年) | 现金性占比 | 取数位置 |",
         "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for r in results:
        L.append(f"| {r.unit_name} | {r.year or '—'} | {r.scope} | {money(r.wage_wan)} | {r.headcount or '—'} | "
                 f"{f'{r.per_capita_wan:.2f}' if r.headcount else '—'} | {money(r.per_capita_yuan, 0) if r.headcount else '—'} | "
                 f"{f'{r.cash_share:.1%}' if r.cash_share is not None else '—'} | {r.sheet} 第 {r.row} 行 |")
    L.append("")
    for r in results:
        L += [f"## {r.unit_name}", "",
              f"- 分子：{money(r.wage_wan)} 万元（{r.sheet} 第 {r.row} 行，表内单位 {r.unit}，口径 {r.scope}）",
              f"- 分母：{r.headcount or '—'} 人（{r.headcount_basis}）",
              (f"- 结论：**{money(r.per_capita_yuan, 0)} 元/年（{r.per_capita_wan:.2f} 万元/年）**"
               if r.headcount else "- 结论：**缺分母，未计算人均**（仅给分子与结构）")]
        if r.items:
            L += ["", "| 科目 | 万元 | 占比 |", "|---|---:|---:|"]
            for name, _ in SUBITEMS:
                if name in r.items:
                    L.append(f"| {name} | {money(r.items[name])} | {r.items[name] / r.wage_wan:.1%} |")
            L.append(f"| **现金性小计** | {money(r.cash_wan)} | {r.cash_wan / r.wage_wan:.1%} |")
            L.append(f"| **单位缴费小计** | {money(r.employer_wan)} | {r.employer_wan / r.wage_wan:.1%} |")
        if r.warnings:
            L += ["", "告警："] + [f"- {w}" for w in r.warnings]
        L.append("")
    return "\n".join(L)


# ── 自检 ──────────────────────────────────────────────────────────
def selftest() -> int:
    import openpyxl

    tmp = Path(tempfile.mkdtemp(prefix="bs_"))
    ok = 0

    def build(path: Path, unit_label: str, value, with_hc: bool, dup: bool):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "支出决算表"
        ws.append(["支出决算表"])
        ws.append([f"单位：{unit_label}"])
        ws.append(["科目编码", "科目名称", "合计", "基本支出", "项目支出"])
        ws.append(["301", "工资福利支出", value, value, "—"])
        ws.append(["30101", "基本工资", 600, 600, "—"])
        ws.append(["30102", "津贴补贴", 900, 900, "—"])
        ws.append(["30108", "机关事业单位基本养老保险缴费", 200, 200, "—"])
        ws.append(["30113", "住房公积金", 150, 150, "—"])
        if dup:
            ws2 = wb.create_sheet("财政拨款支出决算表")
            ws2.append(["一般公共预算财政拨款支出决算表"])
            ws2.append([f"单位：{unit_label}"])
            ws2.append(["科目名称", "合计"])
            ws2.append(["工资福利支出", value])
        if with_hc:
            ws3 = wb.create_sheet("决算说明")
            ws3.append(["本部门年末在职职工人数 120 人，其中行政编制 100 人。"])
        wb.save(path)

    # ① 万元 + 说明里有人数 → 2400/120 = 20 万
    p1 = tmp / "某市税务局2025年度部门决算.xlsx"
    build(p1, "万元", 2400, True, False)
    r1 = analyze(p1, None, "", "", 0.8, False)
    assert abs(r1.per_capita_wan - 20) < 1e-6, r1.per_capita_wan
    assert r1.headcount == 120 and not r1.degraded
    ok += 1

    # ② 元 + 千分位 + 重复表（同值不报警）→ 24,000,000 元 = 2400 万
    p2 = tmp / "某区财政局2025年度部门决算.xlsx"
    build(p2, "元", "24,000,000.00", False, True)
    r2 = analyze(p2, 120, "", "", 0.8, False)
    assert abs(r2.wage_wan - 2400) < 1e-6, r2.wage_wan
    assert abs(r2.per_capita_wan - 20) < 1e-6
    assert sum("多个不同口径" in w for w in r2.warnings) == 0, r2.warnings
    ok += 1

    # ③ 无人无 --headcount → 必须报错退出（不许静默用编制）
    p3 = tmp / "无人数的表.xlsx"
    build(p3, "万元", 1200, False, False)
    try:
        analyze(p3, None, "", "", 0.8, False)
        raise AssertionError("应报错但没有")
    except SystemExit as e:
        assert "在职人数" in str(e), e
    ok += 1

    # ④ 只有编制人数 → 降级 + 告警
    p4 = tmp / "只有编制.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "决算说明"
    ws.append(["核定编制人数 100 人。"])
    ws2 = wb.create_sheet("支出决算表")
    ws2.append(["单位：万元"])
    ws2.append(["科目名称", "合计"])
    ws2.append(["工资福利支出", 1500])
    wb.save(p4)
    r4 = analyze(p4, None, "", "", 0.8, False)
    assert r4.degraded and any("编制人数" in w for w in r4.warnings), r4.warnings
    ok += 1

    # ⑤ 单位识别不到 → 按数量级推断并留痕
    p5 = tmp / "无单位表头.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["科目名称", "合计"])
    ws.append(["工资福利支出", 900])
    wb.save(p5)
    r5 = analyze(p5, 60, "", "", 0.8, False)
    assert r5.unit == "万元" and any("数量级推断" in w for w in r5.warnings)
    ok += 1

    # ⑥ 说明段写法多样：必须取「实有在职」285，不能取「行政编制」260
    p6 = tmp / "实有说明.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "部门基本情况"
    ws.append(["截至2024年12月31日，本单位实有在职人员285人，其中行政编制260人。"])
    ws2 = wb.create_sheet("支出决算表")
    ws2.append(["单位：万元"])
    ws2.append(["科目名称", "合计"])
    ws2.append(["工资福利支出", 5700])
    wb.save(p6)
    r6 = analyze(p6, None, "", "", 0.8, False)
    assert r6.headcount == 285, r6.headcount
    assert abs(r6.per_capita_wan - 20) < 1e-6, r6.per_capita_wan
    ok += 1

    # ⑦ 三栏并排版式：科目编码 30205 不得被当成「绩效工资」的金额
    #    （广东省税务局 2024 年度单位决算 p16 的真实结构）
    p7 = tmp / "三栏并排.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "基本支出决算明细表"
    ws.append(["一般公共预算财政拨款基本支出决算明细表"])
    ws.append(["金额单位：万元"])
    ws.append(["科目代码", "科目名称", "决算数", "科目代码", "科目名称", "决算数"])
    ws.append(["301", "工资福利支出", 1000, "302", "商品和服务支出", 200])
    ws.append(["30101", "基本工资", 400, "30201", "办公费", 50])
    ws.append(["30107", "绩效工资", "", "30205", "水费", 3.71])
    ws.append(["30113", "住房公积金", 100, "30213", "维修(护)费", 2.00])
    ws.append(["30199", "其他工资福利支出", 500, "30214", "租赁费", 1.00])
    wb.save(p7)
    r7 = analyze(p7, 50, "", "", 0.8, False)
    assert "绩效工资" not in r7.items, r7.items.get("绩效工资")
    assert abs(r7.cash_wan + r7.employer_wan - r7.wage_wan) < 0.01, (r7.cash_wan, r7.employer_wan)
    assert abs(r7.per_capita_wan - 20) < 1e-6
    ok += 1

    # ⑧ 千元单位
    p8 = tmp / "千元表.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["单位：千元"])
    ws.append(["科目名称", "合计"])
    ws.append(["工资福利支出", 12000])   # 12000 千元 = 1200 万元
    wb.save(p8)
    r8 = analyze(p8, 60, "", "", 0.8, False)
    assert abs(r8.wage_wan - 1200) < 1e-6, r8.wage_wan
    assert abs(r8.per_capita_wan - 20) < 1e-6
    ok += 1

    # ⑨ 缴费反推：合成一个已知 N=1000、基数 1 万的单位，区间必须包住 1000
    items = {
        "机关事业单位基本养老保险缴费": 1000 * 10000 * 0.16 * 12 / 1e4,   # 1920 万
        "职业年金缴费": 1000 * 10000 * 0.08 * 12 / 1e4,                   # 960 万
        "住房公积金": 1000 * 10000 * 0.10 * 12 / 1e4,                     # 1200 万
        "职工基本医疗保险缴费": 1000 * 10000 * 0.08 * 12 / 1e4,           # 960 万
    }
    est = estimate_headcount(items, social_wage=8000, k_low=1.0, k_high=1.25)
    assert est["ok"] and est["n_low"] <= 1000 <= est["n_high"], (est["n_low"], est["n_high"])
    assert est["overlap"], est["lines"]
    ok += 1

    print(f"✓ selftest 通过：{ok}/9")
    print(render([r1], 0.8))
    print(f"\n（临时目录：{tmp}）")
    return 0


# ── 入口 ──────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="部门决算 → 人均工资福利支出（推算）")
    ap.add_argument("files", nargs="*", help="决算表：.xls/.xlsx/.csv/.pdf/.html，可多个")
    ap.add_argument("--headcount", type=int, default=0, help="在职人数（覆盖自动抽取；多文件时对全部生效）")
    ap.add_argument("--headcounts", default="", help='按文件名分别指定，如 "封开=120,怀集=96"')
    ap.add_argument("--unit", choices=list(UNIT_FACTOR), default="", help="金额单位（默认自动识别）")
    ap.add_argument("--sheet", default="", help="只在指定 sheet 内找（名称包含即可）")
    ap.add_argument("--net-factor", type=float, default=0.8, help="现金性→到手的经验折算系数，默认 0.8")
    ap.add_argument("--json", default="", help="结果写到 JSON（'-' 为 stdout）")
    ap.add_argument("--md", default="", help="结果写到 Markdown")
    ap.add_argument("--no-headcount", action="store_true", help="不要求人数，只输出总额与结构")
    ap.add_argument("--social-wage", type=float, default=0.0,
                    help="当地全口径月平均工资（元），给了就用公积金/社保反推人数区间")
    ap.add_argument("--base-k", default="1.0,2.0", help="人均缴费基数 ÷ 社平工资 的倍数区间，默认 1.0,2.0")
    ap.add_argument("--strict", action="store_true", help="有任何告警即失败")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.files:
        ap.print_help()
        return 2

    hc_map: list[tuple[str, int]] = []
    for seg in re.split(r"[,，]", a.headcounts):
        if "=" in seg:
            k, v = seg.split("=", 1)
            if v.strip().isdigit():
                hc_map.append((k.strip(), int(v)))

    results = []
    for f in a.files:
        p = Path(f)
        if not p.exists():
            print(f"✗ 文件不存在：{f}", file=sys.stderr)
            return 2
        hc = a.headcount or None
        for k, v in hc_map:
            if k and k in p.name:
                hc = v
        k_lo, k_hi = (float(x) for x in (a.base_k.split(",") + ["2.0"])[:2])
        results.append(analyze(p, hc, a.unit, a.sheet, a.net_factor, a.strict,
                               a.no_headcount, a.social_wage, k_lo, k_hi))

    text = render(results, a.net_factor)
    print(text)
    if a.json:
        payload = {"formula": "人均工资福利支出 = 工资福利支出 ÷ 在职人数（推算）",
                   "net_factor": a.net_factor, "results": [r.as_dict() for r in results]}
        blob = json.dumps(payload, ensure_ascii=False, indent=2)
        if a.json == "-":
            print(blob)
        else:
            Path(a.json).write_text(blob, encoding="utf-8")
    if a.md:
        Path(a.md).write_text(render_md(results, a.net_factor), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
