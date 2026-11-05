"""TC-005 / TC-006 / TC-017：省考模式与多 sheet 解析（REQ-003、REQ-011）。

省考的关键差异（改造方案 §五 P0-2）：
- 进面分：官方**没有**逐岗分数（名单只有姓名+准考证号）→ 必须改用代理并标 C 级；
- 职位表：6 个 sheet，**来源表决定 5 年最低服务期**（乡镇机关）；
- 表头不在第 1 行（真实表在第 2~3 行）。
"""

from __future__ import annotations

from helpers import fixture, probe, require_tsx, run_cli


def test_township_service_years() -> None:
    """TC-005：来源表=乡镇机关 → minServiceYears=5；其他来源表 → null。"""
    require_tsx()
    cases = [
        ("乡镇机关", 5),
        ("乡镇", 5),
        ("县以上机关", None),
        ("公安机关", None),
        ("法院", None),
        ("检察院", None),
        ("监狱", None),
    ]
    for sheet, expected in cases:
        result = probe("exammode", {"sourceSheet": sheet})
        assert result["minServiceYears"] == expected, (sheet, result)


def test_unknown_source_sheet_not_guessed() -> None:
    """未知来源表 → null（不猜服务期）。"""
    require_tsx()
    for sheet in ("附件X：某未知表", "", "县以上机关（含街道）"):
        result = probe("exammode", {"sourceSheet": sheet})
        # 「县以上机关（含街道）」包含已知名 → 唯一命中，按县以上处理（null）
        assert result["minServiceYears"] is None, (sheet, result)


def test_has_long_service_bond_flag() -> None:
    """hasLongServiceBond：≥5 年才算长服务期。"""
    require_tsx()
    assert probe("exammode", {"sourceSheet": "乡镇机关"})["hasLongServiceBond"] is True
    assert probe("exammode", {"sourceSheet": "县以上机关"})["hasLongServiceBond"] is False


def test_exam_type_parsing() -> None:
    """gk/sk 大小写与空值处理：空值按国考（历史一致），非法值返回 null。"""
    require_tsx()
    assert probe("exammode", {"examType": "gk"})["parsed"] == "gk"
    assert probe("exammode", {"examType": "SK"})["parsed"] == "sk"
    assert probe("exammode", {"examType": ""})["parsed"] == "gk"
    assert probe("exammode", {"examType": None})["parsed"] == "gk"
    assert probe("exammode", {"examType": "xx"})["parsed"] is None


def test_cutoff_grade_differs_by_exam_type() -> None:
    """省考逐岗线不存在 → C 级；国考税务有官方名单 → A 级。"""
    require_tsx()
    result = probe("exammode", {"examType": "sk"})
    assert result["cutoffGradeSk"] == "C", result
    assert result["cutoffGradeGk"] == "A", result


def test_invalid_exam_type_exits_2() -> None:
    """TC-006：非法 --exam-type → 退出码 2，且输出同时含 gk 与 sk 用法。"""
    require_tsx()
    proc = run_cli(
        ["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--exam-type", "xx"]
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "gk" in combined and "sk" in combined, combined


def test_cli_sk_mode_runs_and_marks_source_sheet() -> None:
    """TC-017：6 个 sheet 分别解析，输出里每岗位带 sourceSheet。"""
    require_tsx()
    out = fixture("gd-2026-jobs.xlsx")
    proc = run_cli(
        [
            "--jobs", str(out),
            "--exam-type", "sk",
            "--cities", "广州",
            "--mu", "67",
            "--sigma", "3.5",
            "--cutoff", "65,70",
            "--json", str(_out_json()),
        ]
    )
    assert proc.returncode == 0, (proc.stdout[-2000:], proc.stderr[-2000:])
    data = _load_out()

    sheets = {row["sourceSheet"] for row in data["candidates"]}
    all_sheets = sheets | {row["sourceSheet"] for row in data["excludedByIntensity"]}
    # 至少覆盖县以上机关与乡镇机关（其余 sheet 的岗位因法考/体测等硬门槛未进候选）
    assert {"县以上机关", "乡镇机关"} <= all_sheets, all_sheets

    # 每个候选都要有 sourceSheet（不能是空串）
    for row in data["candidates"]:
        assert row["sourceSheet"], row


def test_township_bond_survives_into_json() -> None:
    """5 年服务期必须落进 JSON（不是只在引擎里算过）。"""
    require_tsx()
    if not _out_json().is_file():
        test_cli_sk_mode_runs_and_marks_source_sheet()
    data = _load_out()
    bonds = {
        row["code"]: row["minServiceYears"]
        for row in data["candidates"] + data["excludedByIntensity"]
    }
    # 江埔街道（乡镇机关 sheet，强度 none）应带 5 年
    assert bonds.get("44010600000002") == 5, bonds
    # 从化民政局（县以上机关 sheet）不带服务期
    assert bonds.get("44010100000003") is None, bonds
    # 嘉禾街道（乡镇机关，强度 heavy → 在排除列表里）同样带 5 年
    assert bonds.get("44010600000001") == 5, bonds


def test_sk_mode_without_scores_does_not_fail() -> None:
    """省考模式不提供分数文件时必须正常工作（不得因为"没有分数"报错）。"""
    require_tsx()
    proc = run_cli(
        ["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--exam-type", "sk", "--cities", "广州"]
    )
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    assert "省考" in proc.stdout, proc.stdout[:400]


def test_gk_mode_still_works() -> None:
    """国考模式回归：不传 --exam-type 时行为与改造前一致。"""
    require_tsx()
    proc = run_cli(["--jobs", str(fixture("gd-2026-jobs.xlsx")), "--cities", "广州"])
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    assert "国考" in proc.stdout, proc.stdout[:400]


def _out_json():
    from helpers import out_path

    return out_path("pick-sk.json")


def _load_out():
    from helpers import load_json

    return load_json(_out_json())
