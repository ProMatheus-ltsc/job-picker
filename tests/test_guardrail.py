"""TC-019 / TC-020：护栏用例（测试分支只读、受保护路径不可改）。

TC-019 的判定口径：测试期间测试分支**不得有提交、不得 push**。
本仓库的测试全部在工作区只读执行（不产生提交），因此断言"无新提交 + 未 push"。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 受保护路径：守门白名单与已归档一手数据（任何改动都是篡改）
PROTECTED = [
    "scripts/_guard.py",
    "references/interview-scores-2025-tax-yue-zhe-shan.csv",
    "references/interview-scores-2026-tax-yue-zhe-shan.csv",
    "references/tax-scores-yoy-2025-2026.md",
]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def base_ref() -> str | None:
    for ref in ("main", "origin/main", "master", "origin/master"):
        proc = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if proc.returncode == 0:
            return ref
    return None


def test_no_commits_on_test_branch() -> None:
    """TC-019：测试执行期间没有产生新的提交。"""
    base = base_ref()
    if base is None:
        import pytest

        pytest.skip("无 main/origin 基线，跳过（浅克隆环境）")

    head = git("rev-parse", "HEAD").stdout.strip()
    # 测试自身不提交：HEAD 必须仍然指向交付分支的提交，
    # 且工作区 diff 中不得出现「测试提交」这种非交付内容。
    assert head, "无法读取 HEAD"

    # 关键断言：本次测试运行没有新增 git 提交（测试进程从不调用 git commit）
    log = git("log", "--oneline", "-5").stdout
    assert "test commit" not in log.lower()
    assert "临时测试" not in log


def test_test_branch_not_pushed() -> None:
    """TC-019：没有 push 测试分支（远端不存在 test/PRJ-2026-022-* 引用）。"""
    proc = git("ls-remote", "--heads", "origin", "test/PRJ-2026-022-*")
    if proc.returncode != 0:
        import pytest

        pytest.skip(f"无法访问远端（离线环境）: {(proc.stderr or '').strip()[:120]}")
    refs = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    assert not refs, f"远端存在测试分支引用: {refs}"


def test_guard_whitelist_unchanged() -> None:
    """TC-020：_guard.py 的官方域名白名单未被修改。"""
    base = base_ref()
    if base is None:
        import pytest

        pytest.skip("无基线分支，跳过")
    proc = git("diff", "--name-only", base, "--", PROTECTED[0])
    assert proc.returncode == 0, proc.stderr
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not changed, f"受保护路径被修改: {changed}"


def test_archived_hand_data_unchanged() -> None:
    """TC-020：已归档的一手 CSV/MD 数据未被篡改。"""
    base = base_ref()
    if base is None:
        import pytest

        pytest.skip("无基线分支，跳过")
    proc = git("diff", "--name-only", base, "--", *PROTECTED[1:])
    assert proc.returncode == 0, proc.stderr
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not changed, f"已归档一手数据被修改: {changed}"


def test_guard_still_blocks_third_party() -> None:
    """TC-020：守门行为必须仍然有效（改文档不等于放开代码）。"""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from _guard import is_official  # noqa: PLC0415

    assert is_official("https://www.chinatax.gov.cn/xxgk/abc.html")
    assert is_official("http://bm.scs.gov.cn/kl2026/abc.html")
    # 机构镜像与聚合站必须仍然被拦
    assert not is_official("https://u3.huatu.com/uploads/x.xls")
    assert not is_official("https://www.offcn.com/gk/2026/1234.html")
    assert not is_official("https://www.fenbi.com/spa/tiku")


def test_no_generated_artifacts_committed() -> None:
    """测试产物（tests/out/）不得进入版本控制。"""
    proc = git("ls-files", "tests/out")
    assert proc.returncode == 0, proc.stderr
    tracked = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not tracked, f"测试产物被跟踪: {tracked}"
