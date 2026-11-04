"""TC-007 / TC-008：区级薪酬粒度（REQ-004）。

改造前的实测缺口（改造方案 §五 P0-4）：
  输入「广州市南沙区发展和改革局」→ 返回「广州 18–25 万」（整市一个档）
  而荔湾实际 18–21 万、南沙 25–27 万，**6.5 万的区际差被完全抹掉**。
"""

from __future__ import annotations

from helpers import probe, require_tsx

NANSHA = "广州市南沙区发展和改革局"
LIWAN = "广州市荔湾区政务服务和数据管理局"
CONGHUA = "广州市从化区民政局"


def test_three_guangzhou_districts_are_distinguishable() -> None:
    """TC-007：南沙 25–27、荔湾 18–21、从化 15–18，三者互不相同。"""
    require_tsx()
    result = probe("salary", {"regions": [NANSHA, LIWAN, CONGHUA]})
    table = {row["region"]: row for row in result["table"]}

    nansha = table[NANSHA]
    assert (nansha["payMin"], nansha["payMax"]) == (25, 27), nansha
    assert nansha["district"] == "南沙", nansha
    assert nansha["precise"] is True, nansha

    liwan = table[LIWAN]
    assert (liwan["payMin"], liwan["payMax"]) == (18, 21), liwan
    assert liwan["district"] == "荔湾", liwan

    conghua = table[CONGHUA]
    assert (conghua["payMin"], conghua["payMax"]) == (15, 18), conghua
    assert conghua["district"] == "从化", conghua

    pairs = {
        (nansha["payMin"], nansha["payMax"]),
        (liwan["payMin"], liwan["payMax"]),
        (conghua["payMin"], conghua["payMax"]),
    }
    assert len(pairs) == 3, "三个区被判成同一档"


def test_district_label_includes_district_name() -> None:
    """标签形如「广州·南沙」，让报告一眼看出是区级档而非整市档。"""
    require_tsx()
    result = probe("salary", {"region": NANSHA})
    assert result["label"] == "广州·南沙", result
    assert result["city"] == "广州", result


def test_unknown_district_falls_back_to_city() -> None:
    """TC-008：未收录区退回市级档，precise=false 且 district 为空，不编造。"""
    require_tsx()
    result = probe("salary", {"region": "广州市增城区某局"})
    assert result["district"] == "", result
    assert result["precise"] is False, result
    assert result["city"] == "广州", result
    # 退回市级档的区间必须是广州整市档，而不是凭空造一个区级值
    assert (result["payMin"], result["payMax"]) == (18, 25), result


def test_schema_city_not_confused_with_district() -> None:
    """同名歧义防护：区级匹配必须优先在「该市」范围内找区名。"""
    require_tsx()
    # 深圳的「福田」未收录 → 退到深圳市级档，不得误命中广州的某个区
    result = probe("salary", {"region": "广东省深圳市福田区某局"})
    assert result["city"] == "深圳", result
    assert result["district"] == "", result
    assert (result["payMin"], result["payMax"]) == (25, 30), result


def test_shenzhen_districts_differ() -> None:
    """深圳区级档同样可区分：光明/坪山 24–28、深汕 26–30。"""
    require_tsx()
    result = probe(
        "salary",
        {"regions": ["深圳市光明区某局", "深圳市深汕特别合作区某局"]},
    )
    table = {row["region"]: row for row in result["table"]}
    guangming = table["深圳市光明区某局"]
    shenshan = table["深圳市深汕特别合作区某局"]
    assert (guangming["payMin"], guangming["payMax"]) == (24, 28), guangming
    assert (shenshan["payMin"], shenshan["payMax"]) == (26, 30), shenshan


def test_every_hit_is_precise_false_or_has_basis() -> None:
    """任何返回都必须带依据说明（可核验要求：每条数字要能追到出处）。"""
    require_tsx()
    result = probe("salary", {"region": NANSHA})
    assert result["basis"].strip(), result
    assert "B 级" in result["basis"] or "A 级" in result["basis"], result
