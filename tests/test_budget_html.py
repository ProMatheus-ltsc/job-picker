"""REQ-005 补充：--html 输入路径（无需第三方依赖）。

为什么必须有 HTML 入口：不少单位把预算公开成网页而不是 PDF。
只支持 PDF 会让「没有 pdfplumber」+「只公开网页」这一组合完全无法取数。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "budget_salary.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OUT = REPO_ROOT / "tests" / "out"


def run(*args: str) -> subprocess.CompletedProcess:
    OUT.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_html_input_produces_same_result_as_json() -> None:
    """HTML 与 JSON 两种入口对同一份预算必须给出一致结论。"""
    out_html = OUT / "budget-html.json"
    out_json = OUT / "budget-native.json"
    proc_html = run(
        "--html", str(FIXTURES / "nansha-fagai-budget.html"), "--out", str(out_html)
    )
    assert proc_html.returncode == 0, proc_html.stderr[-800:]
    proc_json = run(
        "--json-input", str(FIXTURES / "nansha-fagai-budget.json"), "--out", str(out_json)
    )
    assert proc_json.returncode == 0, proc_json.stderr[-800:]

    html = json.loads(out_html.read_text(encoding="utf-8"))
    native = json.loads(out_json.read_text(encoding="utf-8"))
    for key in ("pathA", "pathB", "pathDiffRatio", "headcountRange",
                "perCapitaPreTaxMin", "perCapitaPreTaxMax",
                "yearPackageMin", "yearPackageMax"):
        assert html[key] == native[key], (key, html[key], native[key])


def test_html_strips_markup_before_extracting() -> None:
    """HTML 标签不得干扰金额抽取（抽出的科目数应与 JSON 入口一致）。"""
    out_html = OUT / "budget-html.json"
    run("--html", str(FIXTURES / "nansha-fagai-budget.html"), "--out", str(out_html))
    data = json.loads(out_html.read_text(encoding="utf-8"))
    subjects = data["subjects"]
    assert any("[301]" in key for key in subjects), subjects
    assert any("工会经费" in key for key in subjects), subjects
    # 值不能带 HTML 残留
    for key, value in subjects.items():
        assert "<" not in str(value), (key, value)


def test_missing_all_inputs_exits_2() -> None:
    """三个入口都不给 → 退出码 2 并说明可选路径。"""
    proc = run()
    assert proc.returncode == 2, (proc.returncode, proc.stdout[:300], proc.stderr[:300])
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "json-input" in combined or "pdf" in combined, combined[:300]


def test_nonexistent_html_exits_nonzero() -> None:
    """HTML 文件不存在 → 非零退出。"""
    proc = run("--html", "tests/fixtures/nope.html")
    assert proc.returncode != 0
