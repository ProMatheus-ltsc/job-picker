#!/usr/bin/env python3
"""薪酬估算统一调度器：两套算法都保留，由本脚本判断最终估算区间。

## 为什么有两套算法

同一份「单位的钱 ÷ 单位的人」有两条独立可走的路，它们**互证**而非替代：

| 算法 | 模块 | 口径 | 数据来源 | 强项 | 弱项 |
|------|------|------|----------|------|------|
| **A 预算双路径** | `budget_salary.py` | 部门**预算** | 预算公开表 | 内部自洽可验证（工会经费÷2% 与 工资福利−单位缴费 两条路径互证） | 不含在职人数，人数靠科室结构反推 |
| **B 决算实有人数** | `budget_salary_final_account.py` | 部门**决算** | 决算表 | 人数口径更实（在职/实有优先，编制只作降级） | 决算表版式杂、金额单位易错位 |

单用 A：人数是推算的，可能整体偏移；单用 B：只有一条路径，没有交叉校验。
**两者都跑，用它们的重叠程度判断可信度**，这是本脚本存在的理由。

## 输出

```json
{
  "methods": {
    "budget_dual_path":  { "available": true, "perCapitaWan": [20.8, 26.0], "confidence": "medium", ... },
    "final_account":     { "available": true, "perCapitaWan": [21.5, 25.5], "confidence": "high", ... }
  },
  "estimate": {
    "perCapitaWan": [20.8, 26.0],   // 最终区间 = 两法并集（保守，不掩盖分歧）
    "weightedMid": 24.1,             // 加权参考值 = 按置信度加权的区间中点
    "agreement": "overlap",          // overlap | wide | single | none
    "recommended": "final_account",  // 推荐主用哪一套
    "reason": "两法区间重叠 74%，B 的在职人数为一手口径，优先采信；A 作交叉校验"
  },
  "yearPackageWan": [20.3, 25.3]
}
```

## 用法

```bash
# 两套都跑（需要能读决算表与预算科目）
python3 scripts/budget_salary_estimate.py --final-account 决算表.xlsx --budget-json 预算科目.json

# 只跑预算双路径
python3 scripts/budget_salary_estimate.py --budget-json 预算科目.json

# 只跑决算法
python3 scripts/budget_salary_estimate.py --final-account 决算表.xlsx

# 自检（造样本验证合成逻辑）
python3 scripts/budget_salary_estimate.py --selftest
```

> **不引入新的第三方依赖**：算法 B 依赖的解析器已随 `budget_salary_final_account.py` 一并入库；
> 算法 A 只用标准库。缺可选依赖时对应方法标记为不可用，区间自动退化为单法结果并说明原因。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# 置信度权重：用于把两法的区间中点合成一个加权参考值。
# B（决算实有人数）权重更高——人数是一手口径，而 A 的人数是结构反推。
CONFIDENCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}

# 年全包 / 应发 的系数（与 budget_salary.py 保持一致：0.975 = 1 − 个人扣缴14.5% + 双边公积金24% 的合并口径）
PACKAGE_RATE = 0.975

# 两法区间重叠度低于此值 → 判为「分歧」，必须人工核对
OVERLAP_MIN = 0.3


def _force_utf8_stdio() -> None:
    """把 stdout/stderr 固定为 UTF-8（Windows GBK 控制台下输出中文会崩）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _overlap_ratio(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """两个区间的重叠比例（相对于较小区间的宽度）。"""
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if hi <= lo:
        return 0.0
    narrow = min(a[1] - a[0], b[1] - b[0])
    if narrow <= 0:
        return 1.0
    return (hi - lo) / narrow


def run_budget_dual_path(budget_json: str, unit: str = "") -> Dict[str, Any]:
    """算法 A：部门预算双路径（工会经费÷2% 与 工资福利−单位缴费互证）。"""
    try:
        import budget_salary as A  # type: ignore
    except ImportError as error:  # pragma: no cover - 依赖缺失
        return {"available": False, "reason": f"算法 A 不可用：{error}"}

    try:
        payload = json.loads(Path(budget_json).read_text(encoding="utf-8"))
        subjects = payload.get("subjects") or payload
        subjects = {k: v for k, v in subjects.items() if k not in {"unit", "subjects"}}
        result = A.compute(subjects, None)
    except Exception as error:  # noqa: BLE001 - 单法失败不应中断另一法
        return {"available": False, "reason": f"算法 A 执行失败：{error}"}

    if not result.get("usable"):
        return {
            "available": False,
            "reason": "算法 A 未产出可用结论",
            "blockedBy": result.get("blockedBy"),
            "anomalies": result.get("anomalies"),
        }

    low = float(result["perCapitaPreTaxMin"])
    high = float(result["perCapitaPreTaxMax"])
    # 人数是结构反推 → 置信度不高于 medium
    confidence = "medium"
    return {
        "available": True,
        "method": "budget_dual_path",
        "label": "部门预算双路径",
        "perCapitaWan": [round(low, 2), round(high, 2)],
        "confidence": confidence,
        "basis": "工资总额 = [301]工资福利 − 单位缴费（路径 B）；与工会经费÷2%（路径 A）互证",
        "pathDiffRatio": result.get("pathDiffRatio"),
        "headcountRange": result.get("headcountRange"),
        "anomalies": result.get("anomalies"),
        "unit": unit or str(payload.get("unit") or ""),
    }


def run_final_account(path: str, headcount: Optional[int] = None,
                      net_factor: float = 0.8) -> Dict[str, Any]:
    """算法 B：部门决算实有人数。"""
    try:
        import budget_salary_final_account as B  # type: ignore
    except ImportError as error:  # pragma: no cover - 依赖缺失
        return {"available": False, "reason": f"算法 B 不可用：{error}"}

    try:
        result = B.analyze(
            Path(path),
            headcount,
            "",       # unit_override
            "",       # sheet_hint
            net_factor,
            False,    # strict
            False,    # no_headcount
            0.0,      # social_wage
            1.0, 2.0,  # base_k
        )
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - 单法失败不应中断另一法
        return {"available": False, "reason": f"算法 B 执行失败：{error}"}

    data = result.as_dict()
    low = data.get("per_capita_low")
    high = data.get("per_capita_high")
    if low is None or high is None:
        per_capita = data.get("per_capita_wan")
        if per_capita is None:
            return {"available": False, "reason": "算法 B 未产出人均值"}
        low = high = float(per_capita)
    else:
        low, high = float(low), float(high)

    # 人数是「在职/实有」口径 → 置信度 high；只有编制数时降级
    basis = str(data.get("headcount_basis") or "")
    confidence = "high" if ("实有" in basis or "在职" in basis) else "medium"
    if data.get("degraded"):
        confidence = "low"

    return {
        "available": True,
        "method": "final_account",
        "label": "部门决算实有人数",
        "perCapitaWan": [round(low, 2), round(high, 2)],
        "confidence": confidence,
        "basis": f"工资福利支出 ÷ {basis}" if basis else "工资福利支出 ÷ 在职人数",
        "headcount": data.get("headcount"),
        "headcountBasis": basis,
        "warnings": data.get("warnings"),
        "degraded": data.get("degraded"),
        "unit": data.get("unit_name") or data.get("unit") or "",
    }


def combine(methods: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """把可用方法合成最终区间 + 加权参考值 + 选用建议。"""
    usable = [m for m in methods.values() if m.get("available")]
    if not usable:
        return {
            "perCapitaWan": None,
            "weightedMid": None,
            "agreement": "none",
            "recommended": None,
            "reason": "两套算法均未产出可用结论",
        }

    if len(usable) == 1:
        only = usable[0]
        low, high = only["perCapitaWan"]
        return {
            "perCapitaWan": [low, high],
            "weightedMid": round((low + high) / 2, 2),
            "agreement": "single",
            "recommended": only["method"],
            "reason": (
                f"仅「{only['label']}」可用，区间即其结果（误差来自该法自身的不确定度）；"
                f"另一套不可用时无法交叉校验。"
            ),
        }

    a, b = usable[0], usable[1]
    (a_lo, a_hi), (b_lo, b_hi) = a["perCapitaWan"], b["perCapitaWan"]
    overlap = _overlap_ratio((a_lo, a_hi), (b_lo, b_hi))

    # 最终区间取并集：两法都不否认的范围，掩盖不了分歧
    final_lo, final_hi = min(a_lo, b_lo), max(a_hi, b_hi)

    # 加权参考值：按置信度加权两个区间的中点
    w_a = CONFIDENCE_WEIGHT.get(a.get("confidence", "low"), 1.0)
    w_b = CONFIDENCE_WEIGHT.get(b.get("confidence", "low"), 1.0)
    mid_a, mid_b = (a_lo + a_hi) / 2, (b_lo + b_hi) / 2
    weighted = (mid_a * w_a + mid_b * w_b) / (w_a + w_b)

    if overlap >= 0.7:
        agreement = "overlap"
    elif overlap >= OVERLAP_MIN:
        agreement = "partial"
    else:
        agreement = "wide"

    # 推荐：置信度高的作主用，另一套作交叉校验；置信度相同则取区间更窄的（更精确）
    if a.get("confidence") != b.get("confidence"):
        order = {k: i for i, k in enumerate(
            sorted([a.get("confidence"), b.get("confidence")],
                   key=lambda c: -CONFIDENCE_WEIGHT.get(c, 1.0)))}
        recommended = a["method"] if order.get(a.get("confidence"), 0) <= order.get(b.get("confidence"), 0) else b["method"]
        reason = (
            f"两法区间重叠 {overlap:.0%}，"
            f"「{a['label']}」置信度 {a.get('confidence')}、"
            f"「{b['label']}」置信度 {b.get('confidence')}，"
            f"以置信度高的为主用，另一套作交叉校验。"
        )
    else:
        narrower = a if (a_hi - a_lo) <= (b_hi - b_lo) else b
        recommended = narrower["method"]
        reason = (
            f"两法置信度相同且区间重叠 {overlap:.0%}，"
            f"取区间更窄的「{narrower['label']}」为主用（更精确），另一套作交叉校验。"
        )

    if agreement == "wide":
        reason += (
            f" ⚠ 两法重叠仅 {overlap:.0%}，分歧较大，最终区间取并集（{final_lo}–{final_hi} 万）；"
            "这类情况必须人工核对原始文件后再用。"
        )

    return {
        "perCapitaWan": [round(final_lo, 2), round(final_hi, 2)],
        "weightedMid": round(weighted, 2),
        "agreement": agreement,
        "overlapRatio": round(overlap, 4),
        "recommended": recommended,
        "reason": reason,
    }


def build_estimate(args) -> Dict[str, Any]:
    methods: Dict[str, Dict[str, Any]] = {}
    if args.budget_json:
        methods["budget_dual_path"] = run_budget_dual_path(args.budget_json, args.unit)
    if args.final_account:
        methods["final_account"] = run_final_account(
            args.final_account, args.headcount, args.net_factor
        )
    if not methods:
        raise SystemExit("至少需要 --budget-json 或 --final-account 之一")

    estimate = combine(methods)
    per_capita = estimate.get("perCapitaWan")
    package = None
    if per_capita:
        package = [
            round(per_capita[0] * PACKAGE_RATE, 1),
            round(per_capita[1] * PACKAGE_RATE, 1),
        ]

    return {
        "version": "1.0",
        "methods": methods,
        "estimate": estimate,
        "perCapitaWan": per_capita,
        "yearPackageWan": package,
        "packageRate": PACKAGE_RATE,
        "grade": "A（一手预算/决算反推，误差取决于人数口径）",
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    """Markdown 输出：结论 → 两法明细 → 局限。"""
    methods = payload.get("methods") or {}
    estimate = payload.get("estimate") or {}
    lines = ["# 薪酬估算（双算法交叉校验）", ""]
    lines.append("> 两套算法都跑，用区间重叠程度判断可信度；最终区间取**并集**（保守，不掩盖分歧）。")
    lines.append("")

    lines.append("## 一、结论")
    lines.append("")
    per_capita = payload.get("perCapitaWan")
    package = payload.get("yearPackageWan")
    if not per_capita:
        lines.append("**无法估算**：两套算法均未产出可用结论。")
        for name, method in methods.items():
            if not method.get("available"):
                lines.append(f"- `{name}`：{method.get('reason')}")
        return "\n".join(lines) + "\n"

    lines.append(f"- 人均应发：**{per_capita[0]}–{per_capita[1]} 万元/年**（推算）")
    if package:
        lines.append(f"- 年全包：**{package[0]}–{package[1]} 万元**（到手 + 双边公积金）")
    if estimate.get("weightedMid") is not None:
        lines.append(f"- 加权参考值：**{estimate['weightedMid']} 万元**（按置信度加权，用作单点参考）")
    lines.append(f"- 一致性：**{estimate.get('agreement')}** ｜ 推荐主用：**{estimate.get('recommended')}**")
    lines.append("")
    lines.append(f"> {estimate.get('reason')}")
    lines.append("")

    lines.append("## 二、两法明细")
    lines.append("")
    lines.append("| 方法 | 可用 | 人均应发（万） | 置信度 | 依据 |")
    lines.append("|------|------|----------------|--------|------|")
    for name, method in methods.items():
        if not method.get("available"):
            lines.append(f"| {method.get('label') or name} | 否 | — | — | {method.get('reason')} |")
            continue
        low, high = method["perCapitaWan"]
        lines.append(
            f"| {method.get('label')} | 是 | {low}–{high} | {method.get('confidence')} | {method.get('basis')} |"
        )
    lines.append("")

    lines.append("## 三、局限")
    lines.append("")
    lines.append("- 人数口径决定误差主来源：决算法用「在职/实有」，预算法用科室结构反推（区间更宽）")
    lines.append("- 两法区间分歧大时（agreement=wide）必须人工核对原始文件，不能只看加权值")
    lines.append("- 加权参考值只是**单点参考**，对外给结论应给区间")
    return "\n".join(lines) + "\n"


def selftest() -> int:
    """自检：造样本验证合成逻辑（区间并集、加权、推荐）。"""
    # ① 两法高度重叠 → agreement=overlap，推荐置信度高者
    methods = {
        "budget_dual_path": {
            "available": True, "method": "budget_dual_path", "label": "A",
            "perCapitaWan": [20.0, 26.0], "confidence": "medium", "basis": "x",
        },
        "final_account": {
            "available": True, "method": "final_account", "label": "B",
            "perCapitaWan": [21.0, 25.0], "confidence": "high", "basis": "y",
        },
    }
    result = combine(methods)
    assert result["agreement"] == "overlap", result
    assert result["recommended"] == "final_account", result
    assert result["perCapitaWan"] == [20.0, 26.0], result
    assert 22.0 < result["weightedMid"] < 24.0, result

    # ② 单法可用 → agreement=single
    single = combine({"a": methods["budget_dual_path"], "b": {"available": False, "reason": "x"}})
    assert single["agreement"] == "single", single
    assert single["perCapitaWan"] == [20.0, 26.0], single

    # ③ 两法分歧 → agreement=wide，且区间取并集
    wide = combine({
        "a": {"available": True, "method": "a", "label": "A", "perCapitaWan": [10.0, 12.0],
              "confidence": "high", "basis": "x"},
        "b": {"available": True, "method": "b", "label": "B", "perCapitaWan": [30.0, 33.0],
              "confidence": "high", "basis": "y"},
    })
    assert wide["agreement"] == "wide", wide
    assert wide["perCapitaWan"] == [10.0, 33.0], wide

    # ④ 都不可用
    none = combine({"a": {"available": False, "reason": "x"}})
    assert none["agreement"] == "none", none
    assert none["perCapitaWan"] is None, none

    print("✓ budget_salary_estimate 自检通过（4 组）")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="薪酬估算统一调度（两套算法交叉校验）")
    parser.add_argument("--budget-json", default="", help="预算科目 JSON（算法 A 入口）")
    parser.add_argument("--final-account", default="", help="部门决算表（算法 B 入口）")
    parser.add_argument("--unit", default="", help="单位名")
    parser.add_argument("--headcount", type=int, default=None, help="在职人数（覆盖自动抽取）")
    parser.add_argument("--net-factor", type=float, default=0.8, help="现金性→到手的经验折算系数")
    parser.add_argument("--out", default="", help="输出 JSON 路径")
    parser.add_argument("--md", default="", help="输出 Markdown 路径")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.budget_json and not args.final_account:
        parser.print_help()
        return 2

    payload = build_estimate(args)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"✓ JSON → {out}")
    else:
        print(text)
    if args.md:
        md = Path(args.md)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(payload), encoding="utf-8")
        print(f"✓ Markdown → {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
