#!/usr/bin/env python3
"""unit_budget.py —— 按「岗位所在单位」抓该单位的部门预算 / 决算公开文件，算人力成本。

为什么要有这个脚本
------------------
`budget_salary.py` 解决的是「给我一份决算文件，我算人均」。
但真正要回答「我报这个岗能拿多少」时，文件不会自己找上门：302 个岗位分布在
212 个具体单位（局 / 镇 / 街道 / 法院），每个单位的预算决算散落在**各自**的
市 / 区县政府网站上，栏目路径、分页方式、附件命名全都不一样。

本脚本做三件事：
  1. **定位**：按「市 / 区县」维护栏目地址（SITES），在栏目里按单位名匹配到详情页
  2. **取证**：从详情页取正文 PDF / XLS 附件，落盘存档（原件可回溯）
  3. **解析**：复用 budget_salary.py 的取数逻辑，抽出「工资福利支出」与人数线索

一条铁律
--------
**抓不到就写「未取得」，不许用考区档位冒充单位数据。**
广东省 / 广州市 / 区县的部门预决算公开表，实测**绝大多数不含在职人数**，
所以本脚本的输出分两列：分子（工资福利支出，单位级一手）与分母（人数，能取则取，
取不到就留空并注明该去哪儿取）。绝不拿编制数或社平工资反推值填进分母假装实数。

用法
----
    # 列出某栏目下所有单位（先看清有没有你要的单位）
    python3 unit_budget.py --list 广州市

    # 抓一个单位
    python3 unit_budget.py --unit 广州市 科学技术局

    # 批量：一行一个「栏目关键词<TAB>单位名」
    python3 unit_budget.py --batch units.tsv --out 单位级.xlsx

    # 栏目列表与站点配置
    python3 unit_budget.py --sites
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import budget_salary as BS  # noqa: E402

CACHE = Path.home() / ".codebuddy/skills/job-picker/references/raw/units"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"


# ── 反推人数用的「月缴费基数锚」─────────────────────────────────────
# 机关事业单位缴费基数 = 职工本人应发工资（法定），而应发 ≈ k × 当地非私营在岗职工月均。
# 下表 = 《广东统计年鉴2025》表4-10「在岗职工年平均工资」÷ 12（元/月），一手无假设。
SOCIAL_WAGE: dict[str, int] = {
    "广州": 13704, "深圳": 14755, "珠海": 11642, "汕头": 8382,
    "佛山": 9653, "韶关": 9239, "河源": 8091, "梅州": 8343,
    "惠州": 8840, "汕尾": 8681, "东莞": 8766, "中山": 9094,
    "江门": 8533, "阳江": 8855, "湛江": 9208, "茂名": 8700,
    "肇庆": 8860, "清远": 8663, "潮州": 8188, "揭阳": 7532,
    "云浮": 8795,
}
K_LOW, K_HIGH = 1.0, 2.0        # 机关缴费基数 ÷ 非私营社平 的倍数区间（基层≈1.0，市级机关可到2.0）

def social_for(site: str) -> float:
    """按站点名（市/区县）查锚点；区县查不到退回所属市。"""
    for k in sorted(SOCIAL_WAGE, key=len, reverse=True):
        if k in site:
            return SOCIAL_WAGE[k]
    return 0.0


# ── 站点配置 ────────────────────────────────────────────────────────
# key  = 地市 / 区县名（匹配时按长度倒序，优先长名）
# 值    = {"budget": 部门预算栏目模板, "final": 部门决算栏目模板, "year": 已确认可用年度}
# {year} 会被替换成 2026 / 2025 …
SITES: dict[str, dict] = {
    "广州市": {
        "budget": "https://www.gz.gov.cn/zwgk/zdly/czzj/bmyjshsgjf/ys/{year}n/",
        "final": "https://www.gz.gov.cn/zwgk/zdly/czzj/bmyjshsgjf/js/{year}n/",
        "year": 2026,
        "year_final": 2025,
    },
    "东莞市": {
        "budget": "https://www.dg.gov.cn/zwgk/zdlyxxgk/czzj/bmyjs/",
        "final": "https://www.dg.gov.cn/zwgk/zdlyxxgk/czzj/bmjs/",
        "year": 2026,
        "year_final": 2025,
    },
    "湛江市": {
        "budget": "https://www.zhanjiang.gov.cn/zdlyxxgk/czyjshsg/bmyjs/bmys/",
        "final": "https://www.zhanjiang.gov.cn/zdlyxxgk/czyjshsg/bmyjs/bmjs/2024/",
        "year": 2026,
        "year_final": 2024,
    },
    "汕尾市": {
        "budget": "https://www.shanwei.gov.cn/shanwei/swzdly/sgjf/bmyjs/bmys/",
        "final": "https://www.shanwei.gov.cn/shanwei/swzdly/sgjf/bmyjs/bmjs/",
        "year": 2026,
        "year_final": 2024,
    },
    "郁南县": {
        "budget": "https://www.gdyunan.gov.cn/ynxrmzf/zwgk/zdlyxxgkzl/czzjxxgk/bmyjs/index.html",
        "final": "",
        "year": 2026,
    },
    "高州市": {
        "budget": "http://www.gaozhou.gov.cn/zdlyxxgk/czzj/",
        "final": "",
        "year": 2026,
    },
}


def http_get(url: str, timeout: int = 30) -> str:
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "-A", UA, url],
        capture_output=True,
    )
    raw = r.stdout
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def http_download(url: str, dest: Path, timeout: int = 90) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        return True
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "-A", UA, "-o", str(dest), url],
        capture_output=True,
    )
    return dest.exists() and dest.stat().st_size > 1024


# ── 栏目页 → 单位条目 ───────────────────────────────────────────────
@dataclass
class Entry:
    title: str
    url: str
    year: int | None = None
    kind: str = ""          # 预算 / 决算


def _abs(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"(https?://[^/]+)", base)
        return (m.group(1) if m else "") + href
    return base.rsplit("/", 1)[0] + "/" + href


def list_entries(index_url: str, max_pages: int = 12, kind: str = "") -> list[Entry]:
    """抓栏目页（自动跟随 index_N.html 分页），返回全部「标题 + 详情页」。"""
    out: list[Entry] = []
    seen: set[str] = set()
    urls = [index_url]
    for p in range(2, max_pages + 1):
        urls.append(re.sub(r"(/|index\.html$)", f"/index_{p}.html" if p else r"\1",
                           index_url.rstrip("/") + "/" if not index_url.endswith(".html") else index_url))
    # 更稳的做法：先解析首页里的 index_N.html 链接
    head = http_get(index_url)
    paged = sorted(set(re.findall(r'href="([^"]*index_(\d+)\.html)"', head)),
                   key=lambda x: int(x[1]))
    urls = [index_url] + [_abs(index_url, h) for h, _ in paged]

    for u in urls:
        html = head if u == index_url else http_get(u)
        if not html:
            continue
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*(?:title="([^"]*)")?[^>]*>(.*?)</a>',
                             html, re.S):
            href, title, inner = m.group(1), m.group(2) or "", m.group(3)
            text = re.sub(r"<[^>]+>", "", inner)
            text = re.sub(r"\s+", "", text)
            name = title or text
            if len(name) < 6 or "预决算" in name and "部门" not in name:
                continue
            if not re.search(r"(部门|单位).{0,12}(预算|决算)", name):
                continue
            full = _abs(u, href)
            if full in seen:
                continue
            seen.add(full)
            y = re.search(r"(20\d\d)\s*年?度?", name)
            out.append(Entry(name, full, int(y.group(1)) if y else None,
                             "决算" if "决算" in name else "预算"))
        time.sleep(0.2)
    return out


# 单位名归一：去掉行政区前缀、"人民"、括号补充、委员会/局 等后缀差异
_STRIP_PREFIX = ("广州市", "广东省")
_SUFFIX = ("局", "委员会", "办公室", "人民政府", "管理", "人民")


def norm_unit(s: str) -> str:
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 去括号补充名
    s = re.sub(r"[\s　·、,，]", "", s)
    for p in _STRIP_PREFIX:
        s = s.replace(p, "")
    s = s.replace("人民政府", "")
    return s


def match_entries(entries: list[Entry], unit: str, kind: str = "") -> list[Entry]:
    """按归一化名称匹配。先精确后包含——包含匹配容易撞（如「财政局」vs「财政国库支付中心」）。"""
    key = norm_unit(unit)
    if not key:
        return []
    exact, fuzzy = [], []
    for e in entries:
        if kind and e.kind != kind:
            continue
        t = norm_unit(e.title)
        t = re.sub(r"20\d\d年?度?", "", t)
        t = t.replace("部门", "").replace("单位", "")
        if t.startswith(key) or key == t:
            exact.append(e)
        elif key in t:
            fuzzy.append(e)
    return exact or fuzzy


# ── 详情页 → 附件 ──────────────────────────────────────────────────
def attachments(post_url: str) -> list[tuple[str, str]]:
    html = http_get(post_url)
    out = []
    for m in re.finditer(r'href="([^"]+\.(?:pdf|xls|xlsx|doc|docx|zip))"[^>]*>([^<]*)', html, re.I):
        out.append((re.sub(r"\s+", "", m.group(2)), _abs(post_url, m.group(1))))
    if not out:                                     # 有些站点附件在 iframe / data 属性
        for m in re.finditer(r'["\']([^"\']+\.pdf)["\']', html, re.I):
            out.append(("", _abs(post_url, m.group(1))))
    return out


def pick_main_pdf(atts: list[tuple[str, str]], unit: str) -> tuple[str, str] | None:
    """挑正文：优先标题里带单位名且带「预算 / 决算」的，其次无标题的第一个。"""
    if not atts:
        return None
    scored = []
    for name, url in atts:
        s = 0
        if "绩效" in name or "目标表" in name or "评分" in name:
            s -= 5
        if re.search(r"(部门|单位).{0,10}(预算|决算)", name):
            s += 3
        if unit and norm_unit(unit)[:6] in norm_unit(name):
            s += 2
        if not name:
            s += 1                                  # 站点惯例：无标题的第一个 = 正文
        scored.append((s, name, url))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1], scored[0][2]



# ── 到手换算（与 salary_official.py 同口径：含双边公积金、不含社保）──
_CASH_KEYS = ["基本工资", "津贴补贴", "奖金", "伙食补助费", "绩效工资", "医疗费", "其他工资福利支出"]

def _income_tax(taxable: float) -> float:
    for cap, rate, ded in [(36000, 0.03, 0), (144000, 0.10, 2520), (300000, 0.20, 16920),
                           (420000, 0.25, 31920), (660000, 0.30, 52920), (960000, 0.35, 85920),
                           (float("inf"), 0.45, 181920)]:
        if taxable <= cap:
            return max(0.0, taxable * rate - ded)
    return 0.0

def net_from_gross(gross: float) -> float:
    """应发工资(元/年) → 到手含双边公积金(元/年)。扣个人社保14%、个税，双边公积金各12%加回。"""
    social = gross * 0.14
    fund_p = gross * 0.12
    taxable = max(0.0, gross - social - fund_p - 60000 - 24000)
    tax = _income_tax(taxable)
    return gross - social - tax + 2 * fund_p


# ── 解析 ────────────────────────────────────────────────────────────
@dataclass
class UnitResult:
    unit: str
    site: str
    year: int | None
    kind: str
    wage_wan: float | None
    headcount: int | None
    hc_basis: str
    scope: str
    unit_basis: str
    sheet: str
    row: int
    items: dict = field(default_factory=dict)
    hc_low: float | None = None
    hc_high: float | None = None
    overlap: bool = False
    est_lines: list = field(default_factory=list)
    per_capita_wan_low: float | None = None
    per_capita_wan_high: float | None = None
    cash_wan: float | None = None
    salary_wan_low: float | None = None
    salary_wan_high: float | None = None
    net_wan_low: float | None = None
    net_wan_high: float | None = None
    source_page: str = ""
    source_file: str = ""
    note: str = ""


HC_WIDE = [
    r"(?:年末|年底)?在职(?:职工|人员|人数)(?:共|为|计)?\s*[:：]?\s*(\d{1,5})\s*人",
    r"实有(?:在职)?(?:人员|人数|职工)(?:共|为|计)?\s*[:：]?\s*(\d{1,5})\s*人",
    r"(?:干部职工|在编人员|在岗职工)(?:共|为|计)?\s*(\d{1,5})\s*人",
    r"人员(?:总数|合计)\s*[:：]?\s*(\d{1,5})\s*人",
    r"共\s*(\d{1,5})\s*人[，,]?\s*其中",
]


def wide_headcount(sheets: list[BS.Sheet]) -> tuple[int | None, str]:
    """在宽口径里找人数——比 budget_salary 的 HC_PATTERNS 多认几种写法。"""
    n, basis, _ = BS.find_headcount(sheets)
    if n:
        return n, basis
    blob = "\n".join(
        " ".join(str(c) for c in row if c is not None)
        for sh in sheets for row in sh.rows
    )
    for pat in HC_WIDE:
        m = re.search(pat, blob)
        if m and 1 <= int(m.group(1)) <= 200_000:
            return int(m.group(1)), f"宽口径命中「{m.group(0)[:30]}」"
    return None, "未披露"


def analyze_unit(site: str, unit: str, kind: str, save: bool = True) -> UnitResult:
    cfg = SITES[site]
    tpl = cfg.get("final" if kind == "决算" else "budget") or ""
    if not tpl:
        return UnitResult(unit, site, None, kind, None, None, "该站点未配置此栏目", "", "", "", 0, note="无栏目")
    url = tpl.format(year=cfg.get("year_final" if kind == "决算" else "year", 2026))
    entries = list_entries(url, kind=kind)
    if not entries:
        return UnitResult(unit, site, None, kind, None, None, "栏目为空或抓取失败", "", "", "", 0,
                          source_page=url, note="栏目无条目")
    hits = match_entries(entries, unit)
    if not hits:
        return UnitResult(unit, site, None, kind, None, None, "栏目内未找到该单位", "", "", "", 0,
                          source_page=url, note=f"栏目共 {len(entries)} 条，无匹unit")
    e = hits[0]
    atts = attachments(e.url)
    got = pick_main_pdf(atts, unit)
    if not got:
        return UnitResult(unit, site, e.year, kind, None, None, "详情页无附件", "", "", "", 0,
                          source_page=e.url, note="详情页无 PDF/XLS")
    name, file_url = got
    fn = file_url.rsplit("/", 1)[-1] or "file.pdf"
    ext = "." + fn.rsplit(".", 1)[-1].lower() if "." in fn else ".pdf"
    dest = CACHE / f"{site}_{unit}_{e.year or ''}_{kind}{ext}"
    if not http_download(file_url, dest):
        return UnitResult(unit, site, e.year, kind, None, None, "附件下载失败", "", "", "", 0,
                          source_page=e.url, source_file=file_url, note="下载失败")
    try:
        sheets = BS.load_sheets(dest)
    except SystemExit as exc:                       # budget_salary 用 SystemExit 报错
        return UnitResult(unit, site, e.year, kind, None, None, f"解析失败：{exc}", "", "", "", 0,
                          source_page=e.url, source_file=file_url, note="解析失败")

    cands, _warns = BS.find_wage_total(sheets)
    if not cands:
        return UnitResult(unit, site, e.year, kind, None, None, "未找到工资福利支出行", "", "", "", 0,
                          source_page=e.url, source_file=file_url, note="无 301 科目")
    best = cands[0]
    wage_wan, _unit, unit_basis = BS.resolve_wan(sheets, best)
    items_raw, _ = BS.find_subitems(sheets, best.sheet)
    factor = BS.UNIT_FACTOR[_unit]
    items = {k: v * factor / 10_000 for k, v in items_raw.items()}
    hc, hc_basis = wide_headcount(sheets)
    cash_wan = sum(items.get(k, 0) for k in _CASH_KEYS)
    # ── 人数反推：公开表不披露人数 → 用公积金/社保缴费额反推（用户指定路径）──
    hc_low = hc_high = None
    overlap = False
    est_lines: list = []
    pc_low = pc_high = None
    if hc is None:
        sw = social_for(site)
        if sw > 0:
            est = BS.estimate_headcount(items, sw, K_LOW, K_HIGH)
            if est.get("ok"):
                hc_low, hc_high = est["n_low"], est["n_high"]
                overlap = est["overlap"]
                est_lines = est["lines"]
                hc_basis = (f"缴费反推 {hc_low:,.0f}~{hc_high:,.0f} 人"
                            f"（锚：非私营月均 {sw:,.0f} 元 × {K_LOW}~{K_HIGH}）")
                pc_low = wage_wan / hc_high if hc_high else None
                pc_high = wage_wan / hc_low if hc_low else None
            else:
                hc_basis = f"反推失败：{est.get('reason', '')}"
        else:
            hc_basis = "未配置社平锚点，无法反推"
    # ── 人均应发（现金性≈工资总额≈应发）与到手含公积金 ──
    sal_low = sal_high = net_low = net_high = None
    if cash_wan and (hc or hc_low):
        n_lo = hc or hc_low
        n_hi = hc or hc_high
        if hc:                       # 直接取到人数 → 点值
            n_lo = n_hi = hc
        sal_low = cash_wan / n_hi if n_hi else None          # 万元/人/年（现金性÷人数）
        sal_high = cash_wan / n_lo if n_lo else None
        net_low = net_from_gross(sal_low * 10000) / 10000 if sal_low else None
        net_high = net_from_gross(sal_high * 10000) / 10000 if sal_high else None
    return UnitResult(
        unit=unit, site=site, year=e.year, kind=kind,
        wage_wan=wage_wan, headcount=hc,
        hc_basis=f"{hc_basis}" if hc else hc_basis,
        scope=BS.detect_scope(best.sheet, sheets), unit_basis=unit_basis,
        sheet=best.sheet, row=best.row,
        items=items, hc_low=hc_low, hc_high=hc_high, overlap=overlap,
        est_lines=est_lines, per_capita_wan_low=pc_low, per_capita_wan_high=pc_high,
        cash_wan=cash_wan, salary_wan_low=sal_low, salary_wan_high=sal_high,
        net_wan_low=net_low, net_wan_high=net_high,
        source_page=e.url, source_file=file_url,
        note="" if (hc or hc_low) else "分母缺失且反推失败",
    )


# ── 输出 ────────────────────────────────────────────────────────────
def render(rs: list[UnitResult]) -> str:
    L = []
    L.append("单位级部门预决算取数（分子=单位一手，分母=能取则取）")
    L.append("=" * 96)
    cols = [("招考单位", 20), ("工资福利支出(万元)", 15), ("人数", 11),
            ("人均人力成本(万/年)", 16), ("人均应发(万/年)", 14), ("到手含公积金(万/年)", 16)]
    L.append("".join(BS.pad(h, w, "right" if i > 0 else "left") for i, (h, w) in enumerate(cols)))
    L.append("-" * 96)
    ok = 0
    for r in rs:
        if r.wage_wan is not None:
            ok += 1
        if r.headcount:
            hc_txt = str(r.headcount)
        elif r.hc_low:
            hc_txt = f"{r.hc_low:,.0f}~{r.hc_high:,.0f}"
        else:
            hc_txt = "—"
        def rng(lo, hi):
            if lo is None:
                return "—"
            return f"{lo:.1f}~{hi:.1f}" if abs(hi - lo) > 0.05 else f"{lo:.1f}"
        row = [
            (r.unit[:18], "left"),
            (BS.money(r.wage_wan) if r.wage_wan is not None else "—", "right"),
            (hc_txt, "right"),
            (rng(r.per_capita_wan_low, r.per_capita_wan_high), "right"),
            (rng(r.salary_wan_low, r.salary_wan_high), "right"),
            (rng(r.net_wan_low, r.net_wan_high), "right"),
        ]
        L.append("".join(BS.pad(v, w, a) for (v, a), (_, w) in zip(row, cols)))
        if r.wage_wan is None:
            L.append(f"    └ {r.note}")
        elif r.est_lines:
            for ln in r.est_lines:
                if ln.get("跳过"):
                    L.append(f"      · {ln['线索']}：{ln['跳过']}")
                else:
                    L.append(f"      · {ln['线索']} {BS.money(ln['金额(万元)'])} 万元 → "
                             f"{ln['N下界']:,.0f}~{ln['N上界']:,.0f} 人")
            if not r.overlap:
                L.append("      ⚠ 三线无交集 → 存在非在编/基数触顶/统缴，反推不可信")
    L.append("")
    L.append(f"取到分子：{ok}/{len(rs)}；直接取到人数：{sum(1 for r in rs if r.headcount)}/{len(rs)}；"
             f"反推人数：{sum(1 for r in rs if r.hc_low)}/{len(rs)}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="按岗位所在单位抓部门预决算并解析")
    ap.add_argument("--sites", action="store_true", help="打印站点配置")
    ap.add_argument("--list", metavar="SITE", help="列出该站点部门预决算栏目下的全部条目")
    ap.add_argument("--unit", nargs=2, metavar=("SITE", "UNIT"), help="抓一个单位")
    ap.add_argument("--kind", choices=["预算", "决算"], default="决算", help="优先预算还是决算（默认决算）")
    ap.add_argument("--batch", help="批量：每行 SITE<TAB>UNIT")
    ap.add_argument("--json", help="结果写 JSON")
    a = ap.parse_args()

    if a.sites:
        for k, v in SITES.items():
            print(f"{k:<6} 预算 {v.get('budget') or '—'}")
            print(f"{'':<6} 决算 {v.get('final') or '—'}")
        return 0

    if a.list:
        cfg = SITES.get(a.list)
        if not cfg:
            print(f"✗ 未配置站点：{a.list}（已配置：{', '.join(SITES)}）", file=sys.stderr)
            return 2
        for kind, key in (("决算", "final"), ("预算", "budget")):
            tpl = cfg.get(key) or ""
            if not tpl:
                continue
            url = tpl.format(year=cfg.get("year_final" if kind == "决算" else "year", 2026))
            es = list_entries(url, kind=kind)
            print(f"\n== {a.list} {kind}（{url}）共 {len(es)} 条")
            for e in es:
                print(f"  {e.title[:56]:<58} {e.url[:88]}")
        return 0

    jobs: list[tuple[str, str]] = []
    if a.unit:
        jobs.append((a.unit[0], a.unit[1]))
    if a.batch:
        for ln in Path(a.batch).read_text(encoding="utf-8").splitlines():
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = re.split(r"\t+|\s{2,}", ln.strip())
            if len(parts) >= 2:
                jobs.append((parts[0].strip(), parts[1].strip()))
    if not jobs:
        ap.print_help()
        return 2

    rs = []
    for site, unit in jobs:
        if site not in SITES:
            print(f"✗ 未配置站点：{site}", file=sys.stderr)
            continue
        r = analyze_unit(site, unit, a.kind)
        rs.append(r)
        print(f"  {'✓' if r.wage_wan is not None else '✗'} {unit}  "
              f"{BS.money(r.wage_wan) if r.wage_wan is not None else r.note}")

    print()
    print(render(rs))
    if a.json:
        Path(a.json).write_text(json.dumps([r.__dict__ for r in rs], ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print(f"\nJSON → {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
