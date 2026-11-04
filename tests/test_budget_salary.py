"""TC-009 / TC-010：预算反推（REQ-005）。

验收基准来自改造方案 §2.1 的南沙发改局实证（官方 PDF）：
  工资福利 775.48 万、工会经费 12.81 万
  → 路径 A 640.5 万、路径 B 623.84 万，两路差 2.7%
  7 个科室 → 24~30 人 → 人均应发 20.8~26.0 万 → 年全包 20~25 万
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "budget_salary.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OUT = REPO_ROOT / "tests" / "out"


def run_budget(fixture_name: str, out_name: str) -> subprocess.CompletedProcess:
    OUT.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--json-input",
            str(FIXTURES / fixture_name),
            "--out",
            str(OUT / out_name),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_nansha_fagai_matches_scheme_baseline() -> None:
    """TC-009：南沙发改局反推结果与方案实证值一致。"""
    proc = run_budget("nansha-fagai-budget.json", "budget.json")
    assert proc.returncode == 0, proc.stderr
    data = load("budget.json")

    # 两条路径的中间量
    assert data["pathA"]["value"] == pytest.approx(640.5, abs=0.5), data["pathA"]
    assert data["pathB"]["value"] == pytest.approx(623.84, abs=0.5), data["pathB"]
    assert data["pathB"]["unitInsurance"] == pytest.approx(151.64, abs=0.05)
    # 两路差 < 3%（方案：2.7%）
    assert data["pathDiffRatio"] < 0.03, data["pathDiffRatio"]

    # 人数与人均（方案：24~30 人、20.8~26.0 万）
    head = data["headcountRange"]
    assert (head["min"], head["max"]) == (24, 30), head
    assert data["perCapitaPreTaxMin"] == pytest.approx(20.79, abs=0.5)
    assert data["perCapitaPreTaxMax"] == pytest.approx(25.99, abs=0.5)

    # 年全包 20~25 万（方案口径；实现给 20.3~25.3，落在 ±1 万内）
    assert 19.5 <= data["yearPackageMin"] <= 20.5, data["yearPackageMin"]
    assert 24.5 <= data["yearPackageMax"] <= 26.0, data["yearPackageMax"]


def test_output_contains_all_intermediates() -> None:
    """中间量必须全部输出（要求可核验：每条数字能追到出处）。"""
    run_budget("nansha-fagai-budget.json", "budget.json")
    data = load("budget.json")
    for key in (
        "subjects",
        "pathA",
        "pathB",
        "pathDiffRatio",
        "headcountRange",
        "wageTotalEstimate",
        "perCapitaPreTaxMin",
        "perCapitaPreTaxMax",
        "yearPackageMin",
        "yearPackageMax",
        "monthlyCash",
        "monthlyFundBothSides",
        "yearCash",
    ):
        assert key in data, f"缺少中间量 {key}"


def test_markdown_report_written() -> None:
    """--out 同时产出 Markdown 报告（方法与局限可见）。"""
    run_budget("nansha-fagai-budget.json", "budget.json")
    md = (OUT / "budget.md").read_text(encoding="utf-8")
    assert "预算反推薪酬" in md
    assert "路径 A" in md and "路径 B" in md
    assert "局限" in md


def test_concentrated_payroll_rejected() -> None:
    """TC-010：基本工资占比 78.4% → 拒绝输出个人薪酬，exit 非 0，stderr 可观察。"""
    proc = run_budget("education-bureau-budget.json", "budget-edu.json")
    assert proc.returncode != 0, proc.stdout
    assert "CONCENTRATED_PAYROLL" in (proc.stderr or ""), proc.stderr
    assert "集中列支" in (proc.stderr or ""), proc.stderr

    data = load("budget-edu.json")
    assert data["usable"] is False, data
    assert "CONCENTRATED_PAYROLL" in data["blockedBy"], data
    # 阻断时不得给年全包结论
    assert "yearPackageMin" not in data, data


def test_low_housing_fund_flagged() -> None:
    """公积金占比 < 3% 是集中列支的独立信号。"""
    run_budget("education-bureau-budget.json", "budget-edu.json")
    data = load("budget-edu.json")
    codes = {item["code"] for item in data["anomalies"]}
    assert "LOW_HOUSING_FUND" in codes, codes


def test_missing_headcount_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """人数不披露且无内设机构数 → 阻断并说明（不得用 1 人除出天价）。"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "no-sections.json"
    path.write_text(
        json.dumps(
            {
                "unit": "某无机构说明单位",
                "subjects": {
                    "[301]工资福利支出": "500.00万元",
                    # 工会经费 9.00 万 ÷ 2% = 450 万，与 500−50 一致 → 两路自洽，
                    # 这样才会走到「人数未知」这一分支，而不是先被结构异常拦下
                    "[30228]工会经费": "9.00万元",
                    "住房公积金": "50.00万元",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json-input", str(path), "--out", str(OUT / "no-sections-out.json")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode != 0, proc.stdout
    data = json.loads((OUT / "no-sections-out.json").read_text(encoding="utf-8"))
    assert data["usable"] is False
    assert "HEADCOUNT_UNKNOWN" in data["blockedBy"], data


def test_explicit_headcount_overrides_structure() -> None:
    """--headcount 可覆盖结构推算（拿到真实人数时的优先路径）。"""
    OUT.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--json-input",
            str(FIXTURES / "nansha-fagai-budget.json"),
            "--headcount",
            "20",
            "--out",
            str(OUT / "budget-hc.json"),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads((OUT / "budget-hc.json").read_text(encoding="utf-8"))
    assert data["headcountRange"]["min"] == 20
    assert data["headcountRange"]["max"] == 20
    assert data["headcountRange"]["basis"] == "显式输入"
