"""TC-017：省考职位表多 sheet 解析（REQ-011）。

广东省考职位表按「县以上机关 / 公安机关 / 法院 / 检察院 / 监狱 / 乡镇机关」分 6 个 sheet，
且表头不在第 1 行。单一 sheet 解析失败不得影响其余 sheet。
"""

from __future__ import annotations

import json

from helpers import fixture, load_json, out_path, require_tsx, run_cli

EXPECTED_SHEETS = ["县以上机关", "公安机关", "法院", "检察院", "监狱", "乡镇机关"]


def pick_json() -> dict:
    target = out_path("pick-sheets.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--cities", "广州",
            "--keep-heavy",
            # 不填法考与基层经历时，法院/检察院/公安/监狱的岗位会被判 fail/warn，
            # 不会出现在 candidates 与 excludedByIntensity 里。
            # 本组用例要验证的是**解析层**（6 sheet 是否都解析、来源表是否落库），
            # 所以把画像补全到"全部可报"：有法考证书、5 年基层、不限应届。
            "--legal-cert", "1",
            "--grassroots", "5",
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    return load_json(target)


def test_all_six_sheets_exist_in_fixture() -> None:
    """fixture 必须含 6 个 sheet，否则本组用例失去意义。"""
    from openpyxl import load_workbook

    wb = load_workbook(fixture("gd-2026-jobs.xlsx"), read_only=True)
    names = list(wb.sheetnames)
    wb.close()
    assert names == EXPECTED_SHEETS, names


def test_every_sheet_parsed_with_source_marker() -> None:
    """6 个 sheet 都被解析到（解析层覆盖），岗位带非空 sourceSheet。

    注意断言口径：`candidates`/`excludedByIntensity` 只包含**资格通过**的岗位；
    公安/监狱 sheet 的岗位因「需体能测评」进入 warn，不在这两个列表里。
    因此这里验证的是「解析层覆盖 6 个 sheet」——用 `parsedSheets` 诊断字段，
    而不是拿候选列表去要求 6 个 sheet 都在（那会把资格判定的正确行为当成解析缺陷）。
    """
    require_tsx()
    data = pick_json()
    parsed = set(data["diagnostics"].get("parsedSheets") or [])
    assert parsed == set(EXPECTED_SHEETS), parsed

    rows = data["candidates"] + data["excludedByIntensity"]
    assert rows, "解析出的岗位为空"
    for row in rows:
        assert row["sourceSheet"], row
        assert row["sourceSheet"] in EXPECTED_SHEETS, row


def test_sheet_errors_empty_on_clean_fixture() -> None:
    """干净 fixture 不应产生 sheet 解析错误。"""
    require_tsx()
    data = pick_json()
    assert data["diagnostics"]["sheetErrors"] == [], data["diagnostics"]["sheetErrors"]


def test_header_row_detection_skips_title() -> None:
    """表头在第 2 行（第 1 行是标题）时仍能正确探测——否则会解析出 0 个岗位。"""
    require_tsx()
    data = pick_json()
    rows = data["candidates"] + data["excludedByIntensity"]
    assert len(rows) >= 8, f"只解析出 {len(rows)} 个岗位，表头探测可能失败"


def test_township_sheet_jobs_carry_bond_in_all_lists() -> None:
    """同一 sheet 的岗位在候选与排除两个列表里都要带 5 年服务期。"""
    require_tsx()
    data = pick_json()
    township = [
        row for row in data["candidates"] + data["excludedByIntensity"]
        if row["sourceSheet"] == "乡镇机关"
    ]
    assert township, "乡镇机关 sheet 没有岗位"
    for row in township:
        assert row["minServiceYears"] == 5, row


def test_non_township_sheets_have_no_bond() -> None:
    """非乡镇 sheet 的岗位不得被误标服务期。"""
    require_tsx()
    data = pick_json()
    others = [
        row for row in data["candidates"] + data["excludedByIntensity"]
        if row["sourceSheet"] in {"县以上机关", "公安机关", "法院", "检察院", "监狱"}
    ]
    assert others
    for row in others:
        assert row["minServiceYears"] is None, row


def test_broken_sheet_does_not_abort_others() -> None:
    """单 sheet 表头异常不得中断整表：其余 sheet 仍产出岗位。"""
    require_tsx()
    from openpyxl import Workbook

    broken = out_path("broken-sheet.xlsx")
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "县以上机关"
    ws1.append(["广东省2026年考试录用公务员职位表（县以上机关）"])
    ws1.append(
        ["职位代码", "招考单位", "招考职位", "职位简介", "录用人数",
         "学历", "专业名称及代码", "是否要求2年以上基层工作经历", "其他要求", "考区"]
    )
    ws1.append(
        ["44010100000001", "广州市南沙区发展和改革局", "一级科员",
         "从事规划编制工作", "1", "本科", "法学(B030101)", "否", "无", "广州市南沙区"]
    )
    # 故意造一个整表只有标题、没有表头的 sheet
    ws2 = wb.create_sheet("法院")
    ws2.append(["广东省2026年考试录用公务员职位表（法院）"])
    ws2.append(["这一行不是表头"])
    wb.save(broken)

    target = out_path("pick-broken.json")
    proc = run_cli(
        ["--jobs", str(broken), "--exam-type", "sk", "--cities", "广州", "--json", str(target)]
    )
    assert proc.returncode == 0, (proc.stdout[-1200:], proc.stderr[-1200:])
    data = json.loads(target.read_text(encoding="utf-8"))
    rows = data["candidates"] + data["excludedByIntensity"]
    assert any(row["sourceSheet"] == "县以上机关" for row in rows), rows
    # 坏 sheet 被记录（或被安全跳过），但进程没有崩
    assert isinstance(data["diagnostics"]["sheetErrors"], list)
