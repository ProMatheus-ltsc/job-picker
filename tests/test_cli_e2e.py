"""TC-001 / TC-006 / TC-014 / TC-015 / TC-016：CLI 端到端用例。

这些用例跑真实的 `scripts/pick.ts`（而不是探针），因为 CLI 层自己也有逻辑：
参数校验、退出码、文件落盘、stdout 与报告的一致性。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import fixture, load_json, out_path, require_tsx, run_cli

GD = "gd-2026-jobs.xlsx"


def pick(*extra: str):
    return run_cli(["--jobs", str(fixture(GD)), *extra])


# ── TC-001 强度筛查落盘 ─────────────────────────────────────────


def test_heavy_jobs_excluded_from_candidates() -> None:
    """TC-001：判 heavy 的岗位进入 excludedByIntensity，不进 candidates。"""
    require_tsx()
    target = out_path("pick-sk.json")
    proc = pick(
        "--exam-type", "sk",
        "--cities", "广州",
        "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
        "--json", str(target),
    )
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    data = load_json(target)

    excluded = data["excludedByIntensity"]
    assert excluded, "没有排除任何 heavy 岗位"
    excluded_codes = {row["code"] for row in excluded}
    candidate_codes = {row["code"] for row in data["candidates"]}
    assert not (excluded_codes & candidate_codes), "heavy 岗位同时出现在候选里"

    # 两个「资格通过且强度 heavy」的验收岗必须被排除。
    # 江埔派出所（44010200000001）在资格判定阶段就因「需体能测评」降级为 warn，
    # 不属于候选池，因此不会进入 excludedByIntensity；它的 heavy 判定由
    # tests/test_intensity.py::test_acceptance_post_jiangpu_police 覆盖。
    assert {"44010100000004", "44010600000001"} <= excluded_codes, excluded_codes
    # 每个候选的强度等级都不得是 heavy
    for row in data["candidates"]:
        assert row["intensity"]["level"] != "heavy", row


def test_keep_heavy_switch_restores_jobs() -> None:
    """--keep-heavy 时 heavy 岗位回到候选（用于"我就想看看有哪些值班岗"）。"""
    require_tsx()
    target = out_path("pick-keep-heavy.json")
    proc = pick(
        "--exam-type", "sk", "--cities", "广州", "--keep-heavy",
        "--json", str(target),
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    data = load_json(target)
    levels = {row["code"]: row["intensity"]["level"] for row in data["candidates"]}
    assert "44010100000004" in levels, levels
    assert levels["44010100000004"] == "heavy", levels


# ── TC-014 范围外提示 ───────────────────────────────────────────


def test_report_contains_scope_notice() -> None:
    """TC-014：--cities 广州,深圳 时报告出现范围外提示小节。"""
    require_tsx()
    report = out_path("report-scope.md")
    proc = pick(
        "--exam-type", "sk", "--cities", "广州,深圳",
        "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
        "--report-out", str(report),
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    text = report.read_text(encoding="utf-8")
    assert "范围外提示" in text, text[-800:]
    assert "广州" in text and "深圳" in text, text[-800:]


def test_stdout_also_shows_scope_notice() -> None:
    """范围外提示不只在文件里，stdout 也要有（用户直接看终端）。"""
    require_tsx()
    proc = pick("--exam-type", "sk", "--cities", "广州")
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert "范围外提示" in proc.stdout, proc.stdout[-600:]


# ── TC-016 报告模板与口径声明 ───────────────────────────────────


def test_report_has_caliber_and_five_sections() -> None:
    """TC-016：报告含口径声明（μ=67、σ=3.5）与五段。"""
    require_tsx()
    report = out_path("report.md")
    proc = pick(
        "--exam-type", "sk", "--cities", "广州",
        "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
        "--report-out", str(report),
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    text = report.read_text(encoding="utf-8")
    assert "判断口径声明" in text
    assert "67" in text and "3.5" in text
    for section in ("## 结论", "## 依据", "## 数据表", "## 局限", "## 待核"):
        assert section in text, f"缺少 {section}"


def test_report_pending_lists_missing_inputs() -> None:
    """不给 μ/σ 时，待核小节必须说明概率未计算（而不是静默留空）。"""
    require_tsx()
    report = out_path("report-noprob.md")
    proc = pick("--exam-type", "sk", "--cities", "广州", "--report-out", str(report))
    assert proc.returncode == 0, proc.stderr[-1000:]
    text = report.read_text(encoding="utf-8")
    pending = text.split("## 待核")[1].split("## ⚠️")[0]
    assert "μ" in pending or "sigma" in pending or "概率" in pending, pending


# ── TC-015 散点图落盘 ───────────────────────────────────────────


def test_scatter_html_written() -> None:
    """TC-015：--scatter-out 生成单文件 HTML，含对数轴、无外链。"""
    require_tsx()
    scatter = out_path("scatter.html")
    proc = pick(
        "--exam-type", "sk", "--cities", "广州",
        "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
        "--scatter-out", str(scatter),
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    html = scatter.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "log" in html.lower()
    assert "http://" not in html and "https://" not in html


# ── 参数校验与退出码 ────────────────────────────────────────────


def test_missing_jobs_exits_2() -> None:
    """缺 --jobs → 退出码 2。"""
    require_tsx()
    proc = run_cli([])
    assert proc.returncode == 2, proc


def test_invalid_cutoff_exits_2() -> None:
    """--cutoff 非数值 → 退出码 2（不静默忽略）。"""
    require_tsx()
    proc = pick("--exam-type", "sk", "--cutoff", "abc")
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)


def test_nonexistent_file_exits_nonzero() -> None:
    """职位表不存在 → 非零退出，且错误信息可读。"""
    require_tsx()
    proc = run_cli(["--jobs", "tests/fixtures/not-exists.xlsx"])
    assert proc.returncode != 0
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "失败" in combined or "Error" in combined or "ENOENT" in combined, combined[:400]


# ── 区级薪酬穿透到 CLI 输出 ─────────────────────────────────────


def test_cli_uses_district_salary() -> None:
    """区级薪酬必须出现在 CLI 的 JSON 输出里（南沙 25–27、荔湾 18–21、从化 15–18）。"""
    require_tsx()
    target = out_path("pick-district.json")
    proc = pick(
        "--exam-type", "sk", "--cities", "广州",
        # 南沙发改局要求「2 年以上基层经历」，不填 grassroots 会被判 warn 而进不了候选
        "--grassroots", "5",
        "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
        "--json", str(target),
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    by_code = {row["code"]: row for row in data["candidates"]}

    nansha = by_code.get("44010100000001")
    assert nansha, by_code.keys()
    assert (nansha["salary"]["payMin"], nansha["salary"]["payMax"]) == (25, 27), nansha["salary"]
    assert nansha["salary"]["district"] == "南沙"

    liwan = by_code.get("44010100000002")
    assert (liwan["salary"]["payMin"], liwan["salary"]["payMax"]) == (18, 21), liwan["salary"]

    conghua = by_code.get("44010100000003")
    assert (conghua["salary"]["payMin"], conghua["salary"]["payMax"]) == (15, 18), conghua["salary"]
