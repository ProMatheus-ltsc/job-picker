"""TC-003 / TC-004：数据分级制度（REQ-002）。

这是本项目最"价值观"的一条：从二分「一手/禁止」改为四级 A/B/C/D，
但放宽只发生在**标注层**——C 级数据用于排序公式仍必须抛错，D 级任何用途都拒绝。
"""

from __future__ import annotations

import pytest

from helpers import probe, require_tsx


def test_rank_rejects_c() -> None:
    """TC-003：C 级用于 rank → 抛 DataGradeError，错误信息含等级与来源。"""
    require_tsx()
    result = probe(
        "datagrade",
        {
            "requireUsable": {
                "value": 74.47,
                "grade": "C",
                "use": "rank",
                "source": "某机构整理的 2026 广州进面分（样本不明）",
            }
        },
    )
    assert result["graded"] is None, result
    assert result["errorName"] == "DataGradeError", result
    assert "C" in result["errorMessage"], result
    assert "来源" in result["errorMessage"], result


def test_display_allows_c() -> None:
    """C 级用于 display 必须放行（只读方向），并带标注。"""
    require_tsx()
    result = probe(
        "datagrade",
        {"requireUsable": {"value": 74.47, "grade": "C", "use": "display", "source": "机构整理"}},
    )
    assert result["graded"] is not None, result
    assert result["graded"]["grade"] == "C"
    assert result["graded"]["label"] == "二手·估算"


def test_rejects_d() -> None:
    """TC-004：D 级在 display 与 rank 两种用途下都抛错。"""
    require_tsx()
    for use in ("display", "rank"):
        result = probe(
            "datagrade",
            {"requireUsable": {"value": 84, "grade": "D", "use": use, "source": "营销模板"}},
        )
        assert result["graded"] is None, (use, result)
        assert result["errorName"] == "DataGradeError", (use, result)
        assert "D" in result["errorMessage"], (use, result)


def test_rank_allows_a_and_b() -> None:
    """A/B 级可用于排序。"""
    require_tsx()
    for grade in ("A", "B"):
        result = probe(
            "datagrade",
            {"requireUsable": {"value": 25, "grade": grade, "use": "rank", "source": "部门预算"}},
        )
        assert result["graded"] is not None, (grade, result)


def test_invalid_grade_rejected() -> None:
    """非法级别抛错，不猜默认级别（避免把未知来源当一手）。"""
    require_tsx()
    result = probe(
        "datagrade",
        {"requireUsable": {"value": 1, "grade": "E", "use": "display", "source": "未知"}},
    )
    assert result["graded"] is None, result
    assert result["errorName"] == "DataGradeError", result


def test_can_use_matrix() -> None:
    """canUse 判定矩阵：A/B 全通；C 仅 display；D 全否。"""
    require_tsx()
    cases = [
        ("A", "rank", True),
        ("A", "display", True),
        ("B", "rank", True),
        ("C", "rank", False),
        ("C", "display", True),
        ("D", "rank", False),
        ("D", "display", False),
    ]
    for grade, use, expected in cases:
        result = probe("datagrade", {"canUse": {"grade": grade, "use": use}})
        assert result["canUse"] is expected, (grade, use, result)


def test_weakest_merges_conservatively() -> None:
    """多个来源合并取最保守级别（A + C → C）。"""
    require_tsx()
    result = probe("datagrade", {"weakest": ["A", "C"]})
    assert result["weakest"] == "C", result


def test_grades_registry_has_four_levels() -> None:
    """四级注册表齐全且每级都有可用于报告的标签。"""
    require_tsx()
    result = probe("datagrade", {"canUse": {"grade": "A", "use": "display"}})
    grades = result["grades"]
    assert set(grades) == {"A", "B", "C", "D"}
    for meta in grades.values():
        assert meta["label"], meta
        assert meta["allowed"], meta


def test_annotate_never_throws() -> None:
    """annotate 是纯标注（不做用途校验），供已经确定展示用途的场景使用。"""
    require_tsx()
    result = probe(
        "datagrade",
        {"annotate": {"value": 74.47, "grade": "C", "source": "机构整理"}},
    )
    assert result["annotated"]["grade"] == "C"
    assert result["annotated"]["label"] == "二手·估算"
