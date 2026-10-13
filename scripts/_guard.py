#!/usr/bin/env python3
"""
来源守门（__guard__）—— 保证「禁止二手数据」不是口号而是代码约束

所有抓取脚本在发起请求前必须调用 assert_official(url)。
非官方域名直接拒绝执行，不存在"绕过开关"。
"""
from __future__ import annotations

import urllib.parse

# ── 官方域名（后缀匹配）────────────────────────────────────────
# gov.cn 覆盖：chinatax.gov.cn / moe.gov.cn / stats.gov.cn / ndrc.gov.cn /
#              mohrss.gov.cn / customs.gov.cn / mof.gov.cn / 各省政府站 …
OFFICIAL_SUFFIXES = (
    ".gov.cn",
    "gov.cn",
    "scs.gov.cn",       # 国家公务员局（独立域名）
    ".scs.gov.cn",
    "dl.scs.gov.cn",
    "bm.scs.gov.cn",
)

# ── 第三方（命中即拒绝，且提示替代来源）────────────────────────
THIRD_PARTY_HINTS: dict[str, str] = {
    "huatu": "华图教育",
    "offcn": "中公教育",
    "fenbi": "粉笔",
    "jinbiaochi": "金标尺",
    "eduu": "教育宝/上岸鸭",
    "gwy.com": "上岸鸭公考",
    "sohu": "搜狐转载",
    "toutiao": "今日头条转载",
    "baijiahao": "百家号",
    "zhihu": "知乎",
    "xiaohongshu": "小红书",
    "tieba": "贴吧",
    "163.com": "网易转载",
    "sina": "新浪转载",
    "qq.com": "腾讯转载",
}


class SourceViolation(RuntimeError):
    """使用了非官方数据源"""


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().split(":")[0]


def is_official(url: str) -> bool:
    """仅 gov.cn / scs.gov.cn 视为官方"""
    h = host_of(url)
    if not h:
        return False
    for bad in THIRD_PARTY_HINTS:
        if bad in h:
            return False
    return any(h == s.lstrip(".") or h.endswith(s) for s in OFFICIAL_SUFFIXES)


def assert_official(url: str) -> None:
    """非官方源 → 抛错。调用方不应捕获后继续。"""
    h = host_of(url)
    if is_official(url):
        return

    hit = next((v for k, v in THIRD_PARTY_HINTS.items() if k in h), None)
    hint = (
        f"检测到第三方来源「{hit}」。\n"
        "  请改用发布机关官网：\n"
        "    · 职位表 / 公告 / 合格线 → http://bm.scs.gov.cn/kl<年份>\n"
        "    · 面试名单（进面分）    → 各招录机关官网「公务员招录 / 通知公告」栏目\n"
        "    · 部门预算 / 决算       → 各单位官网「预算公开 / 决算公开」栏目"
        if hit
        else f"域名 {h} 不在官方白名单内。"
    )
    raise SourceViolation(f"拒绝抓取非官方来源：{url}\n  {hint}")


def warn_if_third_party(url: str) -> None:
    """宽松检查（用于只读展示，不阻止）"""
    if not is_official(url):
        h = host_of(url)
        hit = next((v for k, v in THIRD_PARTY_HINTS.items() if k in h), None)
        print(f"  ⚠ 非官方来源{f'（{hit}）' if hit else ''}：{h} —— 结论中不得引用其数据")


if __name__ == "__main__":
    import sys

    for u in sys.argv[1:]:
        print(f"{'✅ 官方' if is_official(u) else '⛔ 非官方'}  {u}")
