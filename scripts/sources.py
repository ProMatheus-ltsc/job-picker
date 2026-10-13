#!/usr/bin/env python3
"""
进面分数据 —— 官方获取入口清单

用途：当脚本抓不到某个站（WAF / 网络限制）时，把**官方入口地址**给你，
      你手动下载后放到一个目录，再用 interview_scores.py parse 解析。

用法：
  python3 sources.py list                  # 全部入口
  python3 sources.py list --province 陕西    # 指定省
  python3 sources.py list --reachable       # 只列沙箱已验证可达的
"""
from __future__ import annotations

import argparse

# ── 最优入口：一次拿到全量 ────────────────────────────────────────
TOP_ENTRY = """
╔════════════════════════════════════════════════════════════════════╗
║ 【最优入口】国家公务员局 → 相关下载 → 面试人员名单.xlsx（全量）        ║
╚════════════════════════════════════════════════════════════════════╝
  地址：http://bm.scs.gov.cn/kl<年份>      → 页面右下「相关下载」
  文件：中央机关及其直属机构<年份>年度考试录用公务员面试人员名单.xlsx
        （一个文件覆盖**所有系统、所有省份**，不必逐省下载）
  时点：笔试后**次年 1–2 月**挂出（如 2026 年度 = 2026 年 1–2 月）
  同栏目还有：
        · 调剂进入面试人员名单.xls      （调剂岗）
        · 补充录用进入面试人员名单.xls  （补录岗）
  字段：职位代码 / 用人司局 / 招考职位 / 最低面试分数 / 准考证号 / 姓名

  ✅ 沙箱实测：该站可访问，文件可下载（`fetch.py jobs --list/get`）
"""

# ── 分省入口（各招录机关官网）────────────────────────────────────
# reach: 沙箱实测（y=可达 / n=被拦 / s=需 Cookie / ?=未测）
PROVINCES: list[dict] = [
    {"name": "北京",      "host": "beijing.chinatax.gov.cn",      "reach": "?"},
    {"name": "天津",      "host": "tianjin.chinatax.gov.cn",      "reach": "?"},
    {"name": "河北",      "host": "hebei.chinatax.gov.cn",        "reach": "?"},
    {"name": "山西",      "host": "shanxi.chinatax.gov.cn",       "reach": "s"},
    {"name": "内蒙古",    "host": "neimenggu.chinatax.gov.cn",    "reach": "y"},
    {"name": "辽宁",      "host": "liaoning.chinatax.gov.cn",     "reach": "y"},
    {"name": "大连",      "host": "dalian.chinatax.gov.cn",       "reach": "?"},
    {"name": "吉林",      "host": "jilin.chinatax.gov.cn",        "reach": "?"},
    {"name": "黑龙江",    "host": "heilongjiang.chinatax.gov.cn", "reach": "n"},
    {"name": "上海",      "host": "shanghai.chinatax.gov.cn",     "reach": "?"},
    {"name": "江苏",      "host": "jiangsu.chinatax.gov.cn",      "reach": "y"},
    {"name": "浙江",      "host": "zhejiang.chinatax.gov.cn",     "reach": "y"},
    {"name": "宁波",      "host": "ningbo.chinatax.gov.cn",       "reach": "n",
     "section": "xxgk/tzgg/sstz/", "note": "412 WAF，需 Cookie 或本机"},
    {"name": "安徽",      "host": "anhui.chinatax.gov.cn",        "reach": "y"},
    {"name": "福建",      "host": "fujian.chinatax.gov.cn",       "reach": "n"},
    {"name": "厦门",      "host": "xiamen.chinatax.gov.cn",       "reach": "?"},
    {"name": "江西",      "host": "jiangxi.chinatax.gov.cn",      "reach": "y"},
    {"name": "山东",      "host": "shandong.chinatax.gov.cn",     "reach": "n"},
    {"name": "青岛",      "host": "qingdao.chinatax.gov.cn",      "reach": "?"},
    {"name": "河南",      "host": "henan.chinatax.gov.cn",        "reach": "y"},
    {"name": "湖北",      "host": "hubei.chinatax.gov.cn",        "reach": "n"},
    {"name": "湖南",      "host": "hunan.chinatax.gov.cn",        "reach": "n"},
    {"name": "广东",      "host": "guangdong.chinatax.gov.cn",    "reach": "y",
     "section": "gdsw/ryzl/", "note": "已验证：公告页附件可直接下载"},
    {"name": "深圳",      "host": "shenzhen.chinatax.gov.cn",     "reach": "?"},
    {"name": "广西",      "host": "guangxi.chinatax.gov.cn",      "reach": "y"},
    {"name": "海南",      "host": "hainan.chinatax.gov.cn",       "reach": "?"},
    {"name": "重庆",      "host": "chongqing.chinatax.gov.cn",    "reach": "s"},
    {"name": "四川",      "host": "sichuan.chinatax.gov.cn",      "reach": "n"},
    {"name": "贵州",      "host": "guizhou.chinatax.gov.cn",      "reach": "?"},
    {"name": "云南",      "host": "yunnan.chinatax.gov.cn",       "reach": "y"},
    {"name": "西藏",      "host": "xizang.chinatax.gov.cn",       "reach": "?"},
    {"name": "陕西",      "host": "shaanxi.chinatax.gov.cn",      "reach": "n",
     "note": "TCP 超时（沙箱网络策略）；本机通常可达"},
    {"name": "甘肃",      "host": "gansu.chinatax.gov.cn",        "reach": "n"},
    {"name": "青海",      "host": "qinghai.chinatax.gov.cn",      "reach": "?"},
    {"name": "宁夏",      "host": "ningxia.chinatax.gov.cn",      "reach": "?"},
    {"name": "新疆",      "host": "xinjiang.chinatax.gov.cn",     "reach": "?"},
]

MARK = {"y": "✅可达", "n": "❌被拦", "s": "⚠️需Cookie", "?": "  未测"}


def cmd_list(a) -> None:
    print(TOP_ENTRY)
    rows = PROVINCES
    if a.province:
        rows = [p for p in rows if a.province in p["name"]]
    if a.reachable:
        rows = [p for p in rows if p["reach"] == "y"]
    if not rows:
        print(f"没有匹配的省份：{a.province}")
        return

    print("┌" + "─" * 74 + "┐")
    print("│ 【分省入口】各省税务局官网 → 「公务员招录 / 通知公告」栏目 → 面试公告附件      │")
    print("└" + "─" * 74 + "┘")
    print(f"{'省份':<8}{'状态':<12}地址")
    print("-" * 86)
    for p in rows:
        sec = p.get("section", "")
        url = f"https://{p['host']}/{sec}"
        note = f"  ← {p['note']}" if p.get("note") else ""
        print(f"{p['name']:<8}{MARK[p['reach']]:<12}{url}{note}")
    print()
    print("⚠️ 状态列为**沙箱环境**实测，仅供判断脚本能否自动抓；")
    print("   你自己的网络环境（家庭宽带）通常比沙箱宽松，被拦的省份多数可访问。")
    print()
    print("下载后怎么用：")
    print("  1) 把 .xls/.xlsx 放进同一个目录，如 ~/Downloads/gk-interview/")
    print("  2) python3 interview_scores.py parse --dir <该目录> --out scores.csv")
    print("  3) python3 interview_scores.py stats --csv scores.csv --match 西安")
    print("  4) python3 interview_scores.py lookup --csv scores.csv --codes <职位代码>")


def main() -> None:
    ap = argparse.ArgumentParser(description="进面分官方获取入口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="列出官方下载入口")
    p.add_argument("--province", default="")
    p.add_argument("--reachable", action="store_true", help="只列沙箱可达的")
    p.set_defaults(func=cmd_list)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
