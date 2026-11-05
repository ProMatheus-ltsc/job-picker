"""广东省考真实结构的两处回归（2026-11-05 实跑发现）。

两处都是**在真实职位表上才暴露、合成样本碰不到**的缺陷：

1. 专业列跨「研究生 / 本科」两列合并时以空格拼接，`majorHit` 不把空格当分隔符
   → 省直三个岗（唯一要求 2 年基层经历的岗位）与越秀仲裁院被判「专业不符」。
2. 薪酬与排除区都只看「考区」列，而广东省考的考区只有地市名（「广州」），
   区名与省直身份写在**招考单位**里 → 南沙被算成广州整市档、省直岗不走省直 A 档、
   「排除越秀」对越秀的岗位完全不生效。

这两组断言直接在真实表结构上跑 CLI，防止再次靠人工眼看才发现。
"""

from __future__ import annotations

from pathlib import Path

from helpers import REPO_ROOT, out_path, probe, require_tsx, run_cli
import json

# 广东省考真实职位的取值特征：考区只有地市名，区名在单位里
NANSHA = {"unit": "广州市南沙区发展和改革局", "region": "广州"}
PROVINCE = {"unit": "广东省退役军人事务厅", "region": "广州"}


def _pick(gd_table: Path, profile: Path | None = None, name: str = "gd-regress.json") -> dict:
    target = out_path(name)
    args = [
        "--jobs", str(gd_table),
        "--exam-type", "sk",
        "--cities", "广州,深圳",
        "--grassroots", "5",
        "--json", str(target),
    ]
    if profile is not None:
        args += ["--profile", str(profile)]
    proc = run_cli(args)
    assert proc.returncode == 0, (proc.stdout[-1500:], proc.stderr[-1500:])
    return json.loads(target.read_text(encoding="utf-8"))


# ── 缺陷 1：跨列专业必须能命中 ───────────────────────────────


def test_multi_column_major_matches(tmp_path: Path) -> None:
    """专业列跨「研究生 / 本科」两列合并后必须仍能命中，不得整体判为不符。

    广东省考把专业拆成三列（研究生 / 本科 / 大专），引擎合并为**空格拼接**的一段文本。
    若匹配时不按空格分段，就等于要求「一个岗位同时含研究生专业与本科专业」，
    省直三岗与越秀仲裁院会全部被判专业不符。
    """
    require_tsx()
    from openpyxl import Workbook

    book = tmp_path / "multi-major.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "县以上机关"
    ws.append(["测试职位表"])
    ws.append(
        [
            "职位代码", "招考单位", "招考职位", "职位简介", "录用人数", "学历",
            "研究生专业名称及代码", "本科专业名称及代码", "大专专业名称及代码",
            "是否要求2年以上基层工作经历", "其他要求", "考区",
        ]
    )
    # 研究生列与本科列是不同的专业名，本人只命中本科列
    ws.append(
        [
            "44990000000001", "广东省退役军人事务厅", "办公室一级主任科员以下",
            "从事政策法规工作", "1", "本科",
            "法律（法学）(A030112)", "法学(B030101)", "",
            "是", "无", "广州",
        ]
    )
    wb.save(book)

    target = out_path("multi-major.json")
    proc = run_cli(
        ["--jobs", str(book), "--exam-type", "sk", "--cities", "广州", "--grassroots", "5",
         "--json", str(target)]
    )
    assert proc.returncode == 0, (proc.stdout[-1200:], proc.stderr[-1200:])
    data = json.loads(target.read_text(encoding="utf-8"))
    codes = {row["code"] for row in data["candidates"]}
    assert "44990000000001" in codes, (
        f"跨列专业未命中，被误判专业不符：{data['diagnostics']['failReasons']}"
    )


# ── 缺陷 2：薪酬与排除区必须看单位名 ─────────────────────────


def test_salary_uses_unit_not_region_only() -> None:
    """考区只写「广州」时，仍须按单位名里的区走区级档，省直须走省直 A 档。"""
    require_tsx()
    nansha = probe("salary", {"job": NANSHA})
    assert nansha["district"] == "南沙", nansha
    assert (nansha["payMin"], nansha["payMax"]) == (25, 27), nansha

    province = probe("salary", {"job": PROVINCE})
    assert province["grade"] == "A", province
    assert (province["payMin"], province["payMax"]) == (20.7, 22.9), province


def test_exclude_district_matches_unit_name() -> None:
    """「排除越秀」必须对考区写「广州」、区名在单位里的岗位生效。"""
    require_tsx()

    from openpyxl import Workbook

    book = out_path("exclude-district-jobs.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "县以上机关"
    ws.append(["测试职位表"])
    ws.append(
        ["职位代码", "招考单位", "招考职位", "职位简介", "录用人数",
         "学历", "专业名称及代码", "是否要求2年以上基层工作经历", "其他要求", "考区"]
    )
    ws.append(
        ["44990000000002", "广州市越秀区人力资源和社会保障局", "一级科员",
         "从事综合管理工作", "1", "本科", "法学(B030101)", "否", "无", "广州"]
    )
    wb.save(book)

    profile = out_path("profile-exclude-yuexiu.md")
    profile.write_text(
        "\n".join(
            [
                "# 临时画像",
                "",
                "| 项 | 值 | 说明 |",
                "|---|---|---|",
                "| 排除哪些区 | 越秀 | 测试 |",
                "| 接受值班 / 夜间 / 轮班 | 否 | 测试 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target = out_path("exclude-district.json")
    proc = run_cli(
        ["--jobs", str(book), "--exam-type", "sk", "--cities", "广州",
         "--profile", str(profile), "--json", str(target)]
    )
    assert proc.returncode == 0, (proc.stdout[-1200:], proc.stderr[-1200:])
    data = json.loads(target.read_text(encoding="utf-8"))
    excluded = {row["code"] for row in data.get("excludedByPreference", [])}
    assert "44990000000002" in excluded, (
        f"排除越秀未生效：候选={[r['code'] for r in data['candidates']]}"
    )
