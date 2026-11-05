"""CR 第三轮指出的 1 CRITICAL + 3 MAJOR 的回归用例。

每条都对应一次真实缺陷：
1. CR-01：国考下概率被标成「一手」（A），与 μ/σ 是 C 级的事实矛盾；
2. MJ-01：profile.md 的「—」占位符被当成目标城市 → 0 个岗位；
3. MJ-02：画像「接受值班/应急=是」无法恢复 heavy 岗位；
4. MJ-03：薪酬级别硬编码 'B'，省直 A 级被降级。
"""

from __future__ import annotations

from helpers import REPO_ROOT, fixture, load_json, out_path, probe, require_tsx, run_cli

PROFILE = REPO_ROOT / "assets" / "profile.md"


# ── CR-01：概率整体级别 ─────────────────────────────────────────


def test_probability_grade_is_weakest_not_cutoff_grade() -> None:
    """国考：进面线 A 级，但概率必须标 C（μ/σ 是 C 级）。"""
    require_tsx()
    result = probe(
        "probability",
        {
            "mu": 67,
            "sigma": 3.5,
            "cutoffMin": 65,
            "cutoffMax": 70,
            "hires": 1,
            "applicants": 100,
            "cutoffGrade": "A",
            "cutoffSource": "国考面试名单",
        },
    )
    assert result["cutoffGrade"] == "A", result
    assert result["probabilityGrade"] == "C", result
    inputs = {item["input"]: item["grade"] for item in result["gradeInputs"]}
    assert inputs["笔试基线 μ"] == "C", inputs
    assert inputs["整卷波动 σ"] == "C", inputs


def test_probability_grade_c_for_sk() -> None:
    """省考：线与 μ/σ 都是 C → 概率整体 C。"""
    require_tsx()
    result = probe(
        "probability",
        {
            "mu": 67,
            "sigma": 3.5,
            "cutoffMin": 65,
            "cutoffMax": 70,
            "hires": 1,
            "applicants": 100,
            "cutoffGrade": "C",
        },
    )
    assert result["probabilityGrade"] == "C", result


def test_gk_report_table_does_not_mark_probability_as_firsthand() -> None:
    """国考报告的数据表不得给概率标「一手」。"""
    require_tsx()
    report = out_path("gk-grade.md")
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
    table = text.split("## 数据表")[1].split("## 局限")[0]
    assert "（一手）" not in table, table
    # 概率必须标为二手·估算
    assert "（二手·估算）" in table, table


# ── MJ-01：占位符不是取值 ───────────────────────────────────────


def test_placeholder_profile_yields_no_cities() -> None:
    """画像模板里「目标城市 = —」不得被解析成城市名「—」。"""
    require_tsx()
    target = out_path("mj01-default.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--profile", str(PROFILE),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    cities = data["input"]["profile"]["targetCities"]
    assert "—" not in cities, cities
    assert cities == [], cities
    # 未限定城市 → 全量分析，纳入判定不能为 0
    assert data["summary"]["total"] > 0, data["summary"]


def test_placeholder_in_custom_profile_ignored() -> None:
    """自定义画像里各类占位符都要被忽略。"""
    require_tsx()
    profile = out_path("mj01-custom.md")
    profile.write_text(
        "\n".join(
            [
                "| 项 | 值 | 说明 |",
                "|---|---|---|",
                "| 目标城市 | — | 未填 |",
                "| 排除哪些区 | — | 未填 |",
                "| 专业（主修） | — | 未填 |",
                "| 接受值班 / 夜间 / 轮班 | — | 未表态 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = out_path("mj01-custom.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--profile", str(profile),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    assert data["input"]["profile"]["targetCities"] == []
    assert data["summary"]["total"] > 0


# ── MJ-02：接受某类强度即可放行 ─────────────────────────────────


def test_accept_duty_restores_heavy_jobs() -> None:
    """画像「接受值班/应急/执法=是」→ 对应 heavy 岗位回到候选并标注 heavy。"""
    require_tsx()
    profile = out_path("mj02-accept.md")
    profile.write_text(
        "\n".join(
            [
                "| 项 | 值 | 说明 |",
                "|---|---|---|",
                "| 接受值班 / 夜间 / 轮班 | 是 | 测试 |",
                "| 接受应急 / 三防 / 消防 / 救援 | 是 | 测试 |",
                "| 接受执法勤务 / 一线 / 处突 | 是 | 测试 |",
                "| 目标城市 | 广州 | 测试 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = out_path("mj02-accept.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--profile", str(profile),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    heavy = [row for row in data["candidates"] if row["intensity"]["level"] == "heavy"]
    assert heavy, "接受值班/应急后 heavy 岗位仍未恢复"
    assert data["excludedByIntensity"] == [], data["excludedByIntensity"]


def test_reject_duty_still_excludes() -> None:
    """画像「不接受值班」→ 该类岗位继续被排除。"""
    require_tsx()
    profile = out_path("mj02-reject.md")
    profile.write_text(
        "\n".join(
            [
                "| 项 | 值 | 说明 |",
                "|---|---|---|",
                "| 接受值班 / 夜间 / 轮班 | 否 | 测试 |",
                "| 目标城市 | 广州 | 测试 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = out_path("mj02-reject.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--profile", str(profile),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    for row in data["candidates"]:
        categories = {
            hit["category"] for hit in (row["intensity"].get("hits") or [])
        }
        assert "duty" not in categories or row["intensity"]["level"] != "heavy", row


def test_petition_only_preference_does_not_short_circuit() -> None:
    """只设信访类偏好时也必须生效（不能因 hasPreference 判断遗漏而直接返回）。"""
    require_tsx()
    profile = out_path("mj02-petition.md")
    profile.write_text(
        "\n".join(
            [
                "| 项 | 值 | 说明 |",
                "|---|---|---|",
                "| 接受信访 / 接访 / 维稳 | 否 | 测试 |",
                "| 目标城市 | 广州 | 测试 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = out_path("mj02-petition.json")
    proc = run_cli(
        [
            "--jobs", str(fixture("gd-2026-jobs.xlsx")),
            "--exam-type", "sk",
            "--profile", str(profile),
            "--json", str(target),
        ]
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    data = load_json(target)
    for row in data["candidates"]:
        cats = {hit["category"] for hit in (row["intensity"].get("hits") or [])}
        assert "petition" not in cats, row


# ── MJ-03：薪酬级别不再硬编码 ───────────────────────────────────


def test_province_salary_grade_is_a() -> None:
    """省直档（预算反推）在报告里必须标 A 级，不能被降级成 B。"""
    require_tsx()
    result = probe("salary", {"region": "广东省财政厅"})
    assert "A 级" in result["basis"], result["basis"]


def test_report_pay_grade_matches_basis() -> None:
    """报告数据表的薪酬级别必须与薪酬档声明的依据级别一致。"""
    require_tsx()
    report = out_path("mj03-report.md")
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
    # 区级档是 B 级（可核验），必须标 B 而不是 A
    assert "（二手·可核验）" in table, table
    assert "（一手）" not in table, table
