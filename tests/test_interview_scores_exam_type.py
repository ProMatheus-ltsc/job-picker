"""TC-005（补充）：interview_scores.py 的 --exam-type 分支。

省考与国考的数据链差异必须在 CLI 层可见：
- sk 模式不得假装有逐岗分数；
- 两种模式都不得静默改变已有 CSV 的解析口径。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "interview_scores.py"
CSV_2026 = REPO_ROOT / "references" / "interview-scores-2026-tax-yue-zhe-shan.csv"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_help_lists_exam_type() -> None:
    """--exam-type 出现在用法里，取值为 gk|sk。"""
    proc = run("--help")
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "--exam-type" in combined, combined[:400]
    assert "gk" in combined and "sk" in combined, combined[:400]


def test_default_is_gk_and_behaves_as_before() -> None:
    """缺省按国考：stats 正常输出，且不打印省考代理警告。"""
    proc = run("stats", "--csv", str(CSV_2026), "--province", "广东")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "岗位数" in proc.stdout
    assert "省考" not in proc.stdout, proc.stdout[:400]


def test_sk_mode_prints_data_chain_note() -> None:
    """sk 模式必须显式说明「官方不公布逐岗分」，避免误读为脚本问题。"""
    proc = run("--exam-type", "sk", "stats", "--csv", str(CSV_2026), "--province", "广东")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "exam-type=sk" in proc.stdout, proc.stdout[:400]
    assert "不公布逐岗进面分" in proc.stdout, proc.stdout[:400]
    assert "C 级" in proc.stdout, proc.stdout[:400]


def test_sk_lookup_marks_proxy_values() -> None:
    """sk 模式下的 lookup 结果也要标代理级别。"""
    proc = run("--exam-type", "sk", "lookup", "--csv", str(CSV_2026), "--codes", "300110101002")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "exam-type=sk" in proc.stdout, proc.stdout[:300]


def test_invalid_exam_type_rejected() -> None:
    """非法 --exam-type 由 argparse 拒绝（退出码 2）。"""
    proc = run("--exam-type", "xx", "stats", "--csv", str(CSV_2026))
    assert proc.returncode == 2, (proc.returncode, proc.stderr[:300])


def test_existing_csv_untouched() -> None:
    """解析口径不变：既有归档 CSV 的岗位数可复算（557 个广东岗位）。"""
    proc = run("stats", "--csv", str(CSV_2026), "--province", "广东")
    assert "岗位数 557" in proc.stdout, proc.stdout[:300]
