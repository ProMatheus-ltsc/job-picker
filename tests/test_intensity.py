"""TC-001 / TC-002：工作强度筛查（REQ-001）。

核心断言（改造方案 §五 P0-3 验收）：
- 南沙应急局、从化江埔所、白云嘉禾街道（应急办）必须判 heavy；
- **必须扫职位简介**——结构化字段（机构性质/职位类型）看起来正常、但 intro 含
  「三防/消防/应急」的综合岗，也必须判 heavy（当天 50 岗里漏了 5 个就是这么漏的）。
"""

from __future__ import annotations

from helpers import job, probe, require_tsx


def test_intro_only_emergency_is_heavy() -> None:
    """TC-002：title/remark 干净、只有 intro 含三防/应急 → 必须 heavy。"""
    require_tsx()
    result = probe(
        "intensity",
        {
            "job": job(
                title="一级科员",
                remark="",
                intro="从事三防指挥、应急值守及综合协调工作",
            )
        },
    )
    assert result["level"] == "heavy", result
    fields = {hit["field"] for hit in result["hits"]}
    assert "intro" in fields, result
    categories = {hit["category"] for hit in result["hits"]}
    assert {"emergency"} & categories, result


def test_acceptance_post_nansha_emergency() -> None:
    """验收岗 1：南沙区应急管理局 → heavy。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(unit="广州市南沙区应急管理局", intro="从事应急管理、三防指挥及综合协调工作")},
    )
    assert result["level"] == "heavy", result


def test_acceptance_post_jiangpu_police() -> None:
    """验收岗 2：从化江埔所（一线执法执勤）→ heavy。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(unit="广州市公安局从化区分局江埔派出所", intro="从事一线执法执勤工作")},
    )
    assert result["level"] == "heavy", result


def test_acceptance_post_jiahe_street() -> None:
    """验收岗 3：白云嘉禾街道（应急办）→ heavy。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(unit="广州市白云区嘉禾街道办事处", intro="从事三防应急及综合管理工作")},
    )
    assert result["level"] == "heavy", result


def test_clean_job_is_none() -> None:
    """反例：intro 干净 → none，不得误判。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(intro="从事经济社会发展规划编制工作", remark="无")},
    )
    assert result["level"] == "none", result
    assert result["hits"] == [], result


def test_light_signal_is_light_not_heavy() -> None:
    """出差/信访/性别类只判 light（提示性信号），不得升级为 heavy。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(intro="从事信访接待工作，经常出差")},
    )
    assert result["level"] == "light", result


def test_all_three_fields_scanned() -> None:
    """三字段（intro/title/remark）都要被扫描：任一字段命中即记录该字段。"""
    require_tsx()
    result = probe(
        "intensity",
        {"job": job(intro="", title="执法支队一级科员", remark="其他要求: 需夜间值守")},
    )
    fields = {hit["field"] for hit in result["hits"]}
    assert "title" in fields, result
    assert "remark" in fields, result
    assert result["level"] == "heavy"


def test_custom_lexicon_overrides() -> None:
    """自定义词表生效；空数组视为未配置并回退默认词表。"""
    require_tsx()
    custom = probe(
        "intensity",
        {"job": job(intro="从事特殊工种盯守工作"), "lexicon": {"duty": ["盯守"]}},
    )
    assert custom["level"] == "heavy", custom
    assert any(hit["kw"] == "盯守" for hit in custom["hits"])

    fallback = probe(
        "intensity",
        {"job": job(intro="需夜间值班"), "lexicon": {"duty": []}},
    )
    assert fallback["level"] == "heavy", fallback
