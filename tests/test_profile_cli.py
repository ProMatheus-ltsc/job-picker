"""REQ-012：profile.md 的新字段必须能被 CLI 读取并影响判定。

只加文档不加读取入口，等于文档撒谎——用户填了不生效。
本组用例覆盖 5 个新字段中可判定的 4 类（强度/排除区/最低年薪/服务期）。
"""

from __future__ import annotations

import json
from pathlib import Path

from helpers import FIXTURES, REPO_ROOT, fixture, load_json, out_path, require_tsx, run_cli

PROFILE = REPO_ROOT / "assets" / "profile.md"


def write_profile(tmp_name: str, rows: dict[str, str]) -> Path:
    """生成一份临时画像（保持 Markdown 表格格式，与 assets/profile.md 一致）。"""
    out = out_path(tmp_name)
    lines = ["# 临时画像", "", "| 项 | 值 | 说明 |", "|---|---|---|"]
    for key, value in rows.items():
        lines.append(f"| {key} | {value} | 测试 |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def pick(profile: Path, name: str) -> dict:
    target = out_path(name)
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--cities", "广州",
            "--profile", str(profile),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    return load_json(target)


def test_default_profile_rejects_five_year_bond() -> None:
    """仓库自带 profile.md 写「接受 5 年最低服务期 = 否」→ 乡镇岗被排除。"""
    require_tsx()
    data = pick(PROFILE, "prof-default.json")
    bonds = [row["minServiceYears"] for row in data["candidates"]]
    assert all(b is None for b in bonds), bonds
    excluded_bond = [
        row for row in data["excludedByIntensity"] if (row.get("minServiceYears") or 0) >= 5
    ]
    assert excluded_bond, "带 5 年服务期的岗位未被排除"


def test_exclude_district_takes_effect() -> None:
    """画像排除某区 → 该区岗位被排除。"""
    require_tsx()
    profile = write_profile("prof-district.md", {"排除哪些区": "从化", "接受值班 / 夜间 / 轮班": "否"})
    data = pick(profile, "prof-district.json")
    for row in data["candidates"]:
        assert "从化" not in row["regionLabel"], row


def test_min_annual_package_takes_effect() -> None:
    """可接受最低年薪 → 年薪上限低于该值的岗位被排除。"""
    require_tsx()
    profile = write_profile("prof-salary.md", {"可接受最低年薪": "25"})
    data = pick(profile, "prof-salary.json")
    for row in data["candidates"]:
        assert row["salary"]["payMax"] >= 25, row["salary"]


def test_accept_service_bond_keeps_township() -> None:
    """画像接受 5 年服务期 → 乡镇岗保留。"""
    require_tsx()
    profile = write_profile("prof-bond.md", {"接受 5 年最低服务期": "是"})
    data = pick(profile, "prof-bond.json")
    bonds = [row["minServiceYears"] for row in data["candidates"]]
    assert any(b == 5 for b in bonds), bonds


def test_repository_profile_is_parsable() -> None:
    """仓库自带的 assets/profile.md 必须可解析出新字段（文档与实现同步）。"""
    require_tsx()
    text = PROFILE.read_text(encoding="utf-8")
    for token in ("接受值班", "接受执法", "5 年最低服务期", "排除哪些区", "可接受最低年薪"):
        assert token in text, f"profile.md 缺少字段 {token}"


def test_missing_profile_file_rejected() -> None:
    """画像文件不存在 → 退出码 2（不静默忽略）。"""
    require_tsx()
    proc = run_cli(
        ["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--profile", "tests/fixtures/nope.md"]
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout[:300], proc.stderr[:300])


# ── 参数校验加强（CR MAJOR）────────────────────────────────────


def test_non_numeric_mu_exits_2() -> None:
    """--mu abc → 退出码 2（而不是静默产出 NaN 概率）。"""
    require_tsx()
    proc = run_cli(["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--mu", "abc"])
    assert proc.returncode == 2, (proc.returncode, proc.stdout[:300], proc.stderr[:300])
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "mu" in combined, combined[:300]


def test_non_numeric_sigma_exits_2() -> None:
    """--sigma abc → 退出码 2。"""
    require_tsx()
    proc = run_cli(["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--sigma", "abc"])
    assert proc.returncode == 2, (proc.returncode, proc.stderr[:300])


def test_exam_type_without_value_exits_2() -> None:
    """--exam-type 后无取值（下一个是别的 flag）→ 退出码 2，不静默回退 gk。"""
    require_tsx()
    proc = run_cli(["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--exam-type", "--cities", "广州"])
    assert proc.returncode == 2, (proc.returncode, proc.stdout[:300], proc.stderr[:300])


def test_applicants_file_feeds_probability() -> None:
    """--applicants 注入一手报名人数 → 概率被算出来（A 级竞争度来源）。"""
    require_tsx()
    applicants = out_path("applicants.json")
    applicants.write_text(
        json.dumps(
            {
                "44010100000001": 48,
                "44010100000002": 132,
                "44010100000003": 86,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    target = out_path("pick-applicants.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--cities", "广州",
            "--mu", "67",
            "--sigma", "3.5",
            "--cutoff", "65,70",
            "--applicants", str(applicants),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, (proc.stdout[-1200:], proc.stderr[-1200:])
    data = load_json(target)
    with_prob = [row for row in data["candidates"] if row.get("probability")]
    assert with_prob, "报名人数注入后仍未算出概率"
    for row in with_prob:
        if row["code"] in {"44010100000001", "44010100000002", "44010100000003"}:
            assert row["probability"]["p"] is not None, row


def test_applicants_bad_file_exits_2() -> None:
    """--applicants 指向不存在文件 → 退出码 2。"""
    require_tsx()
    proc = run_cli(
        ["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--applicants", "tests/fixtures/nope.json"]
    )
    assert proc.returncode == 2, (proc.returncode, proc.stderr[:300])
