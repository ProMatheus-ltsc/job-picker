"""TC-019 / TC-020：护栏用例（测试分支只读、受保护路径不可改）。

TC-019 的语义是「**测试过程本身不产生提交、不 push**」。
这里在模块导入时记录 HEAD 与分支，用例断言它们未变——
这才是对「测试不改写仓库」的真实断言。只检查 commit message 里有没有 "test"
是弱断言（谁都能绕开），CR 指出过这一点。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 受保护路径：守门白名单与已归档一手数据（任何改动都是篡改）
PROTECTED = [
    "scripts/_guard.py",
    "references/interview-scores-2025-tax-yue-zhe-shan.csv",
    "references/interview-scores-2026-tax-yue-zhe-shan.csv",
    "references/tax-scores-yoy-2025-2026.md",
]

_HEAD_AT_IMPORT = None
_BRANCH_AT_IMPORT = None


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _snapshot() -> None:
    global _HEAD_AT_IMPORT, _BRANCH_AT_IMPORT
    if _HEAD_AT_IMPORT is None:
        _HEAD_AT_IMPORT = git("rev-parse", "HEAD").stdout.strip()
        _BRANCH_AT_IMPORT = git("branch", "--show-current").stdout.strip()


_snapshot()


def base_ref() -> str | None:
    for ref in ("main", "origin/main", "master", "origin/master"):
        proc = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if proc.returncode == 0:
            return ref
    return None


def test_head_unchanged_during_tests() -> None:
    """TC-019：测试执行期间 HEAD 未变（证明测试进程没有提交）。"""
    _snapshot()
    current = git("rev-parse", "HEAD").stdout.strip()
    assert current, "无法读取 HEAD"
    assert current == _HEAD_AT_IMPORT, (
        f"测试期间 HEAD 变了：{_HEAD_AT_IMPORT} → {current}（测试不得提交）"
    )


def test_branch_unchanged_during_tests() -> None:
    """TC-019：测试没有切换分支（未创建测试分支）。"""
    _snapshot()
    current = git("branch", "--show-current").stdout.strip()
    assert current == _BRANCH_AT_IMPORT, (current, _BRANCH_AT_IMPORT)


def test_test_branch_not_pushed() -> None:
    """TC-019：远端不存在 test/PRJ-2026-022-* 引用（测试分支从未 push）。"""
    proc = git("ls-remote", "--heads", "origin", "test/PRJ-2026-022-*")
    if proc.returncode != 0:
        pytest.skip(f"无法访问远端（离线环境）: {(proc.stderr or '').strip()[:120]}")
    refs = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    assert not refs, f"远端存在测试分支引用: {refs}"


def test_guard_whitelist_unchanged() -> None:
    """TC-020：_guard.py 的官方域名白名单未被修改。"""
    base = base_ref()
    if base is None:
        pytest.skip("无基线分支，跳过")
    proc = git("diff", "--name-only", base, "--", PROTECTED[0])
    assert proc.returncode == 0, proc.stderr
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not changed, f"受保护路径被修改: {changed}"


def test_archived_hand_data_unchanged() -> None:
    """TC-020：已归档的一手 CSV/MD 数据未被篡改。"""
    base = base_ref()
    if base is None:
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


def test_worktree_clean_of_test_artifacts() -> None:
    """测试产物不得出现在 git status 的未跟踪列表里（已被 .gitignore 覆盖）。"""
    proc = git("status", "--porcelain", "-uall", "tests/out")
    assert proc.returncode == 0, proc.stderr
    entries = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not entries, f"tests/out 未被忽略: {entries[:5]}"
