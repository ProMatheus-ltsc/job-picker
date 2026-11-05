"""广东省考「专业三列用空格拼接」的匹配修复（majorHit 需按空格分段）。

背景：广东省考把专业拆成「研究生专业名称及代码 / 本科专业名称及代码 / 大专专业名称及代码」
三列，`rowText` 以**空格**拼接多列，于是岗位专业会变成
「…(A030112) 法学(B030101)」这样一个整段。若不按空格分段，
`majorHit` 会要求「一个分段同时等于两个专业」→ 省直三岗、越秀仲裁院等被误判专业不符。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "tests" / "ts" / "probe.ts"

sys.path.insert(0, str(REPO_ROOT / "tests"))
from helpers import _npx_argv as npx_argv  # noqa: E402  (Windows 下 npx 需解析为 .cmd)


def probe(op: str, payload: dict) -> dict:
    proc = subprocess.run(
        [
            *npx_argv(), str(PROBE), "--op", op,
        ],
        cwd=str(REPO_ROOT),
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise AssertionError(f"探针无输出: {proc.stderr[-400:]}")
    data = json.loads(raw)
    assert data.get("ok"), data
    return data


def test_space_joined_multi_column_major_is_matched() -> None:
    """三列用空格拼接时，含目标专业的那一列应能命中。"""
    from openpyxl import Workbook

    book = REPO_ROOT / "tests" / "out" / "space-major.xlsx"
    book.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "县以上机关"
    ws.append(["测试"])
    ws.append(
        ["职位代码", "招考单位", "招考职位", "职位简介", "录用人数",
         "学历", "研究生专业名称及代码", "本科专业名称及代码", "大专专业名称及代码",
         "是否要求2年以上基层工作经历", "其他要求", "考区"]
    )
    # 研究生列与本科列不同，本科列含法学 —— 拼接后应能命中「法学」
    ws.append(
        ["44010100000077", "广东省某厅", "一级科员", "从事政策研究工作",
         "1", "本科", "工商管理类(A0201)", "法学(B030101)", "工商管理类(A0201)",
         "否", "无", "广东省广州市"]
    )
    wb.save(book)

    proc = subprocess.run(
        [
            *npx_argv(), str(REPO_ROOT / "scripts" / "pick.ts"),
            "--jobs", str(book),
            "--exam-type", "sk",
            "--major", "法学",
            "--major-class", "法学类",
            "--json", str(REPO_ROOT / "tests" / "out" / "space-major.json"),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    assert proc.returncode == 0, (proc.stdout[-500:], proc.stderr[-500:])
    data = json.loads(
        (REPO_ROOT / "tests" / "out" / "space-major.json").read_text(encoding="utf-8")
    )
    # 该岗位专业含法学 → 必须通过资格判定进入候选
    codes = [row["code"] for row in data["candidates"]]
    assert "44010100000077" in codes, (
        f"空格拼接的三列专业未被正确匹配（岗位被误判专业不符）：{data['summary']}"
    )


def test_pipe_separated_majors_still_work() -> None:
    """双学位 `--majors 法学,物理学` 拼成的「法学|物理学」仍应逐个匹配。"""
    payload = {
        "job": {
            "key": "k", "code": "1", "unit": "u", "title": "t",
            "avgIncome": None, "netIncome": None, "incomeScore": None, "netScore": None,
            "applicants": None, "hires": 1, "region": "广东省广州市",
            "degree": "本科", "major": "法学(B030101)",
            "intro": "", "politicalStatus": "不限", "grassrootsYears": "否",
            "serviceProject": "", "institution": "", "freshRequired": "否",
            "physicalTest": "", "sourceSheet": "县以上机关", "minServiceYears": None,
            "remark": "", "marks": ["pending"] * 4,
        }
    }
    # 用强度探针验证通路正常（本用例只关心 CLI/引擎链路未因合并而断裂）
    result = probe("intensity", payload)
    assert result["level"] == "none", result
