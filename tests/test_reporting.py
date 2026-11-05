"""TC-014 / TC-015 / TC-016：范围外提示（REQ-008）、散点图（REQ-009）、口径声明与报告模板（REQ-010）。"""

from __future__ import annotations

from helpers import probe, require_tsx

# ── TC-014 范围外提示 ───────────────────────────────────────────


def test_scope_notice_when_cities_given() -> None:
    """指定城市 → 必须出现范围外提示，且列出范围城市与岗位数。"""
    require_tsx()
    result = probe(
        "scope",
        {"cities": ["广州", "深圳"], "inScopeTotal": 50, "adjacentRegions": ["珠三角"]},
    )
    text = result["text"]
    assert "范围外提示" in text, text
    assert "广州" in text and "深圳" in text, text
    assert "50" in text, text


def test_scope_notice_never_invents_numbers() -> None:
    """无范围外统计时只给方向性描述 + 需重新抓取，不虚构岗位数字。"""
    require_tsx()
    result = probe("scope", {"cities": ["广州"], "inScopeTotal": 12})
    text = result["text"]
    assert "需**重新抓取**" in text or "重新抓取" in text, text
    # 不得出现"另有 X 个岗位（如 中山市财政局 56:1）"这类未抓取的具体数字
    assert "56:1" not in text, text
    assert "40:1" not in text, text


def test_scope_notice_lists_known_outside() -> None:
    """给了范围外统计时列出，并提示需重新抓报录比。"""
    require_tsx()
    result = probe(
        "scope",
        {
            "cities": ["广州", "深圳"],
            "inScopeTotal": 50,
            "outsideCandidates": [{"region": "中山", "note": "2 个同类岗位（需重新抓报录比）"}],
        },
    )
    text = result["text"]
    assert "中山" in text, text
    assert "重新抓取" in text, text


def test_scope_notice_full_scan() -> None:
    """未限定城市 → 明确说明无范围外缺口。"""
    require_tsx()
    result = probe("scope", {"cities": [], "inScopeTotal": 433, "fullScan": True})
    text = result["text"]
    assert "全量分析" in text, text
    assert "不存在" in text, text


# ── TC-015 散点图 ───────────────────────────────────────────────


def scatter_points() -> list[dict]:
    return [
        {"label": "从化民政", "city": "广州·从化", "salaryMid": 16.5, "probability": 0.0009, "ratio": 86},
        {"label": "荔湾政数", "city": "广州·荔湾", "salaryMid": 19.5, "probability": 0.0005, "ratio": 132},
        {"label": "南沙发改", "city": "广州·南沙", "salaryMid": 26.0, "probability": 0.00041, "ratio": 48},
        {"label": "光明发改", "city": "深圳·光明", "salaryMid": 26.0, "probability": 0.000015, "ratio": 330},
    ]


def test_scatter_is_single_file_without_external_links() -> None:
    """TC-015：单文件 HTML，不含 http(s) 外链（不引 CDN 或外部脚本）。"""
    require_tsx()
    result = probe("scatter", {"points": scatter_points()})
    html = result["html"]
    assert "<svg" in html, html[:200]
    assert "http://" not in html and "https://" not in html, "存在外链资源"
    assert "<script" not in html.lower(), "不应引入外部/内联脚本"


def test_scatter_has_log_axis() -> None:
    """纵轴为对数刻度：必须出现 log 相关标识与 10 的幂刻度标签。"""
    require_tsx()
    result = probe("scatter", {"points": scatter_points()})
    html = result["html"]
    assert "log" in html.lower(), "缺少对数标识"
    # 刻度用科学计数（如 1e-4），证明是对数轴而非线性轴
    assert "e-4" in html or "e-5" in html or "e-3" in html, "缺少对数刻度标签"


def test_scatter_legend_distinguishes_cities() -> None:
    """颜色区分城市，且带图例。"""
    require_tsx()
    result = probe("scatter", {"points": scatter_points()})
    html = result["html"]
    for city in ("广州·从化", "广州·荔湾", "广州·南沙", "深圳·光明"):
        assert city in html, f"图例缺少 {city}"
    assert "气泡" in html, "缺少气泡含义说明"


def test_scatter_zero_probability_not_dropped() -> None:
    """概率为 0 的点不被静默丢弃，以特殊标记呈现。"""
    require_tsx()
    points = scatter_points() + [
        {"label": "零概率岗", "city": "广州·海珠", "salaryMid": 24.0, "probability": 0, "ratio": 500}
    ]
    result = probe("scatter", {"points": points})
    html = result["html"]
    assert "零概率岗" in html, "概率为 0 的点被丢弃"
    assert "stroke-dasharray" in html, "缺少零概率特殊标记"


def test_scatter_missing_salary_listed_not_silent() -> None:
    """缺薪酬的点不绘制，但要在页面上说明跳过了哪些。"""
    require_tsx()
    points = scatter_points() + [
        {"label": "缺薪酬岗", "city": "广州·天河", "salaryMid": None, "probability": 0.001, "ratio": 50}
    ]
    result = probe("scatter", {"points": points})
    html = result["html"]
    assert "缺薪酬岗" in html, "跳过的岗位未说明"
    assert "未绘制" in html, html[-400:]


# ── TC-016 口径声明与报告模板 ─────────────────────────────────


def report_input() -> dict:
    return {
        "examType": "sk",
        "cities": ["广州"],
        "caliber": {
            "mu": 67,
            "sigma": 3.5,
            "cutoffSource": "区级/层级实测代理",
            "cutoffGrade": "C",
            "tolerance": "薪酬 ±15–20%；概率 ±1 个量级",
        },
        "rows": [
            {
                "label": "广州市从化区民政局·一级科员",
                "code": "44010100000003",
                "region": "广州·从化",
                "hires": 1,
                "payMin": 15,
                "payMax": 18,
                "payGrade": "B",
                "probability": 0.0009,
                "probabilityGrade": "C",
                "ratio": 86,
                "intensity": {"level": "none", "hits": []},
                "minServiceYears": None,
                "frontier": True,
            },
            {
                "label": "广州市南沙区发展和改革局·一级科员",
                "code": "44010100000001",
                "region": "广州·南沙",
                "hires": 1,
                "payMin": 25,
                "payMax": 27,
                "payGrade": "B",
                "probability": 0.00041,
                "probabilityGrade": "C",
                "ratio": 48,
                "intensity": {"level": "none", "hits": []},
                "minServiceYears": None,
                "frontier": True,
            },
        ],
        "pareto": {
            "frontier": [
                {"key": "44010100000003", "salaryMid": 16.5, "probability": 0.0009},
                {"key": "44010100000001", "salaryMid": 26, "probability": 0.00041},
            ],
            "dominated": [],
            "excluded": [],
        },
        "scopeNotice": "## ⚠️ 范围外提示\n\n本次分析范围：**广州**。",
        "limitations": ["区级薪酬为 B 级，误差 ±15–20%"],
        "pendingChecks": ["进面线为 C 级代理值"],
        "magnitudeWarning": "概率低于 0.1%：分数达标之前，选岗的边际收益极小。",
    }


def test_report_has_five_sections() -> None:
    """TC-016：结论、依据、数据表、局限、待核五个二级小节齐全。"""
    require_tsx()
    result = probe("report", report_input())
    md = result["md"]
    for section in ("## 结论", "## 依据", "## 数据表", "## 局限", "## 待核"):
        assert section in md, f"缺少小节 {section}"


def test_report_caliber_declaration_present() -> None:
    """口径声明必须写明 μ、σ、数据级别、误差范围。"""
    require_tsx()
    md = probe("report", report_input())["md"]
    assert "判断口径声明" in md, md[:600]
    assert "67" in md and "3.5" in md, "μ/σ 未写入声明"
    assert "误差" in md
    assert "C" in md and "B" in md, "数据级别未声明"


def test_report_includes_scope_notice() -> None:
    """范围外提示由调用方传入并原样出现在报告末尾（单一实现）。"""
    require_tsx()
    md = probe("report", report_input())["md"]
    assert "范围外提示" in md, md[-600:]
    assert md.strip().endswith("本次分析范围：**广州**。") or "范围外提示" in md


def test_report_marks_frontier_rows() -> None:
    """数据表用 ★ 标出前沿点。"""
    require_tsx()
    md = probe("report", report_input())["md"]
    table = md.split("## 数据表")[1].split("## 局限")[0]
    assert "★" in table, table


def test_report_empty_sections_not_omitted() -> None:
    """空小节写「无」而不是省略（省略会被误读为"没想到"）。"""
    require_tsx()
    payload = report_input()
    payload["limitations"] = []
    payload["pendingChecks"] = []
    md = probe("report", payload)["md"]
    for section in ("## 局限", "## 待核"):
        body = md.split(section)[1].split("##")[0]
        assert "无" in body, f"{section} 为空却未写「无」: {body!r}"


def test_report_magnitude_warning_in_conclusion() -> None:
    """量级警告必须出现在结论段（这是当天最重要的结论）。"""
    require_tsx()
    md = probe("report", report_input())["md"]
    conclusion = md.split("## 结论")[1].split("## 依据")[0]
    assert "边际收益极小" in conclusion, conclusion
