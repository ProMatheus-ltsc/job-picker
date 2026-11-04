"""测试公共工具：调用 TypeScript 引擎探针并解析 JSON 结果。

为什么用子进程探针而不是 Node 侧另写一套测试：
本项目原有的验证入口就是 `python -m pytest -q`（SKILL/CI 都用它），
再引一套 Node test runner 会让"跑测试"这件事出现两条路径。
探针只做转发，业务判定仍在 `engine/`，所以不存在"实现与测试各写一份"的问题。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "tests" / "ts" / "probe.ts"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OUT_DIR = REPO_ROOT / "tests" / "out"


class ProbeError(RuntimeError):
    """探针执行失败（含引擎抛错）。"""


def _npx_argv() -> list[str]:
    """定位 tsx 入口：优先本地 node_modules，其次 npx。"""
    local = REPO_ROOT / "node_modules" / ".bin"
    for name in ("tsx.cmd", "tsx"):
        candidate = local / name
        if candidate.is_file():
            return [str(candidate)]
    npx = shutil.which("npx")
    if npx:
        return [npx, "tsx"]
    raise ProbeError("找不到 tsx：请在 job-picker 目录执行 npm i")


def probe(op: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    """调用探针并返回解析后的 JSON；非零退出会带上 stdout 中的错误信息。"""
    argv = _npx_argv() + [str(PROBE), "--op", op]
    proc = subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise ProbeError(
            f"探针无输出（op={op}, exit={proc.returncode}）: {(proc.stderr or '')[:500]}"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProbeError(f"探针输出非 JSON（op={op}）: {raw[:500]}") from error
    if not data.get("ok"):
        raise ProbeError(
            f"引擎报错（op={op}）: {data.get('errorName') or data.get('code')} "
            f"{data.get('errorMessage') or data.get('error')}"
        )
    return data


def run_cli(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """以子进程方式跑 scripts/pick.ts。"""
    argv = _npx_argv() + [str(REPO_ROOT / "scripts" / "pick.ts"), *args]
    return subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def fixture(name: str) -> Path:
    path = FIXTURES / name
    if not path.is_file():
        raise FileNotFoundError(f"fixture 不存在: {path}")
    return path


def out_path(name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / name


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def job(**overrides: Any) -> Dict[str, Any]:
    """构造一个字段完整的 Job（引擎读的字段一个都不能少，否则扫描会得到空值）。"""
    base: Dict[str, Any] = {
        "key": "k",
        "code": "44010100000000",
        "unit": "测试单位",
        "title": "一级科员",
        "avgIncome": None,
        "netIncome": None,
        "incomeScore": None,
        "netScore": None,
        "applicants": None,
        "hires": 1,
        "region": "广州市南沙区",
        "degree": "本科",
        "major": "法学(B030101)",
        "intro": "",
        "politicalStatus": "不限",
        "grassrootsYears": "否",
        "serviceProject": "",
        "institution": "",
        "freshRequired": "否",
        "physicalTest": "",
        "sourceSheet": "县以上机关",
        "minServiceYears": None,
        "remark": "",
        "marks": ["pending", "pending", "pending", "pending"],
    }
    base.update(overrides)
    return base


def require_tsx() -> None:
    """没有 node_modules 时跳过而非失败：依赖缺失是环境问题，不是代码缺陷。"""
    if not (REPO_ROOT / "node_modules").is_dir():
        try:
            import pytest

            pytest.skip("node_modules 缺失，请先执行 npm i")
        except ImportError:  # pragma: no cover
            print("node_modules 缺失，请先执行 npm i", file=sys.stderr)
