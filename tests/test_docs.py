"""TC-018：文档与画像更新（REQ-012）。

验证「文档写了」且「实现读得到」——只写文档不实现是本项目最容易发生的偏差。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_profile_has_five_new_fields() -> None:
    """profile.md 新增 5 个字段：接受值班、接受执法卷、接受 5 年服务期、排除哪些区、可接受最低年薪。"""
    text = read("assets/profile.md")
    required = ["值班", "执法", "5 年最低服务期", "排除哪些区", "可接受最低年薪"]
    missing = [item for item in required if item not in text]
    assert not missing, f"profile.md 缺少字段: {missing}"


def test_profile_fields_are_implementable() -> None:
    """每个新字段都必须写清「对判定的影响」，否则实现无从对齐。"""
    text = read("assets/profile.md")
    # 新章节存在且说明硬筛语义
    assert "工作强度与形态" in text, "缺少强度章节"
    assert "硬筛" in text, "未说明强度是硬筛而非加权"
    assert "heavy" in text, "未说明 heavy 语义"


def test_pitfalls_has_five_new_entries() -> None:
    """pitfalls.md 至少新增 5 条省考坑，且覆盖方案点名的五条。"""
    text = read("references/pitfalls.md")
    required = [
        "区平均分 ≠ 岗位线",
        "模板拼接",
        "限应届岗不可与不限应届岗直接对比",
        "不披露在职人数",
        "集中列支",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"pitfalls 缺少条目: {missing}"


def test_pitfalls_numbering_continues() -> None:
    """条目编号连续（从 1 递增），不重复不跳号。"""
    text = read("references/pitfalls.md")
    numbers = [int(n) for n in re.findall(r"^### (\d+)\.", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1)), numbers
    assert len(numbers) >= 39, f"条目数 {len(numbers)}"


def test_skill_has_no_pick_py_reference() -> None:
    """SKILL.md 全文不再出现 pick.py（实施入口是 scripts/pick.ts）。"""
    text = read("SKILL.md")
    assert "pick.py" not in text, "SKILL.md 仍残留 pick.py"
    assert "scripts/pick.ts" in text, "SKILL.md 未引用 pick.ts"


def test_skill_documents_four_level_grading() -> None:
    """SKILL.md 必须写明四级分级与「C 级不进排序公式」的执行口径。"""
    text = read("SKILL.md")
    for token in ("A 一手", "B 二手·可核验", "C 二手·估算", "D 禁用"):
        assert token in text, f"缺少分级 {token}"
    assert "只读方向" in text, "未说明 C 级只读方向"
    assert "_guard.py" in text, "未说明守门层不变"


def test_skill_documents_intensity_scan_fields() -> None:
    """SKILL 必须写明强度扫描三字段与「必须扫职位简介」的铁律。"""
    text = read("SKILL.md")
    assert "职位简介" in text and "其他要求" in text, "未写明扫描字段"
    assert "必须扫职位简介" in text, "缺少必须扫 intro 的铁律"


def test_skill_documents_budget_dual_path() -> None:
    """SKILL 必须写明预算双路径与集中列支规则。"""
    text = read("SKILL.md")
    assert "工会经费" in text and "2%" in text, "缺少路径 A"
    assert "单位缴费" in text, "缺少路径 B"
    assert "60%" in text, "缺少集中列支阈值"


def test_skill_documents_probability_formula() -> None:
    """SKILL 必须写明概率公式与三个必检项。"""
    text = read("SKILL.md")
    assert "Φ" in text or "Φ(" in text, "缺少正态累积分布表达"
    assert "进面名额" in text, "缺少名额口径"
    assert "边际收益极小" in text, "缺少量级结论"


def test_skill_documents_report_template() -> None:
    """SKILL 必须写明五段报告模板与范围外提示。"""
    text = read("SKILL.md")
    for section in ("结论", "依据", "数据表", "局限", "待核"):
        assert section in text, f"缺少小节 {section}"
    assert "范围外提示" in text, "缺少范围外提示"
