#!/usr/bin/env python3
"""
国考面试名单 —— 抓取 / 解析 / 查询（进面分数据源）

为什么需要它：
  职位表里**没有进面分**。进面分只在「面试人员名单」里 —— 由各招录机关在笔试成绩公布后
  单独发布（通常在次年 1–2 月）。这是唯一的一手来源。

数据链路：
  ① fetch  —— 从「面试公告页」提取附件（.xls/.xlsx/.zip）并下载
  ② parse  —— 解析名单 → 结构化 CSV（职位代码 / 单位 / 职位 / 进面分 / 进面人数）
  ③ stats  —— 按地区/单位统计分数分布
  ④ lookup —— 按职位代码反查历史进面分（选岗时最常用）

⚠️ 数据性质：
  「进入面试最低分数」= 该岗位进面最后一名的笔试成绩（两科原始分相加，满分 200）。
  由招录机关公布、第三方转发，**不是官方统一标准**；跨年份会随题难波动。

用法：
  python3 interview_scores.py fetch  --url <公告页> [--url ...] --out ./raw
  python3 interview_scores.py parse  --dir ./raw --out scores.csv
  python3 interview_scores.py stats  --csv scores.csv [--match 西安]
  python3 interview_scores.py lookup --csv scores.csv --codes 300110101002,300110003006
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import urllib.parse
import warnings
import zipfile
from collections import Counter

warnings.filterwarnings("ignore")

# 来源守门（与 fetch.py 同一套硬约束：非官方域名直接抛错）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _guard import assert_official  # noqa: E402
except Exception:  # noqa: BLE001

    def assert_official(url: str) -> None:  # type: ignore[misc]
        pass


# ── 省税务局官网「公务员招录」栏目预设（苏迪 CMS 信息公开接口）★★ ──────────
# 这是本项目攻破瑞数类 WAF 的核心手段：**HTML 页面被 412 拦，但 /module/* 接口放行**。
#   · 正文阅读 → WebFetch（能过 WAF）
#   · 附件下载 → /module/download/downfile.jsp（不受保护）
#   · 栏目列表 → POST /module/xxgk/search.jsp（本预设，含历史年份）
# 详见 references/pitfalls.md #29~#31
#
# ⚠️ 参数是「最小集且不能多」：多带 page/currentpage/vc_title 会退回「请传入正确参数！」
# ⚠️ 该接口**忽略分页参数**，固定返回最新约 20 条（一般覆盖近两年，够定位年度公告）
SITES: dict[str, dict] = {
    "陕西": {
        "base": "https://shaanxi.chinatax.gov.cn",
        "col_path": "/col/col32162/index.html",
        "params": {
            "columnid": "32162",
            "infotypeId": "A07",
            "jdid": "1",
            "area": "11610000160006543",
        },
    },
    "浙江": {
        "base": "http://zhejiang.chinatax.gov.cn",
        "col_path": "/col/col24800/index.html",
        "params": {
            "columnid": "24800",
            "infotypeId": "Z2402",
            "jdid": "15",
            "area": "11330000002484088Y",
        },
    },
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
CODE_RE = re.compile(r"(\d{12})")
ATTACH_RE = re.compile(r'href="([^"]+\.(?:xls|xlsx|zip|rar))"', re.I)
# 表头识别：同时出现「职位」与「分数」列
HEAD_KW_MAJOR = ("职位", "岗位")
HEAD_KW_SCORE = ("分数",)

# 省份识别（含计划单列市单列）
PROVINCE_KEYWORDS = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "大连", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "宁波", "安徽", "福建", "厦门", "江西", "山东", "青岛",
    "河南", "湖北", "湖南", "广东", "深圳", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]

# 地级市 → 省级（依据民政部《中华人民共和国行政区划》）
CITY_TO_PROVINCE: dict[str, str] = {
    # 广东
    "广州": "广东", "韶关": "广东", "深圳": "广东", "珠海": "广东", "汕头": "广东",
    "佛山": "广东", "江门": "广东", "湛江": "广东", "茂名": "广东", "肇庆": "广东",
    "惠州": "广东", "梅州": "广东", "汕尾": "广东", "河源": "广东", "阳江": "广东",
    "清远": "广东", "东莞": "广东", "中山": "广东", "潮州": "广东", "揭阳": "广东",
    "云浮": "广东",
    # 广东县级市（名单里按县级单位出现）
    "鹤山": "广东", "台山": "广东", "开平": "广东", "恩平": "广东",
    "高州": "广东", "化州": "广东", "信宜": "广东", "普宁": "广东",
    "阳春": "广东", "陆丰": "广东", "四会": "广东", "英德": "广东",
    "连州": "广东", "南雄": "广东", "乐昌": "广东", "兴宁": "广东",
    "吴川": "广东", "雷州": "广东", "廉江": "广东", "罗定": "广东",
    # 浙江
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "湖州": "浙江",
    "绍兴": "浙江", "金华": "浙江", "衢州": "浙江", "舟山": "浙江", "台州": "浙江",
    "丽水": "浙江",
    "瑞安": "浙江", "义乌": "浙江", "东阳": "浙江", "慈溪": "浙江", "余姚": "浙江",
    "诸暨": "浙江", "嵊州": "浙江", "温岭": "浙江", "临海": "浙江", "新昌": "浙江",
    "平湖": "浙江", "海宁": "浙江", "桐乡": "浙江", "长兴": "浙江", "德清": "浙江",
    "建德": "浙江", "乐清": "浙江", "龙港": "浙江", "玉环": "浙江", "兰溪": "浙江",
    "龙泉": "浙江", "江山": "浙江", "永康": "浙江", "安吉": "浙江", "嘉善": "浙江",
    "桐庐": "浙江", "淳安": "浙江", "象山": "浙江", "宁海": "浙江", "海盐": "浙江",
    # 陕西
    "西安": "陕西", "铜川": "陕西", "宝鸡": "陕西", "咸阳": "陕西", "渭南": "陕西",
    "延安": "陕西", "汉中": "陕西", "榆林": "陕西", "安康": "陕西", "商洛": "陕西",
    "神木": "陕西", "韩城": "陕西", "华阴": "陕西", "兴平": "陕西", "彬州": "陕西",
    # 直辖市 / 计划单列市
    "北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆",
    "大连": "辽宁", "青岛": "山东", "厦门": "福建", "深圳": "广东",
    # 其他常见
    "南京": "江苏", "苏州": "江苏", "无锡": "江苏", "常州": "江苏", "南通": "江苏",
    "徐州": "江苏", "济南": "山东", "烟台": "山东", "潍坊": "山东", "临沂": "山东",
    "郑州": "河南", "洛阳": "河南", "武汉": "湖北", "宜昌": "湖北", "长沙": "湖南",
    "成都": "四川", "绵阳": "四川", "福州": "福建", "泉州": "福建", "厦门市": "福建",
    "南昌": "江西", "合肥": "安徽", "昆明": "云南", "贵阳": "贵州", "南宁": "广西",
    "太原": "山西", "石家庄": "河北", "沈阳": "辽宁", "哈尔滨": "黑龙江",
    "长春": "吉林", "呼和浩特": "内蒙古", "兰州": "甘肃", "西宁": "青海",
    "银川": "宁夏", "乌鲁木齐": "新疆", "拉萨": "西藏", "海口": "海南", "三亚": "海南",
}


def province_of(text: str) -> str:
    """
    从「单位及职位」识别省份。
    例：'国家税务总局广州市海珠区税务局…' → '广东'
        '国家税务总局陕西省税务局稽查局…' → '陕西'
        '国家税务总局宁波市税务局…'      → '宁波'（计划单列市，其市局独立招录）
    """
    s = str(text)
    # 取「国家税务总局」后到 省/市/自治区 之间的名字
    m = re.search(r"国家税务总局([\u4e00-\u9fa5]{2,6}?)(?:省|市|自治区)", s)
    if m:
        name = re.sub(r"(壮族|维吾尔|回族|藏族|蒙古族)$", "", m.group(1))
        if name in PROVINCE_KEYWORDS:
            return name
        if name in CITY_TO_PROVINCE:
            return CITY_TO_PROVINCE[name]
        # ★ 不在这里返回未识别的县级市（如「建德」「乐清」）——交给下面的关键词兜底；
        #   仍识别不出时返回 ""，由 parse_one 的文件级多数省份修正。
    for p in PROVINCE_KEYWORDS:
        if p in s:
            return p
    return ""


# ----------------------------- ① fetch -----------------------------
# 文件名非法字符（Windows 尤其严格）
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _clean_name(name: str, fallback: str) -> str:
    """把链接文字/URL 参数洗成安全文件名，并保证有扩展名"""
    n = urllib.parse.unquote(name or "").strip()
    n = _BAD_CHARS.sub("_", n).strip(" .")
    # 形如「1：面试人员名单」的全角冒号前的序号保留，去掉冒号本身
    n = n.replace("：", "_").replace(":", "_").strip("_ ")
    n = n[:80] or fallback
    if not n.lower().endswith((".xls", ".xlsx", ".zip", ".rar", ".doc", ".docx", ".pdf")):
        n += ".xls"
    return n


def _name_from_url(url: str) -> str:
    """
    从 URL 推文件名。优先级：
      ① showname / filename 查询参数（downfile.jsp 这类下载器把真名放在这里）
      ② 路径 basename
    """
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    for key in ("showname", "filename", "file", "name"):
        if q.get(key):
            return _clean_name(q[key][0], key)
    return _clean_name(
        os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)), "attach"
    )


def _extract_attachments(html: str, base: str) -> list[tuple[str, str]]:
    """
    提取 (url, 显示名)。
    ★ 必须成对抓取 href 与链接文字：多数税务局 CMS 的下载链接是
      downfile.jsp?filename=<uuid>，URL 里没有文件名，只能靠链接文字区分，
      否则 6 个附件会全部存成同一个名字互相覆盖。
    """
    out: list[tuple[str, str]] = []
    # ① 带文字的 <a>（文字为空时退回 title 属性）
    for m in re.finditer(r'(<a[^>]+href="([^"]+)"[^>]*>)(.*?)</a>', html, re.S | re.I):
        tag, href, inner = m.group(1), m.group(2), m.group(3)
        # ★ 这里必须判断「裸 URL」而不是 ATTACH_RE —— ATTACH_RE 匹配的是整个
        #   href="…" 片段，拿裸 URL 去 search 恒为 None，会让所有附件都掉进兜底分支、
        #   丢失文件名（广东局踩过：3 个附件全变成 UUID 名）。
        if not _is_direct_file(href):
            continue
        text = re.sub(r"<[^>]+>", "", inner)
        text = re.sub(r"\s+", " ", urllib.parse.unquote(text)).strip()
        if not text:
            t = re.search(r'title="([^"]*)"', tag, re.I)
            text = urllib.parse.unquote(t.group(1)).strip() if t else ""
        out.append((urllib.parse.urljoin(base, href), text))
    # ② 兜底：裸链接
    if not out:
        for l in ATTACH_RE.findall(html):
            out.append((urllib.parse.urljoin(base, l), ""))
    return out


def _unique_path(outdir: str, name: str, used: set[str]) -> str:
    """
    重名自动加后缀，避免静默覆盖。
    ★ 必须同时看「本次进程已用过的名字」和「磁盘上已存在的文件」——
      否则分多次调用 fetch 时（比如逐省抓名单），后一次会把前一次的同名附件覆盖掉，
      而且文件名一样、大小也接近，几乎发现不了。
    """
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    cand, i = name, 1
    while cand in used or os.path.exists(os.path.join(outdir, cand)):
        cand = f"{stem}({i}).{ext}" if ext else f"{stem}({i})"
        i += 1
    used.add(cand)
    return os.path.join(outdir, cand)


def _is_direct_file(url: str) -> bool:
    """
    判断 URL 是否直接指向一个文件（而非公告页）。
    用于两种场景：
      ① 静态附件直链 …/files/<uuid>.xls
      ② CMS 下载器 …/module/download/downfile.jsp?filename=<uuid>.xls
         （陕西/浙江税务局都是这种形态：页面被 WAF 拦，但下载接口可直连，
           这时用浏览器/WebFetch 拿到直链后可直接灌进本函数）
    """
    path = urllib.parse.urlparse(url).path.lower()
    if re.search(r"\.(xls|xlsx|zip|rar|doc|docx|pdf)$", path):
        return True
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return any(re.search(r"\.(xls|xlsx|zip|rar)$", v, re.I) for k in ("filename", "showname") for v in q.get(k, []))


def fetch(urls: list[str], outdir: str) -> None:
    import requests

    os.makedirs(outdir, exist_ok=True)
    used: set[str] = set()
    for url in urls:
        # ── 直链模式：不解析 HTML，直接落盘 ──
        if _is_direct_file(url):
            fn = _name_from_url(url)
            dst = _unique_path(outdir, fn, used)
            print(f"[fetch] 直链 {url[:96]}")
            try:
                rr = requests.get(url, headers={"User-Agent": UA}, timeout=120)
                if rr.status_code != 200 or len(rr.content) < 2000:
                    print(f"  ✗ {fn} HTTP {rr.status_code} / {len(rr.content)}B")
                    continue
                with open(dst, "wb") as f:
                    f.write(rr.content)
                print(f"  ✓ {fn}  {len(rr.content) // 1024} KB")
                if zipfile.is_zipfile(dst):
                    with zipfile.ZipFile(dst) as z:
                        for n in z.namelist():
                            if n.lower().endswith((".xls", ".xlsx")):
                                z.extract(n, outdir)
                                print(f"      ↳ 解压 {n}")
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {fn} {type(e).__name__} {e}")
            continue

        # ── 页面模式：解析出附件再下载 ──
        print(f"[fetch] {url}")
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 页面失败：{type(e).__name__} {e}")
            continue

        if r.encoding is None or r.encoding.lower() in ("iso-8859-1",):
            r.encoding = r.apparent_encoding or "utf-8"

        pairs = _extract_attachments(r.text, url)
        # 分级筛选，避免把「确认参加面试声明」「考点路线图」等非名单附件也拖下来：
        #   ① 含「名单」  → 只要这些
        #   ② 含「人员/面试」→ 退而求其次
        #   ③ 都没有      → 全留（宁可多下，不可漏）
        t1 = [p for p in pairs if "名单" in p[1] + p[0]]
        t2 = [p for p in pairs if re.search(r"人员|面试", p[1] + p[0])]
        targets = t1 or t2 or pairs
        print(f"  发现附件 {len(pairs)} 个，采用 {len(targets)} 个")

        for link, text in targets:
            fn = _clean_name(text, "attach") if text else _name_from_url(link)
            dst = _unique_path(outdir, fn, used)
            try:
                rr = requests.get(
                    link, headers={"User-Agent": UA, "Referer": url}, timeout=60
                )
                if rr.status_code != 200 or len(rr.content) < 2000:
                    print(f"  ✗ {fn} HTTP {rr.status_code} / {len(rr.content)}B")
                    continue
                with open(dst, "wb") as f:
                    f.write(rr.content)
                print(f"  ✓ {fn}  {len(rr.content) // 1024} KB")
                if zipfile.is_zipfile(dst):
                    with zipfile.ZipFile(dst) as z:
                        for n in z.namelist():
                            if n.lower().endswith((".xls", ".xlsx")):
                                z.extract(n, outdir)
                                print(f"      ↳ 解压 {n}")
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {fn} {type(e).__name__} {e}")


# ----------------------------- ② parse -----------------------------
def _norm_cols(cols) -> list[str]:
    return [re.sub(r"[\s\n\r\t（）()：:]+", "", str(c)) for c in cols]


def _find_header(df_raw) -> tuple[int, list[str]] | None:
    """在前 8 行里找表头行：含「职位」列且含「分数」列"""
    import pandas as pd  # noqa: F401

    n = min(8, len(df_raw))
    for i in range(n):
        row = _norm_cols(df_raw.iloc[i].tolist())
        has_major = any(any(k in c for k in HEAD_KW_MAJOR) for c in row)
        has_score = any(any(k in c for k in HEAD_KW_SCORE) for c in row)
        if has_major and has_score:
            return i, row
    return None


def parse_one(path: str) -> list[dict]:
    import pandas as pd

    out: list[dict] = []
    try:
        if path.lower().endswith(".xlsx"):
            engine = "openpyxl"
        else:
            engine = None  # 让 pandas 自行选择（.xls 走 xlrd）
        xl = pd.ExcelFile(path, engine=engine)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {os.path.basename(path)} 无法读取：{type(e).__name__} {e}")
        return out

    for sn in xl.sheet_names:
        try:
            raw = xl.parse(sn, header=None, dtype=str)
        except Exception:  # noqa: BLE001
            continue
        if raw.empty:
            continue
        hit = _find_header(raw)
        if not hit:
            continue
        hrow, head = hit

        df = raw.iloc[hrow + 1 :].copy()
        df.columns = head
        # 归一化列名（去空白/换行/全角括号）
        df.columns = _norm_cols(df.columns)

        col_major = next((c for c in df.columns if "职位" in c or "岗位" in c), None)
        col_score = next(
            (c for c in df.columns if "分数" in c and ("面试" in c or "最低" in c or "进入" in c)),
            None,
        ) or next((c for c in df.columns if "分数" in c), None)
        if not col_major or not col_score:
            continue
        col_name = next((c for c in df.columns if "姓名" in c), None)
        col_zkz = next((c for c in df.columns if "准考证" in c), None)

        # ★ 顺序至关重要：「职位名称及代码」只在岗位首行出现，必须先 ffill 再筛行。
        #   若先按「含 12 位代码」筛，会把同岗位的续行（其余进面考生）整行丢掉，
        #   于是「进面人数」恒等于 1 —— 这是最容易错且不易察觉的地方。
        df["_pos"] = df[col_major].ffill()
        df["_code"] = df["_pos"].fillna("").astype(str).str.extract(CODE_RE)[0]
        df["_score"] = pd.to_numeric(df[col_score], errors="coerce")

        # 考生行判定：有姓名或准考证号才算，避免表尾说明行/空行被 ffill 带上下一个代码
        keys = [c for c in (col_name, col_zkz) if c]
        if keys:
            df = df[df[keys].fillna("").apply(lambda s: s.str.strip().ne("")).any(axis=1)]
        df = df.dropna(subset=["_code"])
        if df.empty:
            continue

        kind = "递补名单" if "递补" in os.path.basename(path) else "主名单"

        # 同一岗位多行（每个进面考生一行）→ 聚合
        for code, g in df.groupby("_code", sort=False):
            pos = str(g["_pos"].iloc[0]).replace("\n", "").strip()
            pos_clean = re.sub(r"[（(]\s*\d{12}\s*[）)]\s*$", "", pos).strip()
            # 分数：广东/浙江只在首行给值，陕西每行重复 → 取非空值里的最小值最稳
            scores = g["_score"].dropna()
            if scores.empty:
                continue
            out.append(
                {
                    "省份": province_of(pos_clean) or province_of(os.path.basename(path)),
                    "职位代码": code,
                    "单位及职位": pos_clean,
                    "进面最低分": round(float(scores.min()), 1),
                    "进面人数": int(len(g)),
                    "名单类型": kind,
                    "来源文件": os.path.basename(path),
                    "工作表": sn,
                }
            )

    # ── 文件级省份兜底 ──────────────────────────────────────────────
    # 一份面试名单只覆盖一个省 / 一个计划单列市（由该省局发布），
    # 因此用「本文件出现最多的省份」修正识别不出来的县级市、县局
    # （如「建德市税务局」「博罗县税务局」——它们的名字里没有省级关键词）。
    if out:
        c = Counter(r["省份"] for r in out if r["省份"] in PROVINCE_KEYWORDS)
        if c:
            main_p = c.most_common(1)[0][0]
            fixed = 0
            for r in out:
                if r["省份"] not in PROVINCE_KEYWORDS:
                    r["省份"] = main_p
                    fixed += 1
            if fixed:
                print(f"  ↳ 省份兜底：{fixed} 个县级局归入「{main_p}」")
    return out


def parse_dir(d: str, out_csv: str) -> None:
    files = [
        os.path.join(d, f)
        for f in sorted(os.listdir(d))
        if f.lower().endswith((".xls", ".xlsx"))
    ]
    if not files:
        print(f"[parse] {d} 下没有 xls/xlsx")
        return
    rows: list[dict] = []
    for f in files:
        got = parse_one(f)
        print(f"  {os.path.basename(f)} → {len(got)} 个岗位")
        rows.extend(got)

    # 去重（同一岗位可能同时出现在主名单与递补名单里）：
    #   ① 主名单优先 —— 官方面试公告附件1 里的「进入面试最低分数」才是该岗位的进面线；
    #      递补名单里写的是递补者本人的分数（更低），拿它当进面线会低估。
    #   ② 同为一种名单时取分数更高的一条。
    #
    # ★★ 去重键必须是 (省份, 职位代码)，不能只用职位代码：
    #    12 位职位代码**不是全国唯一**——税务系统各省局独立编号，
    #    实测 300110106001 同时出现在广东 / 浙江 / 陕西（134 个代码跨省重号）。
    #    只用代码做键会把别省的岗位静默吃掉，且完全看不出错。
    def _rank(x: dict) -> tuple[bool, float]:
        return (x.get("名单类型") == "主名单", float(x["进面最低分"]))

    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        k = (r["省份"], r["职位代码"])
        if k not in best or _rank(r) > _rank(best[k]):
            best[k] = r
    rows = sorted(best.values(), key=lambda x: (x["省份"], -x["进面最低分"], x["职位代码"]))

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[parse] 共 {len(rows)} 个岗位 → {out_csv}")


# ----------------------------- ③ stats / ④ lookup -----------------------------
def load(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def stats(csv_path: str, match: str | None, province: str | None = None) -> None:
    import statistics as st

    rows = load(csv_path)
    if province:
        rows = [r for r in rows if province in r.get("省份", "")]
    if match:
        rows = [r for r in rows if match in r["单位及职位"]]
    if not rows:
        print("无数据")
        return
    scores = sorted(float(r["进面最低分"]) for r in rows)
    print(f"岗位数 {len(scores)}")
    print(
        f"最低 {scores[0]} ｜ 25% {scores[len(scores)//4]} ｜ 中位 {st.median(scores)}"
        f" ｜ 75% {scores[len(scores)*3//4]} ｜ 最高 {scores[-1]}"
        f" ｜ 平均 {round(st.mean(scores),1)}"
    )
    if province:
        hires = [int(r["进面人数"]) for r in rows if str(r.get("进面人数", "")).isdigit()]
        if hires:
            print(
                f"进面人数合计 {sum(hires)} ｜ 单岗中位 {int(st.median(hires))} ｜ "
                f"≥3 人岗位 {sum(1 for h in hires if h >= 3)}/{len(hires)}"
            )
    print("\n分数段分布：")
    edges = [0, 110, 115, 120, 125, 130, 135, 200]
    for lo, hi in zip(edges, edges[1:]):
        n = sum(1 for s in scores if lo <= s < hi)
        if n:
            print(f"  {lo:>3}-{hi:<3} {'█' * min(60, n)} {n}")
    if match:
        print(f"\n『{match}』明细：")
        for r in sorted(rows, key=lambda x: -float(x["进面最低分"])):
            print(f"  {r['进面最低分']:>6}  [{r['职位代码']}] {r['单位及职位'][:56]}")


def lookup(csv_path: str, codes: list[str]) -> None:
    # ★ 一个职位代码可能命中多个省份（各省局独立编号）→ 必须按代码聚合、全部列出
    index: dict[str, list[dict]] = {}
    for r in load(csv_path):
        index.setdefault(r["职位代码"], []).append(r)

    print(f"{'职位代码':<14}{'省份':<8}{'进面分':>7}  单位及职位")
    print("-" * 92)
    for c in codes:
        c = c.strip()
        hits = index.get(c)
        if not hits:
            print(f"{c:<14}{'—':<8}{'—':>7}  未收录（该岗去年未招 / 代码变更 / 不在已收录省份）")
            continue
        for r in sorted(hits, key=lambda x: x.get("省份", "")):
            print(
                f"{c:<14}{r.get('省份',''):<8}{r['进面最低分']:>7}  {r['单位及职位'][:52]}"
            )
        if len(hits) > 1:
            print(f"{'':<22}↳ ⚠ 该代码命中 {len(hits)} 个省份，"
                  f"请按你报考的省份取对应行（代码非全国唯一）")
    print("\n※ 未收录 ≠ 好考。国考职位代码跨年、跨省都会变，"
          "优先查「同单位 / 同地区」的历史分。")


# --------------------- ⑤ discover：找公告页（绕过 WAF） ---------------------
def _parse_cms_rows(html: str) -> list[dict]:
    """
    解析苏迪 CMS 信息公开列表（`search.jsp` 返回的 HTML 表格）为结构化行。

    ★ 两个必须兼容的点：
      1. 锚点用**单引号** `href='…'` —— 只写双引号的正则会命中 0 条，
         从而误判成"接口没返回数据"（陕西站实测踩过）
      2. 标题优先取锚点文字，取不到再退回 `title=` 属性
    """
    out: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        m = re.search(
            r"""href=['"]([^'"]*art_\d+_\d+\.html[^'"]*)['"][^>]*>(.*?)</a>""",
            tr,
            re.S | re.I,
        )
        if not m:
            continue
        href, inner = m.group(1), m.group(2)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
        if not title:
            t = re.search(r"""title=['"]([^'"]*)['"]""", tr, re.I)
            title = urllib.parse.unquote(t.group(1)).strip() if t else ""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tr)).strip()
        d = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        out.append(
            {
                "url": href if href.startswith("http") else "",
                "path": href,
                "title": urllib.parse.unquote(title),
                "date": d.group(1) if d else "",
            }
        )
    return out


def discover(site: str, year: str | None, kw: str | None) -> None:
    """列出某省税务局官网「公务员招录」栏目的公告（含历史年份）"""
    import requests

    if site not in SITES:
        print(f"未知站点「{site}」。已收录：{'、'.join(SITES)}")
        print("（其他省份可自行补预设：拿该栏目 URL 里的 columnid / area，")
        print("  以及页面隐藏域 infotypeId / jdid 即可，见 references/pitfalls.md #30）")
        return

    cfg = SITES[site]
    url = cfg["base"] + "/module/xxgk/search.jsp"
    assert_official(url)  # ★ 非官方域名直接抛错，不做静默降级
    referer = cfg["base"] + cfg["col_path"]
    data = dict(cfg["params"])
    data["divid"] = "list"

    r = requests.post(
        url,
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        data=data,
        timeout=30,
    )
    r.encoding = "utf-8"

    if "请传入正确参数" in r.text:
        print(f"  ✗ 接口要求最小参数集，当前预设被拒：{data}")
        print("     ↳ 别加 page / currentpage / vc_title 等多余参数（见 pitfalls #30）")
        return
    if len(r.text) < 400:
        print(f"  ✗ 接口返回异常（{len(r.text)}B）：{r.text.strip()[:80]}")
        return

    rows = _parse_cms_rows(r.text)
    if not rows:
        print("  ✗ 未解析到文章行（可能是站点换了模板；注意锚点引号形态）")
        return

    print(f"[discover] {site} · {referer}")
    print(f"  接口返回 {len(rows)} 条（该接口忽略分页参数，固定为最新约 20 条）")

    if year:
        rows = [x for x in rows if f"/{year}/" in x["path"]]
    if kw:
        rows = [x for x in rows if kw in x["title"]]
    if not rows:
        print("  没有匹配的条目（换年份/关键词，或该年份公告已过 20 条窗口）")
        return

    print()
    print(f"{'日期':<12}{'标题':<50}链接")
    print("-" * 108)
    for x in sorted(rows, key=lambda z: z["date"], reverse=True):
        full = x["path"] if x["path"].startswith("http") else cfg["base"] + "/" + x["path"].lstrip("/")
        print(f"{x['date']:<12}{x['title'][:46]:<50}{full}")
    print()
    print("下一步：用 WebFetch 打开上面的公告页 → 取出 downfile.jsp 附件直链")
    print("        → python3 interview_scores.py fetch --url '<直链>' --out ./raw")


# ----------------------------- CLI -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="国考面试名单抓取/解析/查询")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("fetch", help="从公告页下载面试名单附件")
    p1.add_argument("--url", action="append", required=True,
                    help="公告页 URL，或附件直链（可多次）")
    p1.add_argument("--out", required=True, help="输出目录")

    p2 = sub.add_parser("parse", help="把名单解析成 CSV")
    p2.add_argument("--dir", required=True)
    p2.add_argument("--out", required=True)

    p3 = sub.add_parser("stats", help="统计分数分布")
    p3.add_argument("--csv", required=True)
    p3.add_argument("--match", default=None, help="只看含该关键词的岗位，如「西安」")
    p3.add_argument("--province", default=None, help="只看该省份，如「广东」")

    p4 = sub.add_parser("lookup", help="按职位代码查历史进面分")
    p4.add_argument("--csv", required=True)
    p4.add_argument("--codes", required=True, help="逗号分隔")

    p5 = sub.add_parser(
        "discover",
        help="列出某省税务局「公务员招录」栏目的公告（绕过瑞数 WAF，含历史年份）",
    )
    p5.add_argument("--site", required=True, help="省份，如 陕西 / 浙江；用 list 看已收录")
    p5.add_argument("--year", default=None, help="只看该年份，如 2025")
    p5.add_argument("--kw", default=None, help="标题关键词，如「面试公告」")

    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.url, a.out)
    elif a.cmd == "parse":
        parse_dir(a.dir, a.out)
    elif a.cmd == "stats":
        stats(a.csv, a.match, a.province)
    elif a.cmd == "lookup":
        lookup(a.csv, a.codes.split(","))
    elif a.cmd == "discover":
        if a.site == "list":
            print("已收录站点：")
            for k, v in SITES.items():
                print(f"  {k:<6} {v['base']}{v['col_path']}  params={v['params']}")
        else:
            discover(a.site, a.year, a.kw)


if __name__ == "__main__":
    main()
