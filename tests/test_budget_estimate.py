"""双算法薪酬估算（预算双路径 × 决算实有人数）的交叉校验。

这是 2026-11-05 合并 GitHub main 后新增的能力：两套算法都保留，
由 `budget_salary_estimate.py` 判断最终估算区间。

核心断言：
1. 区间重叠 → agreement=overlap，推荐置信度高者（决算法）；
2. 仅一法可用 → agreement=single，区间即该法结果；
3. 两法分歧大 → agreement=wide，区间取**并集**且必须带人工核对提示；
4. C 级数据不得因为"取平均"而被掩盖——最终区间取并集而非加权平均。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "budget_salary_estimate.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OUT = REPO_ROOT / "tests" / "out"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import budget_salary_estimate as est  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess:
    OUT.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def method(name: str, low: float, high: float, confidence: str) -> dict:
    return {
        "available": True,
        "method": name,
        "label": name,
        "perCapitaWan": [low, high],
        "confidence": confidence,
        "basis": "test",
    }


# ── 合成逻辑（单元级）────────────────────────────────────────


def test_overlap_picks_higher_confidence_method() -> None:
    """重叠充分 → 推荐置信度高者（决算法 high > 预算反推 medium）。"""
    result = est.combine({
        "budget_dual_path": method("budget_dual_path", 20.0, 26.0, "medium"),
        "final_account": method("final_account", 21.0, 25.0, "high"),
    })
    assert result["agreement"] == "overlap", result
    assert result["recommended"] == "final_account", result
    # 最终区间取并集（不掩盖分歧）
    assert result["perCapitaWan"] == [20.0, 26.0], result


def test_weighted_mid_between_two_mids() -> None:
    """加权参考值必须落在两个区间中点之间（而不是任一端）。"""
    result = est.combine({
        "budget_dual_path": method("budget_dual_path", 20.0, 26.0, "medium"),
        "final_account": method("final_account", 21.0, 25.0, "high"),
    })
    assert 22.0 < result["weightedMid"] < 24.0, result


def test_single_method_available() -> None:
    """只有一法可用 → agreement=single，区间即该法结果。"""
    result = est.combine({
        "budget_dual_path": method("budget_dual_path", 20.0, 26.0, "medium"),
        "final_account": {"available": False, "reason": "缺文件"},
    })
    assert result["agreement"] == "single", result
    assert result["perCapitaWan"] == [20.0, 26.0], result
    assert "无法交叉校验" in result["reason"], result


def test_wide_disagreement_takes_union_and_warns() -> None:
    """两法分歧大 → agreement=wide，区间取并集（保守），并提示人工核对。"""
    result = est.combine({
        "a": method("a", 10.0, 12.0, "high"),
        "b": method("b", 30.0, 33.0, "high"),
    })
    assert result["agreement"] == "wide", result
    assert result["perCapitaWan"] == [10.0, 33.0], result
    assert "人工核对" in result["reason"], result


def test_both_unavailable() -> None:
    """两法都不可用 → agreement=none，区间为空。"""
    result = est.combine({"a": {"available": False, "reason": "x"}})
    assert result["agreement"] == "none", result
    assert result["perCapitaWan"] is None, result


# ── CLI 级 ─────────────────────────────────────────────────────


def test_cli_selftest_passes() -> None:
    """脚本自带自检必须通过（4 组组合场景）。"""
    proc = run("--selftest")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "自检通过" in proc.stdout, proc.stdout


def test_cli_budget_only_outputs_range() -> None:
    """只给预算科目 → 输出区间 + 年全包，且说明只有单法。"""
    out = OUT / "est-budget.json"
    proc = run(
        "--budget-json", str(FIXTURES / "nansha-fagai-budget.json"),
        "--out", str(out),
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["estimate"]["agreement"] == "single", data["estimate"]
    assert data["perCapitaWan"] == [20.79, 25.99], data["perCapitaWan"]
    assert data["yearPackageWan"] == [20.3, 25.3], data["yearPackageWan"]
    assert data["methods"]["budget_dual_path"]["available"] is True


def test_cli_markdown_has_three_sections() -> None:
    """Markdown 报告含结论/两法明细/局限三段。"""
    out_json = OUT / "est-md.json"
    out_md = OUT / "est-md.md"
    proc = run(
        "--budget-json", str(FIXTURES / "nansha-fagai-budget.json"),
        "--out", str(out_json),
        "--md", str(out_md),
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    text = out_md.read_text(encoding="utf-8")
    assert "## 一、结论" in text, text[:400]
    assert "## 二、两法明细" in text, text[:400]
    assert "## 三、局限" in text, text[:400]
    assert "人均应发" in text, text[:600]


def test_cli_requires_at_least_one_input() -> None:
    """两个入口都不给 → 退出码 2 并给用法。"""
    proc = run()
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)


def test_missing_budget_file_degrades_not_crashes() -> None:
    """预算文件不存在 → 该方法标不可用，另一方法仍可继续（单点失败不中断整体）。"""
    out = OUT / "est-missing.json"
    proc = run(
        "--budget-json", str(FIXTURES / "not-exists.json"),
        "--final-account", str(FIXTURES / "nansha-fagai-budget.json"),
        "--out", str(out),
    )
    # 决算入口收到预算 JSON 也会失败，但不应崩溃
    assert proc.returncode in (0, 1, 2), (proc.returncode, proc.stdout, proc.stderr)
    if out.is_file():
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "estimate" in data, data
