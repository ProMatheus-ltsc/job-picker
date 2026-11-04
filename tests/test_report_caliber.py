"""结论段的口径正确性：「算不了」不得写成「没有」。

这是本项目最典型的错误输出形态——把"缺少输入"伪装成"结论是否定的"。
"""

from __future__ import annotations

from helpers import probe, require_tsx


def base_input() -> dict:
    return {
        "examType": "sk",
        "cities": ["广州"],
        "caliber": {
            "mu": None,
            "sigma": None,
            "cutoffSource": "区级代理",
            "cutoffGrade": "C",
            "tolerance": "概率 ±1 个量级",
        },
        "rows": [
            {
                "label": "广州市从化区民政局·一级科员",
                "code": "A",
                "region": "广州·从化",
                "hires": 1,
                "payMin": 15,
                "payMax": 18,
                "payGrade": "B",
                "probability": None,
                "probabilityGrade": "C",
                "ratio": 86,
                "intensity": {"level": "none", "hits": []},
                "minServiceYears": None,
                "frontier": False,
            }
        ],
        "pareto": {
            "frontier": [],
            "dominated": [],
            "excluded": [{"key": "A", "reason": "缺少概率，无法参与两轴比较"}],
        },
        "scopeNotice": "## ⚠️ 范围外提示\n\n本次分析范围：**广州**。",
        "limitations": [],
        "pendingChecks": ["未提供 μ/σ，概率未计算"],
        "magnitudeWarning": None,
    }


def test_missing_axis_is_not_zero_frontier() -> None:
    """所有点都被 excluded（缺概率轴）时，结论必须说「算不了」，不能说「0 个前沿点」。"""
    require_tsx()
    md = probe("report", base_input())["md"]
    conclusion = md.split("## 结论")[1].split("## 依据")[0]
    assert "未做帕累托前沿分析" in conclusion, conclusion
    assert "算不了" in conclusion or "不是" in conclusion, conclusion
    # 不得出现把"算不了"写成结论的表述
    assert "0 个位于帕累托前沿" not in conclusion, conclusion
    # 必须给出补救路径
    assert "--mu" in conclusion, conclusion


def test_missing_axis_still_gives_actionable_conclusion() -> None:
    """即使概率缺失，也要说明当前还能依据什么（不能只丢一句"算不了"）。"""
    require_tsx()
    md = probe("report", base_input())["md"]
    conclusion = md.split("## 结论")[1].split("## 依据")[0]
    assert "只能按薪酬区间与竞争度排序" in conclusion, conclusion


def test_partial_exclusion_keeps_real_conclusion() -> None:
    """有点能比较时，正常给前沿结论，并说明有多少做了比较。"""
    require_tsx()
    payload = base_input()
    payload["rows"].append(
        {
            "label": "广州市南沙区发展和改革局·一级科员",
            "code": "B",
            "region": "广州·南沙",
            "hires": 1,
            "payMin": 25,
            "payMax": 27,
            "payGrade": "B",
            "probability": 0.0004,
            "probabilityGrade": "C",
            "ratio": 48,
            "intensity": {"level": "none", "hits": []},
            "minServiceYears": None,
            "frontier": True,
        }
    )
    payload["pareto"] = {
        "frontier": [{"key": "B", "salaryMid": 26, "probability": 0.0004}],
        "dominated": [],
        "excluded": [{"key": "A", "reason": "缺少概率"}],
    }
    md = probe("report", payload)["md"]
    conclusion = md.split("## 结论")[1].split("## 依据")[0]
    assert "1 个位于帕累托前沿" in conclusion, conclusion
    assert "南沙发改" in conclusion or "南沙区发展和改革局" in conclusion, conclusion
    assert "未做帕累托前沿分析" not in conclusion, conclusion
