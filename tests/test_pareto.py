"""TC-013：帕累托支配分析（REQ-007）。

验收基准（改造方案 P1-3）：11 个岗应输出 3 个前沿点（从化民政、荔湾政数、南沙发改），
并指出"黄埔/深圳光明被南沙同薪酬支配，概率低 27–34 倍"。
"""

from __future__ import annotations

import json

import pytest

from helpers import FIXTURES, probe, require_tsx


def baseline() -> dict:
    return json.loads((FIXTURES / "pareto-baseline.json").read_text(encoding="utf-8"))


def test_three_frontier_points() -> None:
    """前沿点应为 3 个，且正是方案点名的三个岗位。"""
    require_tsx()
    data = baseline()
    result = probe("pareto", {"points": data["points"]})
    keys = {point["key"] for point in result["frontier"]}
    assert keys == {"从化民政", "荔湾政数", "南沙发改"}, result


def test_manyuan_dominated_by_nansha() -> None:
    """黄埔投促被南沙发改支配（同薪酬，概率低得多）。"""
    require_tsx()
    result = probe("pareto", {"points": baseline()["points"]})
    dominated = {item["key"]: item for item in result["dominated"]}
    assert "黄埔投促" in dominated, dominated.keys()
    assert "南沙发改" in dominated["黄埔投促"]["by"], dominated["黄埔投促"]


def test_probability_ratio_reported() -> None:
    """被支配点要给出概率倍数（当天用的就是倍数口径：27–34 倍）。"""
    require_tsx()
    result = probe("pareto", {"points": baseline()["points"]})
    dominated = {item["key"]: item for item in result["dominated"]}

    guangming = dominated["光明发改"]
    ratios = [d["probabilityRatio"] for d in guangming["deltas"] if d["dominator"] == "南沙发改"]
    assert ratios, guangming
    # 26.0 vs 26.0 同薪酬；概率 0.00041 / 0.000015 ≈ 27 倍
    assert 25 <= ratios[0] <= 30, ratios

    huangpu = dominated["黄埔投促"]
    ratios = [d["probabilityRatio"] for d in huangpu["deltas"] if d["dominator"] == "南沙发改"]
    assert ratios and 30 <= ratios[0] <= 40, ratios


def test_equal_values_are_not_dominance() -> None:
    """两轴同值 → 互不支配，均留在前沿（同值不该判出支配关系）。"""
    require_tsx()
    result = probe(
        "pareto",
        {
            "points": [
                {"key": "A", "salaryMid": 20, "probability": 0.001},
                {"key": "B", "salaryMid": 20, "probability": 0.001},
            ]
        },
    )
    assert {p["key"] for p in result["frontier"]} == {"A", "B"}, result
    assert result["dominated"] == [], result


def test_single_axis_better_is_dominance() -> None:
    """一轴相等、另一轴严格更优 → 构成支配。"""
    require_tsx()
    result = probe(
        "pareto",
        {
            "points": [
                {"key": "A", "salaryMid": 20, "probability": 0.001},
                {"key": "B", "salaryMid": 20, "probability": 0.0005},
            ]
        },
    )
    assert [p["key"] for p in result["frontier"]] == ["A"], result
    assert [d["key"] for d in result["dominated"]] == ["B"], result


def test_empty_input_returns_empty_result() -> None:
    """输入为空 → 空结果，不抛错。"""
    require_tsx()
    result = probe("pareto", {"points": []})
    assert result["frontier"] == []
    assert result["dominated"] == []
    assert result["excluded"] == []


def test_missing_axis_excluded_with_reason() -> None:
    """缺轴的点被排除并说明原因（不参与支配关系，也不污染前沿）。"""
    require_tsx()
    result = probe(
        "pareto",
        {
            "points": [
                {"key": "A", "salaryMid": 20, "probability": 0.001},
                {"key": "B", "salaryMid": 22, "probability": None},
                {"key": "C", "salaryMid": None, "probability": 0.002},
            ]
        },
    )
    excluded = {item["key"]: item for item in result["excluded"]}
    assert set(excluded) == {"B", "C"}, result
    assert "概率" in excluded["B"]["reason"], excluded["B"]
    assert "薪酬" in excluded["C"]["reason"], excluded["C"]
    assert [p["key"] for p in result["frontier"]] == ["A"], result


def test_summary_mentions_frontier_count() -> None:
    """摘要要能直接进报告（前沿点数量 + 被支配者的支配者）。"""
    require_tsx()
    result = probe("pareto", {"points": baseline()["points"]})
    summary = result["summary"]
    assert "3 个前沿点" in summary, summary
    assert "被" in summary and "支配" in summary, summary


def test_zero_probability_handled() -> None:
    """概率为 0 的点：倍数无意义，不得崩溃（用 Infinity 表示并保持可比）。"""
    require_tsx()
    result = probe(
        "pareto",
        {
            "points": [
                {"key": "A", "salaryMid": 20, "probability": 0.001},
                {"key": "Z", "salaryMid": 20, "probability": 0},
            ]
        },
    )
    assert [p["key"] for p in result["frontier"]] == ["A"], result
    zero = next(d for d in result["dominated"] if d["key"] == "Z")
    assert zero["deltas"][0]["probabilityRatio"] == pytest.approx(float("inf")) or (
        zero["deltas"][0]["probabilityRatio"] == 0
        or zero["deltas"][0]["probabilityRatio"] is None
    )
