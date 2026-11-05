"""TC-011 / TC-012：进面概率模型（REQ-006）。

验证方式：在 Python 侧**独立实现**同一公式（用标准库 math.erf），
再与 TypeScript 引擎逐岗位比对。这样"实现与测试各写一份"反而是优点——
两份独立实现给出同一结果，才说明公式没错。

公式（改造方案 §2.2）：
    P(进面) = (1 − Φ((线 − μ)/σ)) × 进面名额 ÷ 报名人数
    进面名额 = 招录 × 进面比（1:3；招 4–5 人按 1:2.5 向下取整）
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from helpers import FIXTURES, probe, require_tsx

BASELINE = FIXTURES / "probability-baseline.json"


def reference_p(
    mu: float,
    sigma: float,
    cutoff_min: float,
    cutoff_max: float,
    hires: int,
    applicants: int,
    ratio: float = 3.0,
) -> float:
    """Python 侧独立实现（与 TS 实现无关的第二份）。"""
    effective = 2.5 if 4 <= hires <= 5 else ratio
    quota = max(1, math.floor(hires * effective))
    mid = (cutoff_min + cutoff_max) / 2
    # Φ(x) = 0.5 * erfc(-x / √2)
    phi = 0.5 * math.erfc(-((mid - mu) / sigma) / math.sqrt(2))
    return (1 - phi) * quota / applicants


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_all_cases_match_independent_implementation() -> None:
    """TC-011：11 个岗位概率与独立实现一致（相对误差 <= 10%）。"""
    require_tsx()
    baseline = load_baseline()
    mu, sigma = baseline["mu"], baseline["sigma"]
    items = [
        {
            **item,
            "mu": mu,
            "sigma": sigma,
            "interviewRatio": 3,
            "key": item["key"],
        }
        for item in baseline["items"]
    ]
    result = probe("probability-batch", {"items": items})
    got = {row["key"]: row for row in result["results"]}

    failures = []
    for item in baseline["items"]:
        expected = reference_p(
            mu,
            sigma,
            item["cutoffMin"],
            item["cutoffMax"],
            item["hires"],
            item["applicants"],
        )
        actual = got[item["key"]]["p"]
        assert actual is not None, (item["key"], got[item["key"]])
        rel = abs(actual - expected) / expected if expected else 0
        if rel > 0.10:
            failures.append((item["key"], expected, actual, rel))
    assert not failures, failures


def test_matches_scheme_magnitude_regime() -> None:
    """方案 §2.2 的核心结论：**概率的绝对量级本身是结论**。

    当天 11 个岗全部 < 0.1%，由此得出"分数达标前，选岗的边际收益极小"。
    本用例用与当天同量级的输入（μ=67、σ=3.5、线 70–74、报名 200–400）验证
    实现确实落在「远低于 1%」这一区间，并给出量级警告。
    """
    require_tsx()
    scenarios = [
        {"cutoffMin": 70.0, "cutoffMax": 74.0, "hires": 1, "applicants": 330},
        {"cutoffMin": 71.0, "cutoffMax": 75.0, "hires": 1, "applicants": 300},
        {"cutoffMin": 69.5, "cutoffMax": 73.5, "hires": 1, "applicants": 400},
    ]
    for scenario in scenarios:
        result = probe("probability", {"mu": 67, "sigma": 3.5, **scenario})
        assert result["p"] is not None, result
        assert result["p"] < 1e-3, (scenario, result["p"])
        assert result["magnitudeWarning"], (scenario, result)


def test_magnitude_warning_when_below_threshold() -> None:
    """P < 0.1% 时必须给"分数达标前选岗作用很小"类警告。"""
    require_tsx()
    result = probe(
        "probability",
        {
            "mu": 67,
            "sigma": 3.5,
            "cutoffMin": 70,
            "cutoffMax": 74,
            "hires": 1,
            "applicants": 330,
        },
    )
    assert result["p"] < 1e-3, result
    assert result["magnitudeWarning"], result
    assert "提分" in result["magnitudeWarning"] or "边际收益" in result["magnitudeWarning"], result


def test_missing_applicants_returns_null_not_zero() -> None:
    """TC-012：缺报名人数 → p=null 且 missingInputs 含 applicants（绝不把"不知道"算成"没希望"）。"""
    require_tsx()
    result = probe(
        "probability",
        {"mu": 67, "sigma": 3.5, "cutoffMin": 65, "cutoffMax": 70, "hires": 1, "applicants": None},
    )
    assert result["p"] is None, result
    assert result["p"] != 0, result
    assert "applicants" in result["missingInputs"], result


def test_missing_mu_or_sigma_returns_null() -> None:
    """缺 μ/σ 同样降级为 null（不得静默用某个默认基线代替）。"""
    require_tsx()
    for missing in ("mu", "sigma"):
        payload = {
            "mu": 67,
            "sigma": 3.5,
            "cutoffMin": 65,
            "cutoffMax": 70,
            "hires": 1,
            "applicants": 50,
        }
        payload[missing] = None
        result = probe("probability", payload)
        assert result["p"] is None, (missing, result)
        assert missing in result["missingInputs"], (missing, result)


def test_quota_rule_for_four_to_five_hires() -> None:
    """进面名额：招 4–5 人按 1:2.5 向下取整；其余按 1:3。"""
    require_tsx()
    cases = {1: 3, 2: 6, 3: 9, 4: 10, 5: 12, 6: 18}
    for hires, expected in cases.items():
        result = probe(
            "probability",
            {
                "mu": 67,
                "sigma": 3.5,
                "cutoffMin": 65,
                "cutoffMax": 70,
                "hires": hires,
                "applicants": 100,
            },
        )
        assert result["quota"] == expected, (hires, result["quota"], expected)


def test_sigma_zero_raises() -> None:
    """σ=0 → 抛错（模型退化为阶跃函数，必须由调用方显式决定）。"""
    require_tsx()
    try:
        probe(
            "probability",
            {"mu": 67, "sigma": 0, "cutoffMin": 65, "cutoffMax": 70, "hires": 1, "applicants": 50},
        )
    except Exception as error:  # noqa: BLE001 - 探针把引擎异常包装成 ProbeError
        assert "sigma" in str(error), error
    else:  # pragma: no cover
        raise AssertionError("σ=0 未抛错")


def test_cutoff_grade_is_c_for_proxy_line() -> None:
    """进面线是推算/二手 → 输出必须标 C 级（省考官方不给逐岗线）。"""
    require_tsx()
    result = probe(
        "probability",
        {"mu": 67, "sigma": 3.5, "cutoffMin": 65, "cutoffMax": 70, "hires": 1, "applicants": 50},
    )
    assert result["cutoffGrade"] == "C", result


def test_interval_line_gives_optimistic_and_pessimistic() -> None:
    """区间线同时给乐观（下沿）与悲观（上沿）概率，且下沿 > 上沿。"""
    require_tsx()
    result = probe(
        "probability",
        {"mu": 67, "sigma": 3.5, "cutoffMin": 63, "cutoffMax": 72, "hires": 1, "applicants": 100},
    )
    assert result["pAtMinLine"] > result["pAtMaxLine"], result
    assert result["pAtMaxLine"] <= result["p"] <= result["pAtMinLine"], result
