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

warnings.filterwarnings("ignore")

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
        return name
    for p in PROVINCE_KEYWORDS:
        if p in s:
            return p
    return ""


# ----------------------------- ① fetch -----------------------------
def fetch(urls: list[str], outdir: str) -> None:
    import requests

    os.makedirs(outdir, exist_ok=True)
    for url in urls:
        host = urllib.parse.urlparse(url).netloc
        print(f"[fetch] {url}")
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 页面失败：{type(e).__name__} {e}")
            continue

        # 页面编码兜底
        if r.encoding is None or r.encoding.lower() in ("iso-8859-1",):
            r.encoding = r.apparent_encoding or "utf-8"
        links = ATTACH_RE.findall(r.text)
        links = [urllib.parse.urljoin(url, l) for l in links]
        # 只留含「名单/人员」字样的；若都没有则全留
        named = [l for l in links if re.search(r"名单|人员|面试", urllib.parse.unquote(l))]
        targets = named or links
        print(f"  发现附件 {len(links)} 个，采用 {len(targets)} 个")

        for link in dict.fromkeys(targets):
            fn = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(link).path)) or "attach"
            if not fn.lower().endswith((".xls", ".xlsx", ".zip", ".rar")):
                fn += ".xls"
            dst = os.path.join(outdir, fn)
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

        # 只保留含 12 位职位代码的行（过滤标题/空行/说明行）
        df = df[df[col_major].fillna("").str.contains(r"\d{12}", regex=True)]
        if df.empty:
            continue

        # 「职位名称及代码」通常只在首行出现 → 前向填充
        df["_pos"] = df[col_major].ffill()
        df["_code"] = df["_pos"].str.extract(CODE_RE)[0]
        df["_score"] = pd.to_numeric(df[col_score], errors="coerce")
        df = df.dropna(subset=["_code", "_score"])

        # 同一岗位多行（每个进面考生一行）→ 聚合
        for code, g in df.groupby("_code"):
            pos = str(g["_pos"].iloc[0]).replace("\n", "").strip()
            pos_clean = re.sub(r"[（(]\s*\d{12}\s*[）)]\s*$", "", pos).strip()
            out.append(
                {
                    "省份": province_of(pos_clean) or province_of(os.path.basename(path)),
                    "职位代码": code,
                    "单位及职位": pos_clean,
                    "进面最低分": round(float(g["_score"].median()), 1),
                    "进面人数": len(g),
                    "来源文件": os.path.basename(path),
                    "工作表": sn,
                }
            )
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

    # 去重（同代码保留分数更高的一条 = 主名单优先于递补名单）
    best: dict[str, dict] = {}
    for r in rows:
        k = r["职位代码"]
        if k not in best or r["进面最低分"] > best[k]["进面最低分"]:
            best[k] = r
    rows = sorted(best.values(), key=lambda x: (-x["进面最低分"], x["职位代码"]))

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[parse] 共 {len(rows)} 个岗位 → {out_csv}")


# ----------------------------- ③ stats / ④ lookup -----------------------------
def load(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def stats(csv_path: str, match: str | None) -> None:
    import statistics as st

    rows = load(csv_path)
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
    index = {r["职位代码"]: r for r in load(csv_path)}
    print(f"{'职位代码':<14}{'进面分':>7}  单位及职位")
    print("-" * 84)
    for c in codes:
        c = c.strip()
        r = index.get(c)
        if r:
            print(f"{c:<14}{r['进面最低分']:>7}  {r['单位及职位'][:56]}")
        else:
            print(f"{c:<14}{'—':>7}  未收录（该岗去年未招 / 代码变更）")
    print("\n※ 未收录 ≠ 好考。国考职位代码跨年有延续性但非固定，"
          "优先查「同单位 / 同地区」的历史分。")


# ----------------------------- CLI -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="国考面试名单抓取/解析/查询")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("fetch", help="从公告页下载面试名单附件")
    p1.add_argument("--url", action="append", required=True, help="公告页 URL（可多次）")
    p1.add_argument("--out", required=True, help="输出目录")

    p2 = sub.add_parser("parse", help="把名单解析成 CSV")
    p2.add_argument("--dir", required=True)
    p2.add_argument("--out", required=True)

    p3 = sub.add_parser("stats", help="统计分数分布")
    p3.add_argument("--csv", required=True)
    p3.add_argument("--match", default=None, help="只看含该关键词的岗位，如「西安」")

    p4 = sub.add_parser("lookup", help="按职位代码查历史进面分")
    p4.add_argument("--csv", required=True)
    p4.add_argument("--codes", required=True, help="逗号分隔")

    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.url, a.out)
    elif a.cmd == "parse":
        parse_dir(a.dir, a.out)
    elif a.cmd == "stats":
        stats(a.csv, a.match)
    elif a.cmd == "lookup":
        lookup(a.csv, a.codes.split(","))


if __name__ == "__main__":
    main()
