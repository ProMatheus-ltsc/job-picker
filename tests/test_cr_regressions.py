"""CR 第二轮指出的 3 个 CRITICAL 的回归用例。

每一条都对应一次真实缺陷，防止再次退化：
1. 带前缀的来源表名（「附件1：乡镇机关职位表」）漏判 5 年服务期；
2. 画像偏好过滤后未重算帕累托 → 「3 个候选却有 3 个前沿点」；
3. 国考下 cutoffGrade=C 与 proxyGrade=A 并存，报告前后矛盾。
"""

from __future__ import annotations

from helpers import fixture, load_json, out_path, probe, require_tsx, run_cli


# ── CRITICAL 1：带前缀的来源表名 ────────────────────────────────


def test_prefixed_township_sheet_recognized() -> None:
    """真实 sheet 名带前缀时也要判出 5 年服务期（不能因为多命中而放弃）。"""
    require_tsx()
    cases = {
        "乡镇机关": 5,
        "附件1：乡镇机关职位表": 5,
        "乡镇机关职位表": 5,
        "附件2-乡镇机关": 5,
        "县以上机关": None,
        "附件1：县以上机关职位表": None,
        "公安机关": None,
    }
    for sheet, expected in cases.items():
        result = probe("exammode", {"sourceSheet": sheet})
        assert result["minServiceYears"] == expected, (sheet, result)


def test_prefixed_sheet_keeps_bond_in_json() -> None:
    """带前缀的乡镇 sheet 在完整流水线里也要带服务期。"""
    require_tsx()
    from openpyxl import Workbook

    book = out_path("prefixed-sheet.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "附件1：乡镇机关职位表"
    ws.append(["广东省2026年考试录用公务员职位表（乡镇机关）"])
    ws.append(
        ["职位代码", "招考单位", "招考职位", "职位简介", "录用人数",
         "学历", "专业名称及代码", "是否要求2年以上基层工作经历", "其他要求", "考区"]
    )
    ws.append(
        ["44010600000099", "广州市从化区某街道办事处", "一级科员",
         "从事文电会务工作", "1", "本科", "法学(B030101)", "否", "无", "广州市从化区"]
    )
    wb.save(book)

    target = out_path("prefixed-pick.json")
    proc = run_cli(["--jobs", str(book), "--exam-type", "sk", "--cities", "广州", "--json", str(target)])
    assert proc.returncode == 0, (proc.stdout[-1000:], proc.stderr[-1000:])
    data = load_json(target)
    rows = data["candidates"] + data["excludedByIntensity"]
    assert rows, "没有解析出岗位"
    assert rows[0]["minServiceYears"] == 5, rows[0]


# ── CRITICAL 2：过滤后重算帕累托 ────────────────────────────────


def test_pareto_recomputed_after_profile_filter() -> None:
    """画像过滤后前沿点数量不得超过候选数（不能出现 3 候选 3 前沿但实际被排除）。"""
    require_tsx()
    from helpers import REPO_ROOT

    target = out_path("prf-pareto.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--cities", "广州",
            "--profile", str(REPO_ROOT / "assets" / "profile.md"),
            "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, (proc.stdout[-1200:], proc.stderr[-1200:])
    data = load_json(target)

    candidates = len(data["candidates"])
    frontier = len(data["pareto"]["frontier"])
    assert frontier <= candidates, (frontier, candidates)

    # 前沿里的 key 必须是仍然存在的候选
    codes = {row["code"] for row in data["candidates"]}
    for point in data["pareto"]["frontier"]:
        assert point["key"] in codes, (point["key"], codes)


def test_profile_exclusion_reported_separately() -> None:
    """画像排除与强度排除必须分开报告（不能混称"强度排除"）。"""
    require_tsx()
    from helpers import REPO_ROOT

    target = out_path("prf-sep.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--cities", "广州",
            "--profile", str(REPO_ROOT / "assets" / "profile.md"),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    assert "excludedByPreference" in data, data.keys()
    intensity_excluded = {row["code"] for row in data["excludedByIntensity"]}
    preference_excluded = {row["code"] for row in data["excludedByPreference"]}
    # 两个集合不应互相污染（同一岗位不会既因强度又因偏好出现在两处）
    assert not (intensity_excluded & preference_excluded), (
        intensity_excluded & preference_excluded
    )


# ── CRITICAL 3：进面线级别随考试类型 ────────────────────────────


def test_cutoff_grade_follows_exam_type() -> None:
    """国考 → A；省考 → C。cutoffGrade 与 proxyGrade 必须一致。"""
    require_tsx()
    for exam, expected in (("gk", "A"), ("sk", "C")):
        target = out_path(f"grade-{exam}.json")
        proc = run_cli(
            [
                "--jobs", str(fixture("gd-2026-jobs.xlsx")),
                "--exam-type", exam,
                "--cities", "广州",
                "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
                "--json", str(target),
            ]
        )
        assert proc.returncode == 0, proc.stderr[-800:]
        data = load_json(target)
        rows = [row for row in data["candidates"] if row.get("probability")]
        assert rows, f"{exam}: 没有算出概率"
        for row in rows:
            prob = row["probability"]
            assert prob["cutoffGrade"] == expected, (exam, row["code"], prob)
            assert prob["proxyGrade"] == expected, (exam, row["code"], prob)
            assert prob["cutoffGrade"] == prob["proxyGrade"], (exam, row["code"], prob)


def test_sk_report_declares_c_grade_axis() -> None:
    """省考报告的结论段必须声明概率轴是 C 级、帕累托只作方向筛选。"""
    require_tsx()
    report = out_path("grade-sk.md")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk", "--cities", "广州",
            "--mu", "67", "--sigma", "3.5", "--cutoff", "65,70",
            "--report-out", str(report),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    text = report.read_text(encoding="utf-8")
    assert "C 级" in text, "报告未声明 C 级"
    assert "方向筛选" in text, "报告未声明帕累托仅作方向筛选"


def test_probability_never_exceeds_one() -> None:
    """概率不得超过 100%（名额 ≥ 报名人数时会算出 200%，必须截断）。"""
    require_tsx()
    result = probe(
        "probability",
        {
            "mu": 67,
            "sigma": 3.5,
            "cutoffMin": 50,
            "cutoffMax": 52,
            "hires": 3,
            "applicants": 2,
        },
    )
    assert result["p"] is not None
    assert result["p"] <= 1.0, result["p"]
    assert result.get("capped") is True, result


def test_province_tier_only_for_guangdong() -> None:
    """省直档只对广东生效；其它省份回退市级/层级档（不编造）。"""
    require_tsx()
    result = probe(
        "salary",
        {"regions": ["浙江省财政厅", "江苏省发展和改革委员会", "广东省财政厅"]},
    )
    table = {row["region"]: row for row in result["table"]}
    assert table["浙江省财政厅"]["city"] != "省直（驻广州）", table["浙江省财政厅"]
    assert table["江苏省发展和改革委员会"]["city"] != "省直（驻广州）", table[
        "江苏省发展和改革委员会"
    ]
    assert table["广东省财政厅"]["city"] == "省直（驻广州）", table["广东省财政厅"]
