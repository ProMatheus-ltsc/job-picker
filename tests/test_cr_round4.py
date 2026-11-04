"""CR 第四轮 2 个 MAJOR 的回归用例。

MJ-04：帕累托概率轴级别应取概率整体级别（国考也是 C），且国考报告也要有方向筛选声明；
MJ-05：薪酬级别里「档位估算」兜底应为 C（二手·估算），不得升级成「二手·可核验」。
"""

from __future__ import annotations

from helpers import fixture, load_json, out_path, probe, require_tsx, run_cli


# ── MJ-04 ───────────────────────────────────────────────────────


def test_gk_pareto_axis_grade_is_probability_grade() -> None:
    """国考下帕累托概率轴级别应为 C（与候选的 probabilityGrade 一致），不是 A。"""
    require_tsx()
    target = out_path("mj04-gk.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "gk", "--cities", "广州",
            "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    grades = {
        row["probability"]["probabilityGrade"]
        for row in data["candidates"]
        if row.get("probability")
    }
    assert grades == {"C"}, grades
    assert data["pareto"]["probabilityAxisGrade"] == "C", data["pareto"]
    assert data["pareto"]["usedAsRanking"] is False, data["pareto"]


def test_gk_report_has_direction_screening_declaration() -> None:
    """国考报告同样必须声明「仅作方向筛选」（原先只在省考输出）。"""
    require_tsx()
    report = out_path("mj04-gk.md")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "gk", "--cities", "广州",
            "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
            "--report-out", str(report),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    text = report.read_text(encoding="utf-8")
    assert "方向筛选" in text, text[:800]
    assert "概率整体为 **C 级**" in text, text[:800]


def test_declaration_reason_matches_exam_type() -> None:
    """声明的理由要随考试类型变化，不能把省考的说法写进国考报告。"""
    require_tsx()
    gk_report = out_path("mj04-reason-gk.md")
    sk_report = out_path("mj04-reason-sk.md")
    for exam, path in (("gk", gk_report), ("sk", sk_report)):
        proc = run_cli(
            [
                "--jobs", str(fixture("gd-2026-jobs.xlsx")),
                "--exam-type", exam, "--cities", "广州",
                "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
                "--report-out", str(path),
            ]
        )
        assert proc.returncode == 0, proc.stderr[-800:]

    gk_text = gk_report.read_text(encoding="utf-8")
    sk_text = sk_report.read_text(encoding="utf-8")
    # 国考：线是官方 A 级，理由必须点明 μ/σ
    assert "μ/σ 为用户自报" in gk_text, gk_text[:800]
    # 省考：线是代理，理由必须点明「不公布逐岗线」
    assert "不公布逐岗线" in sk_text, sk_text[:800]


# ── MJ-05 ───────────────────────────────────────────────────────


def test_salary_grade_by_source() -> None:
    """薪酬级别由匹配来源决定：省直 A、区级 B、市级 B、兜底 C。"""
    require_tsx()
    cases = {
        "广东省财政厅": "A",           # 省直：部门预算反推（一手）
        "广州市南沙区发展和改革局": "B",  # 区级：预算结构 + 同类区样本
        "广州市某局": "B",             # 市级：调研样本可核验
        "某某县某局": "C",             # 层级兜底：纯档位推断
    }
    for region, expected in cases.items():
        result = probe("salary", {"region": region})
        assert result["grade"] == expected, (region, result["grade"], expected)


def test_fallback_salary_appears_as_estimate_in_report() -> None:
    """兜底档岗位在报告数据表里必须标「二手·估算」（不再是硬编码的 B）。

    做法：构造一个只有兜底档岗位的小职位表，跑完整 CLI 后检查报告。
    """
    require_tsx()
    from openpyxl import Workbook

    book = out_path("fallback-jobs.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "县以上机关"
    ws.append(["测试职位表"])
    ws.append(
        ["职位代码", "招考单位", "招考职位", "职位简介", "录用人数",
         "学历", "专业名称及代码", "是否要求2年以上基层工作经历", "其他要求", "考区"]
    )
    # 「某某县某局」会落到层级兜底档（C 级）
    ws.append(
        ["44990000000001", "某某县某局", "一级科员", "从事综合管理工作",
         "1", "本科", "法学(B030101)", "否", "无", "某某县"]
    )
    wb.save(book)

    report = out_path("fallback-report.md")
    proc = run_cli(
        ["--jobs", str(book), "--report-out", str(report)]
    )
    assert proc.returncode == 0, (proc.stdout[-800:], proc.stderr[-800:])
    text = report.read_text(encoding="utf-8")
    table = text.split("## 数据表")[1].split("## 局限")[0]
    assert "（二手·估算）" in table, table


def test_district_salary_appears_as_verifiable_in_report() -> None:
    """区级档在报告数据表里应标「二手·可核验」（B 级）。"""
    require_tsx()
    report = out_path("mj05-district.md")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk", "--cities", "广州",
            "--report-out", str(report),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    text = report.read_text(encoding="utf-8")
    table = text.split("## 数据表")[1].split("## 局限")[0]
    assert "（二手·可核验）" in table, table
    assert "（一手）" not in table, table


def test_city_level_salary_is_grade_b_not_c() -> None:
    """市级整市档必须是 B（有调研样本），不能被误解成 C（MJ-06 的核心）。"""
    require_tsx()
    result = probe("salary", {"region": "广州市某局"})
    assert result["city"] == "广州", result
    assert (result["payMin"], result["payMax"]) == (18, 25), result
    assert result["grade"] == "B", result


def test_default_tier_is_grade_c() -> None:
    """最后一个兜底分支（DEFAULT_TIER，不匹配任何 TIERS 正则）也必须是 C。

    之前只覆盖了 TIERS 的县域分支，DEFAULT_TIER 分支无回归保护（m-06）。
    """
    require_tsx()
    # 「某某市某局」不匹配县域/新一线等正则，会落到最后的 DEFAULT_TIER
    result = probe("salary", {"region": "某某市某局"})
    assert result["city"] == "普通地级市（估算）", result
    assert result["grade"] == "C", result


def test_salary_grade_mapping() -> None:
    require_tsx()
    # 省直：basis 里写「A 级」
    province = probe("salary", {"region": "广东省财政厅"})
    assert "A 级" in province["basis"], province["basis"]

    # 区级：basis 里写「B 级」
    district = probe("salary", {"region": "广州市南沙区发展和改革局"})
    assert "B 级" in district["basis"], district["basis"]

    # 层级兜底：basis 里没有任何级别声明（档位估算）→ 应为 C
    fallback = probe("salary", {"region": "某某县某局"})
    assert "A 级" not in fallback["basis"] and "B 级" not in fallback["basis"], fallback["basis"]
