"""省直判定回归用例（salary.ts 的 isProvinceLevel）。

真实职位表里「广东省广州市某局」是最常见写法，省级前缀极易被误判成省直。
这些用例把该边界固定下来。
"""

from __future__ import annotations

from helpers import probe, require_tsx


def test_city_prefixed_by_province_is_not_province_level() -> None:
    """省级前缀 + 市级主体 → 判为所在市，不是省直。"""
    require_tsx()
    cases = {
        "广东省广州市某局": ("广州", ""),
        "广东省深圳市财政局": ("深圳", ""),
        "广东省广州市天河区某局": ("广州", "天河"),
    }
    for region, (city, district) in cases.items():
        result = probe("salary", {"region": region})
        assert result["city"] == city, (region, result)
        assert result["district"] == district, (region, result)


def test_real_province_level_units_recognized() -> None:
    """真正的省直单位要命中省直档。"""
    require_tsx()
    for region in (
        "广东省财政厅",
        "广东省发展和改革委员会",
        "省直某单位",
        "广东省直属机关事务管理局",
    ):
        result = probe("salary", {"region": region})
        assert result["city"] == "省直（驻广州）", (region, result)
        assert (result["payMin"], result["payMax"]) == (20.7, 22.9), (region, result)


def test_province_level_band_uses_grade_a_basis() -> None:
    """省直档用预算反推的 A 级依据（区别于 B 级调研区间）。"""
    require_tsx()
    result = probe("salary", {"region": "广东省财政厅"})
    assert "A 级" in result["basis"], result["basis"]
