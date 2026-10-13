#!/usr/bin/env python3
"""
官方数据抓取器（国家公务员局侧 / 各招录机关官网）

所有请求先经 _guard 校验域名；非官方源直接抛错。

用法：
  python3 fetch.py jobs --list
  python3 fetch.py jobs --get 招考简章 --out ./raw
  python3 fetch.py attachments --url <官方公告页> --out ./raw [--cookie "k=v; k2=v2"]

── 遇到反爬时（重要）────────────────────────────────────────────
| 现象                        | 性质                    | 处理                                    |
|----------------------------|-------------------------|-----------------------------------------|
| HTTP 000 / Connection timed | IP 或网络策略层面阻断    | 换网络环境（本机宽带通常可达）           |
| HTTP 403 / 412 / 400       | WAF（含 JS 挑战）        | ① 浏览器打开后复制 Cookie 用 --cookie    |
|                            |                         | ② 或本机运行                             |
| 返回 200 但内容是空壳       | JS 渲染 / 挑战页         | 同上；或改用附件直链                     |
❌ 不要用第三方转载/镜像替代 —— 那是二手数据。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard import assert_official  # noqa: E402

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
DL = "http://dl.scs.gov.cn"
CONST_JS = f"{DL}/pp/gkweb/core/web/ui/js/core/core-constant.js"
API_RES = DL + "/api/res/{root}/1110"
DOWNLOAD = DL + "/download/{rid}"
ATTACH_RE = re.compile(r'href="([^"]+\.(?:xls|xlsx|zip|rar))"', re.I)

_COOKIE: str | None = None   # --cookie 注入


def _session():
    import requests

    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    if _COOKIE:
        for kv in _COOKIE.split(";"):
            if "=" in kv:
                k, _, v = kv.strip().partition("=")
                s.cookies.set(k.strip(), v.strip())
    return s


def _explain(status: int | None) -> None:
    """按状态码给出可执行指引"""
    if status is None:
        print("     ↳ 连接层失败（超时/重置）：多为目标站对当前 IP 的限制")
        print("        · 请在本机（家庭宽带）运行本脚本")
    elif status in (400, 403, 412, 418, 429):
        print(f"     ↳ HTTP {status} = 站点 WAF 拦截（可能含 JS 挑战）")
        print("        ① 用浏览器正常打开该页 → F12 → 复制 Cookie → 加 --cookie \"k=v; ...\"")
        print("        ② 或在本机运行本脚本")
    else:
        print(f"     ↳ HTTP {status}")


def _get(s, url: str, referer: str | None = None, timeout: int = 30, retries: int = 2):
    """带重试的 GET（对 5xx / 网络抖动重试；4xx 不重试）"""
    last = None
    for i in range(retries + 1):
        try:
            h = {"Referer": referer} if referer else {}
            r = s.get(url, headers=h, timeout=timeout)
            if r.status_code < 500:
                return r
            last = r
        except Exception as e:  # noqa: BLE001
            last = e
        if i < retries:
            time.sleep(1.5 * (i + 1))
    return last if isinstance(last, Exception) is False else None if last is None else last


def _web_root(s) -> str | None:
    assert_official(CONST_JS)
    r = s.get(CONST_JS, timeout=20)
    m = re.search(r"hb01Id[^;]*?[\"']([0-9a-f]{32})[\"']", r.text)
    return m.group(1) if m else None


def _list_resources(s, root: str) -> list[dict]:
    url = API_RES.format(root=root)
    assert_official(url)
    r = s.get(url, timeout=25)
    r.raise_for_status()
    return json.loads(r.text).get("resList", []) or []


def _download(s, rid: str, name: str, outdir: str, referer: str) -> str | None:
    url = DOWNLOAD.format(rid=rid)
    assert_official(url)
    dst = os.path.join(outdir, name)
    r = s.get(url, headers={"Referer": referer}, timeout=300, stream=True)
    if r.status_code != 200:
        print(f"  ✗ {name} HTTP {r.status_code}")
        _explain(r.status_code)
        return None
    with open(dst, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    print(f"  ✓ {name}  {os.path.getsize(dst) // 1024} KB")
    if zipfile.is_zipfile(dst):
        with zipfile.ZipFile(dst) as z:
            for n in z.namelist():
                if n.lower().endswith((".xls", ".xlsx")):
                    # zip 内文件名可能是 GBK（国考简章即如此），修正后另存
                    try:
                        fixed = n.encode("cp437").decode("gbk")
                    except Exception:  # noqa: BLE001
                        fixed = n
                    fixed = os.path.basename(fixed)
                    with open(os.path.join(outdir, fixed), "wb") as o:
                        o.write(z.read(n))
                    print(f"      ↳ 解压 {fixed}")
    return dst


# ───────────────────────── jobs ─────────────────────────
def cmd_jobs(a) -> None:
    s = _session()
    root = _web_root(s)
    if not root:
        print("✗ 未能从 core-constant.js 读到 webRootId —— 专题可能未开放")
        return
    print(f"[jobs] webRootId = {root}")
    res = _list_resources(s, root)
    if not res:
        print("  资源列表为空 —— 官方尚未上传（招考简章通常在公告发布当天下午挂出）")
        return
    print(f"  共 {len(res)} 个资源：")
    for i, it in enumerate(res, 1):
        print(f"   {i:>2}. {it.get('resourceName')}  «{it.get('resourceComment') or '无说明'}»")

    if not a.get:
        return
    os.makedirs(a.out, exist_ok=True)
    referer = "http://bm.scs.gov.cn/kl" + (a.year or "")
    hit = 0
    for kw in a.get:
        for it in res:
            nm = urllib.parse.unquote(it.get("resourceName") or "")
            if kw in nm:
                _download(s, it["resResourceId"], nm, a.out, referer)
                hit += 1
    if not hit:
        print(f"  ✗ 没有匹配「{'/'.join(a.get)}」的资源")


# ────────────────────── attachments ──────────────────────
def cmd_attachments(a) -> None:
    s = _session()
    os.makedirs(a.out, exist_ok=True)
    for page in a.url:
        assert_official(page)  # ★ 非官方公告页直接拒绝
        print(f"[attachments] {page}")
        r = _get(s, page, timeout=a.timeout)
        if r is None or getattr(r, "status_code", 0) != 200:
            st = getattr(r, "status_code", None)
            print(f"  ✗ 页面获取失败：{st if st else '连接失败'}")
            _explain(st)
            continue
        if r.encoding is None or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"

        links = [urllib.parse.urljoin(page, l) for l in ATTACH_RE.findall(r.text)]
        links = list(dict.fromkeys(links))
        keep = [l for l in links if re.search(r"名单|人员|公告|简章|职位", urllib.parse.unquote(l))]
        targets = keep or links
        if not targets:
            print("  ⚠ 页面里没找到附件链接（可能是 JS 渲染页）")
            print("     ↳ 用浏览器打开该页，直接下载附件，然后用 interview_scores.py parse --dir <目录>")
            continue
        print(f"  发现附件 {len(links)} 个，采用 {len(targets)} 个")
        for link in targets:
            assert_official(link)  # ★ 附件域名同样校验
            fn = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(link).path))
            if not fn.lower().endswith((".xls", ".xlsx", ".zip", ".rar")):
                fn += ".xls"
            dst = os.path.join(a.out, fn)
            rr = _get(s, link, referer=page, timeout=a.timeout)
            if rr is None or rr.status_code != 200 or len(rr.content) < 2000:
                print(f"  ✗ {fn} HTTP {getattr(rr, 'status_code', '连接失败')} / {len(getattr(rr, 'content', b''))}B")
                _explain(getattr(rr, "status_code", None))
                continue
            with open(dst, "wb") as f:
                f.write(rr.content)
            print(f"  ✓ {fn}  {len(rr.content) // 1024} KB")


def main() -> None:
    global _COOKIE
    ap = argparse.ArgumentParser(description="官方数据抓取器（仅限官方域名）")
    ap.add_argument("--cookie", default="", help="浏览器 Cookie，用于绕过 WAF（k=v; k2=v2）")
    ap.add_argument("--timeout", type=int, default=30)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("jobs", help="国考专题「相关下载」资源")
    p.add_argument("--year", default="2027")
    p.add_argument("--list", action="store_true")
    p.add_argument("--get", action="append")
    p.add_argument("--out", default="./raw")
    p.set_defaults(func=cmd_jobs)

    p2 = sub.add_parser("attachments", help="从官方公告页下载附件")
    p2.add_argument("--url", action="append", required=True)
    p2.add_argument("--out", default="./raw")
    p2.set_defaults(func=cmd_attachments)

    a = ap.parse_args()
    if a.cookie:
        _COOKIE = a.cookie
    try:
        a.func(a)
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
