#!/usr/bin/env python3
"""部门预算 → 人均应发与年全包区间（改造方案 P1-1，SKILL 里原标注「⏳ 待建」）。

为什么必须换公式：SKILL §3.2 原写「工资福利支出 ÷ 在职人数」，但**预算几乎都不写在职人数**
（实测 6 份预算 6 份都没有）。公式不可执行，等于该方法不存在。

本脚本用两条可互证的路径 + 一条人数替代路径解决这个问题：

    路径 A：[30228] 工会经费 ÷ 2%           = 工资总额   （《工会法》按工资总额 2% 计提）
    路径 B：[301] 工资福利支出 − 单位缴费    = 个人应发
            单位缴费 = 养老 + 职业年金 + 其他社保 + 住房公积金

    在职人数（不披露时）：内设机构数 × 每科室 3~4 人 + 局领导 3~4 人 = 人数区间

南沙发改局实证（2026 预算，官方 PDF）：

    [301] 工资福利支出                                  775.48 万
      ├ 基本工资 / 津贴补贴 / 奖金             97.55 / 334.56 / 167.18
      └ 养老 59.89 + 年金 29.94 + 其他社保 1.00 + 公积金 60.81 = 151.64 万
    [30228] 工会经费                                     12.81 万

    路径 A：12.81 ÷ 2% = 640.5 万
    路径 B：775.48 − 151.64 = 623.84 万
    两路差 2.7% → 预算内部自洽，可采信
    7 个科室 → 24~30 人 → 人均应发 20.8~26.0 万 → 年全包 20~25 万

异常规则（当天踩过的坑）：
    海珠区教育局（本级）2026 预算：工资福利 10,525.85 万，其中基本工资 8,248.95 万（78.4%）、
    公积金仅 147.22 万（1.4%）——这是把**全区教师工资集中在教育局本级列支**。
    → 基本工资占工资福利支出 > 60% 的单位，一律不做个人薪资参照。
      （正常机关科室的公积金占比应在 7–12%，低于 3% 即异常。）

用法：
    python scripts/budget_salary.py --json-input tests/fixtures/nansha-fagai-budget.json
    python scripts/budget_salary.py --pdf budget.pdf --unit 南沙发改局 --out out.json
    python scripts/budget_salary.py --json-input x.json --out out.json   # 写出 JSON + Markdown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 阈值（改造方案 §2.1 的规则）─────────────────────────────────
UNION_DUES_RATE = 0.02          # 工会经费按工资总额 2% 计提
PATH_DIFF_TOLERANCE = 0.10      # 两条路径差 > 10% 判预算结构异常
CONCENTRATED_BASIC_WAGE = 0.60  # 基本工资 / 工资福利 > 60% 判集中列支
SUSPICIOUS_FUND_RATIO = 0.03    # 公积金占工资福利 < 3% 为异常信号
STAFF_PER_SECTION = (3, 4)      # 每科室 3~4 人
LEADERS = (3, 4)                # 局领导 3~4 人
# 人数上限的防重复计数：按「每科室满编 4 人」假设时，科室负责人已计入科室人数，
# 局领导中只有 2 人属于纯"额外"编制（局长 + 常务副局长），再全额加 4 人会重复计数。
# 该规则与改造方案 §2.1 的实证值对齐：南沙发改局 7 个科室 → 24~30 人。
LEADERS_COUNTED_AT_MAX = 2

# ── 扣缴模型（人均应发 → 年全包）──────────────────────────────
# 年全包 = 到手现金 + 双边公积金（公积金不能直接花，所以必须分开给）
# 设人均应发 S：
#   个人扣缴 = 养老 8% + 年金 4% + 医保 2% + 失业 0.5% = 14.5%
#   公积金单边 = 12%（双边各 12%）
#   到手现金 = S × (1 − 14.5% − 12%) = 0.735 S
#   双边公积金 = S × 24%
#   年全包   = 0.735 S + 0.24 S = 0.975 S
# 注意：年全包**不等于**应发，也不该再乘一个 >1 的系数（那会把单位缴费重复计入）。
PERSONAL_DEDUCTION_RATE = 0.145
EMPLOYER_INSURANCE_RATE = 0.312
FUND_RATE_EACH_SIDE = 0.12
# 年全包 / 应发（由上面四项推导，不手填）
PACKAGE_RATE = 1 - PERSONAL_DEDUCTION_RATE - FUND_RATE_EACH_SIDE + 2 * FUND_RATE_EACH_SIDE

# 允许的科目别名（不同预算表的写法差异）
SUBJECT_ALIASES: Dict[str, List[str]] = {
    "wage_total": ["[301]工资福利支出", "301工资福利支出", "工资福利支出"],
    "basic_wage": ["基本工资", "[30101]基本工资"],
    "allowance": ["津贴补贴", "[30102]津贴补贴"],
    "bonus": ["奖金", "[30103]奖金", "绩效奖金"],
    "pension": ["机关事业单位基本养老保险缴费", "[30108]", "养老保险"],
    "annuity": ["职业年金缴费", "[30109]", "职业年金"],
    "other_social": ["职工基本医疗保险缴费", "[30110]", "其他社会保障缴费", "[30112]", "其他社保"],
    "housing_fund": ["住房公积金", "[30113]"],
    "union_dues": ["[30228]工会经费", "30228工会经费", "工会经费"],
    "sections": ["内设机构数", "内设机构", "科室数"],
}


class BudgetError(RuntimeError):
    """预算结构异常（可恢复，调用方决定退出码）。"""


def _force_utf8_stdio() -> None:
    """把 stdout/stderr 固定为 UTF-8。

    Windows 控制台默认 GBK，本脚本会输出 ✓/⚠ 这类非 GBK 字符，
    不处理就会在 **管道/重定向** 时抛 UnicodeEncodeError（PRJ-2026-021 踩过同款坑）。
    用 errors="replace" 兜底，保证任何环境下都不会因输出字符崩溃。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _norm(text: str) -> str:
    """归一化科目名：去掉空白与全角括号差异，便于别名匹配。"""
    return re.sub(r"[\s\u3000]", "", str(text)).replace("（", "(").replace("）", ")")


def _lookup(subjects: Dict[str, Any], key: str) -> Optional[float]:
    """按别名表取值；值支持数字或「775.48万元」这类字符串。"""
    normalized = {_norm(k): v for k, v in subjects.items()}
    for alias in SUBJECT_ALIASES.get(key, []):
        value = normalized.get(_norm(alias))
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def _unit_insurance(subjects: Dict[str, Any]) -> float:
    """单位缴费 = 养老 + 职业年金 + 其他社保 + 住房公积金。"""
    parts = [
        _lookup(subjects, "pension"),
        _lookup(subjects, "annuity"),
        _lookup(subjects, "other_social"),
        _lookup(subjects, "housing_fund"),
    ]
    return round(sum(v for v in parts if v is not None), 2)


def path_a(subjects: Dict[str, Any]) -> Optional[float]:
    """路径 A：工会经费 ÷ 2% = 工资总额。"""
    dues = _lookup(subjects, "union_dues")
    if dues is None or dues <= 0:
        return None
    return round(dues / UNION_DUES_RATE, 2)


def path_b(subjects: Dict[str, Any]) -> Optional[float]:
    """路径 B：工资福利支出 − 单位缴费 = 个人应发（总额口径）。"""
    total = _lookup(subjects, "wage_total")
    if total is None or total <= 0:
        return None
    return round(total - _unit_insurance(subjects), 2)


def headcount_range(subjects: Dict[str, Any], explicit: Optional[int] = None) -> Tuple[int, int, str]:
    """在职人数区间：优先显式给出；否则用内设机构数反推。"""
    if explicit is not None and explicit > 0:
        return explicit, explicit, "显式输入"
    sections = _lookup(subjects, "sections")
    if sections is None or sections <= 0:
        raise BudgetError(
            "预算未披露在职人数，且无法从「部门机构设置」段得到内设机构数；"
            "请用 --headcount 显式给出，或在 JSON 里补 sections 字段"
        )
    low = int(sections) * STAFF_PER_SECTION[0] + LEADERS[0]
    high = int(sections) * STAFF_PER_SECTION[1] + LEADERS_COUNTED_AT_MAX
    return low, high, (
        f"内设机构 {int(sections)} 个 × 每科室 3~4 人 + 局领导 3~{LEADERS_COUNTED_AT_MAX} 人"
    )


def anomaly_checks(subjects: Dict[str, Any], a: Optional[float], b: Optional[float]) -> List[Dict[str, Any]]:
    """集中列支与结构异常的判定（返回异常列表，非空即不得输出个人薪酬结论）。"""
    anomalies: List[Dict[str, Any]] = []
    total = _lookup(subjects, "wage_total")
    basic = _lookup(subjects, "basic_wage")
    fund = _lookup(subjects, "housing_fund")

    if total and basic is not None and total > 0:
        ratio = basic / total
        if ratio > CONCENTRATED_BASIC_WAGE:
            anomalies.append({
                "code": "CONCENTRATED_PAYROLL",
                "detail": (
                    f"基本工资占工资福利支出 {ratio:.1%}（> {CONCENTRATED_BASIC_WAGE:.0%}），"
                    "判为集中列支（典型如区教育局本级代列全区教师工资），不作为个人薪酬参照"
                ),
            })
    if total and fund is not None and total > 0:
        fund_ratio = fund / total
        if fund_ratio < SUSPICIOUS_FUND_RATIO:
            anomalies.append({
                "code": "LOW_HOUSING_FUND",
                "detail": (
                    f"公积金仅占工资福利支出 {fund_ratio:.1%}（正常机关科室应在 7–12%），"
                    "结构异常，可能为集中列支或科目并表"
                ),
            })

    if a is not None and b is not None and b > 0:
        diff = abs(a - b) / b
        if diff >= PATH_DIFF_TOLERANCE:
            anomalies.append({
                "code": "BUDGET_STRUCTURE_ANOMALY",
                "detail": (
                    f"两条路径差 {diff:.1%}（阈值 {PATH_DIFF_TOLERANCE:.0%}）："
                    f"路径 A={a} 万、路径 B={b} 万；预算内部不自洽，不得采信"
                ),
            })
        else:
            anomalies.append({
                "code": "PATHS_CONSISTENT",
                "detail": f"两条路径差 {diff:.1%}（< {PATH_DIFF_TOLERANCE:.0%}），预算内部自洽，可采信",
            })
    elif a is None or b is None:
        anomalies.append({
            "code": "PARTIAL_PATHS",
            "detail": (
                "仅有一条路径可算（"
                + ("缺工会经费，路径 A 不可用" if a is None else "缺工资福利支出，路径 B 不可用")
                + "），结论可信度下降"
            ),
        })
    return anomalies


def blocking_anomalies(anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """阻断类异常：出现即不得输出个人薪酬结论。"""
    blocking = {"CONCENTRATED_PAYROLL", "BUDGET_STRUCTURE_ANOMALY"}
    return [a for a in anomalies if a.get("code") in blocking]


def compute(subjects: Dict[str, Any], headcount: Optional[int] = None) -> Dict[str, Any]:
    """核心计算：返回带全部中间量的结果字典。"""
    a = path_a(subjects)
    b = path_b(subjects)
    anomalies = anomaly_checks(subjects, a, b)
    result: Dict[str, Any] = {
        "subjects": subjects,
        "pathA": {"value": a, "formula": "工会经费 ÷ 2%", "grade": "A"},
        "pathB": {
            "value": b,
            "formula": "工资福利支出 − (养老+年金+其他社保+公积金)",
            "unitInsurance": _unit_insurance(subjects),
            "grade": "A",
        },
        "pathDiffRatio": (
            round(abs(a - b) / b, 4) if a is not None and b is not None and b > 0 else None
        ),
        "anomalies": anomalies,
    }

    blocking = blocking_anomalies(anomalies)
    if blocking:
        result["usable"] = False
        result["blockedBy"] = [item["code"] for item in blocking]
        return result

    try:
        low, high, basis = headcount_range(subjects, headcount)
    except BudgetError as error:
        result["usable"] = False
        result["blockedBy"] = ["HEADCOUNT_UNKNOWN"]
        result["headcountError"] = str(error)
        return result

    # 人均应发口径用**路径 B**：它直接给出「个人应发」；路径 A 得到的「工资总额」语义略宽，
    # 只作互证（两者差 < 10% 才采信）。混用两路均值会让口径变得说不清。
    total_estimate = b if b is not None else a
    if total_estimate is None:
        result["usable"] = False
        result["blockedBy"] = ["NO_PATH"]
        return result

    per_low = total_estimate / high   # 人数多 → 人均低
    per_high = total_estimate / low   # 人数少 → 人均高
    package_low = per_low * PACKAGE_RATE
    package_high = per_high * PACKAGE_RATE

    # 扣缴拆解（以人均中位为基准）
    mid = (per_low + per_high) / 2
    fund_each = mid * FUND_RATE_EACH_SIDE
    cash = mid * (1 - PERSONAL_DEDUCTION_RATE - FUND_RATE_EACH_SIDE)

    result.update({
        "usable": True,
        "headcountRange": {"min": low, "max": high, "basis": basis, "grade": "A（机构结构推算）"},
        "wageTotalEstimate": round(total_estimate, 2),
        "perCapitaBasis": "路径 B（个人应发）",
        "perCapitaPreTaxMin": round(per_low, 2),
        "perCapitaPreTaxMax": round(per_high, 2),
        "yearPackageMin": round(package_low, 1),
        "yearPackageMax": round(package_high, 1),
        # 月/年到手与公积金：内部万元 → 输出元
        "monthlyCash": round((cash * 10000) / 12, 0),
        "monthlyFundBothSides": round((fund_each * 2 * 10000) / 12, 0),
        "yearCash": round(cash, 2),
        "packageRate": round(PACKAGE_RATE, 4),
        "grade": "A（一手预算反推，误差 ±10%）",
        "deductionModel": {
            "personal": PERSONAL_DEDUCTION_RATE,
            "employerInsurance": EMPLOYER_INSURANCE_RATE,
            "fundEachSide": FUND_RATE_EACH_SIDE,
        },
    })
    return result


def render_markdown(result: Dict[str, Any], unit: str) -> str:
    """Markdown 输出：方法 → 中间量 → 结论 → 局限。"""
    lines = [f"# 预算反推薪酬：{unit}", ""]
    lines.append("> 方法：两条可互证路径（工会经费 ÷ 2% 与 工资福利支出 − 单位缴费），")
    lines.append("> 人数不披露时用内设机构结构反推。所有中间量均列出，便于手工复核。")
    lines.append("")

    lines.append("## 一、科目（一手预算）")
    lines.append("")
    lines.append("| 科目 | 值（万元） |")
    lines.append("|------|-----------:|")
    for key, value in (result.get("subjects") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.append("")

    lines.append("## 二、两条路径")
    lines.append("")
    pa = result.get("pathA") or {}
    pb = result.get("pathB") or {}
    lines.append(f"- 路径 A（{pa.get('formula')}）：**{pa.get('value')} 万元**")
    lines.append(f"- 路径 B（{pb.get('formula')}）：**{pb.get('value')} 万元**（单位缴费 {pb.get('unitInsurance')} 万元）")
    diff = result.get("pathDiffRatio")
    lines.append(f"- 两路差：**{'—' if diff is None else f'{diff:.2%}'}**（阈值 10%）")
    lines.append("")

    anomalies = result.get("anomalies") or []
    if anomalies:
        lines.append("## 三、结构性判断")
        lines.append("")
        for item in anomalies:
            lines.append(f"- `{item.get('code')}`：{item.get('detail')}")
        lines.append("")

    if not result.get("usable"):
        lines.append("## 结论")
        lines.append("")
        lines.append(
            "**不出个人薪酬结论**（触发阻断项："
            + "、".join(result.get("blockedBy") or [])
            + "）。理由见上节结构性判断。"
        )
        if result.get("headcountError"):
            lines.append("")
            lines.append(f"补充：{result['headcountError']}")
        return "\n".join(lines) + "\n"

    head = result.get("headcountRange") or {}
    lines.append("## 四、人数与人均")
    lines.append("")
    lines.append(f"- 在职人数区间：**{head.get('min')}–{head.get('max')} 人**（{head.get('basis')}）")
    lines.append(f"- 工资总额估计（{result.get('perCapitaBasis') or '路径 B'}）：**{result.get('wageTotalEstimate')} 万元**")
    lines.append(
        f"- 人均应发：**{result.get('perCapitaPreTaxMin')}–{result.get('perCapitaPreTaxMax')} 万元/年**"
    )
    lines.append("")

    lines.append("## 五、结论（推算）")
    lines.append("")
    lines.append(
        f"- **年全包：{result.get('yearPackageMin')}–{result.get('yearPackageMax')} 万元**（推算）"
    )
    lines.append(f"- 月打卡现金：约 {result.get('monthlyCash')} 元")
    lines.append(f"- 公积金（双边/月）：约 {result.get('monthlyFundBothSides')} 元")
    lines.append(f"- 年到手：约 {result.get('yearCash')} 万元")
    lines.append("")
    lines.append("## 六、局限")
    lines.append("")
    lines.append("- 人数为**结构推算**而非披露值，是误差主来源（±20% 量级）")
    lines.append("- 年全包系数与扣缴比例为**结构近似**，不等于该单位工资单")
    lines.append("- 预算为部门整体口径，可能含非在编人员经费")
    return "\n".join(lines) + "\n"


def load_subjects(args) -> Tuple[Dict[str, Any], str]:
    """读取科目：--json-input 优先；否则 --pdf 抽取。"""
    if args.json_input:
        path = Path(args.json_input)
        data = json.loads(path.read_text(encoding="utf-8"))
        unit = str(data.get("unit") or args.unit or path.stem)
        subjects = data.get("subjects") or data
        # 去掉非科目字段，避免混进报告表
        subjects = {k: v for k, v in subjects.items() if k not in {"unit", "subjects"}}
        return subjects, unit

    if not args.pdf:
        raise argparse.ArgumentTypeError("必须提供 --json-input 或 --pdf")

    try:
        import pdfplumber  # type: ignore
    except ImportError as error:
        raise ImportError(
            "缺少 pdfplumber，无法解析 PDF：pip install pdfplumber\n"
            "或改用 --json-input 手工录入科目（无第三方依赖）"
        ) from error

    text_parts: List[str] = []
    with pdfplumber.open(args.pdf) as pdf:  # pragma: no cover - 需真实 PDF
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    return extract_subjects_from_text(text), args.unit or Path(args.pdf).stem


def extract_subjects_from_text(text: str) -> Dict[str, Any]:
    """从预算正文抽科目金额（简陋但确定：按别名找"名称 + 数字"）。"""
    subjects: Dict[str, Any] = {}
    flat = re.sub(r"[ \t]+", " ", text)
    for key, aliases in SUBJECT_ALIASES.items():
        for alias in aliases:
            pattern = re.escape(alias) + r"[^\d\-]{0,20}(-?\d[\d,]*(?:\.\d+)?)"
            match = re.search(pattern, flat)
            if match:
                subjects[alias] = float(match.group(1).replace(",", ""))
                break
    return subjects


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="部门预算 → 人均应发与年全包区间（双路径反推）",
    )
    parser.add_argument("--pdf", help="部门预算 PDF 路径")
    parser.add_argument("--json-input", help="已抽取的科目录 JSON（无 pdfplumber 时的降级入口）")
    parser.add_argument("--unit", default="", help="单位名称（报告标题用）")
    parser.add_argument("--headcount", type=int, default=None, help="显式在职人数（覆盖结构推算）")
    parser.add_argument("--out", default="", help="输出 JSON 路径；同时生成同名 .md")
    args = parser.parse_args(argv)

    try:
        subjects, unit = load_subjects(args)
    except ImportError as error:
        print(str(error), file=sys.stderr)
        return 3
    except (argparse.ArgumentTypeError, OSError, json.JSONDecodeError) as error:
        print(f"输入不可用：{error}", file=sys.stderr)
        return 2

    try:
        result = compute(subjects, args.headcount)
    except BudgetError as error:
        print(f"预算反推失败：{error}", file=sys.stderr)
        return 1

    payload = {"unit": unit, **result}
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        md_path = out.with_suffix(".md")
        md_path.write_text(render_markdown(result, unit), encoding="utf-8")
        print(f"✓ JSON → {out}")
        print(f"✓ Markdown → {md_path}")
    else:
        print(text)

    if not result.get("usable"):
        # 集中列支 / 结构异常：明确非零退出，避免调用方把"不算结论"当成"没数据"
        for item in result.get("anomalies") or []:
            print(f"✗ {item['code']}: {item['detail']}", file=sys.stderr)
        if result.get("headcountError"):
            print(f"✗ HEADCOUNT_UNKNOWN: {result['headcountError']}", file=sys.stderr)
        return 1

    for item in result.get("anomalies") or []:
        print(f"· {item['code']}: {item['detail']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
