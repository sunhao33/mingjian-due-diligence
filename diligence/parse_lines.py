"""规则抽取兜底：不调用大模型，直接从定位到的报表页文本抽取三大报表科目。

用途与定位：
- **离线可用**：没有 API Key、没有网络也能端到端产出结构化数据（真实案例演示、回归对照）；
- **可对照**：与大模型抽取互为验证 —— 两者数值若不一致，说明有一方读错了；
- **不适用**：扫描件（无文本层）；栏目严重错位的表格。

已实测适配三种真实年报版式：
| 报告 | 标题 | 单位 | 列结构 |
|------|------|------|--------|
| 万科 2024 | 合并资产负债表 | 元 | 本期 / 上期 |
| 工商银行 2024 | 合并及公司资产负债表 | 百万元 | 合并本期 / 合并上期 / 公司本期 / 公司上期 |
| 美的集团 2024 | 2024年度合并及公司利润表 | 千元 | 同上（四列）|
"""

import re

from .locate import diagnose
from .normalize import normalize_company

# 单位声明 -> 换算到「万元」的乘数
_UNIT_RE = re.compile(
    r"(?:金额单位[均为]*|单位)\s*[：:]?\s*"
    r"(?:\(?（?除特别注明外[，,]?\s*)?"
    r"(?:人民币)?\s*(百万元|千元|万元|元)"
)
_UNIT_FACTORS = {"百万元": 100.0, "千元": 0.1, "万元": 1.0, "元": 0.0001}

# 金额：带千分位，或 ≥5 位连续数字；圆括号表示负数
_AMOUNT_RE = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\d{5,}(?:\.\d+)?")
_YEAR_RE = re.compile(r"(20\d{2})\s*年")

# (归属报表, 目标字段, [行名正则...])。顺序重要：更具体的行名必须排在前面。
# 一律用 ^ 锚定行首，否则「负债合计」会命中「流动负债合计」、
# 「股东权益合计」会命中「归属于母公司股东权益合计」——这类子串误匹配
# 在真实年报上已实际发生，会算出看似合理却错误的数值。
_FIELDS = [
    ("income", "归母净利润", [r"^归属于母公司(?:股东|所有者)的净"]),
    ("income", "净利润", [r"^[一二三四五六七八九十\d、.（）()\s]*净\s*[（(]亏损[)）]\s*/\s*利润",
                          r"^[一二三四五六七八九十\d、.（）()\s]*净利润"]),
    ("income", "营业收入", [r"^[一二三四五六七八九十\d、.（）()\s]*营业总收入",
                            r"^[一二三四五六七八九十\d、.（）()\s]*营业收入"]),
    ("income", "营业成本", [r"^减[：:]\s*营业成本", r"^营业成本"]),
    ("income", "财务费用", [r"^(?:其中[：:])?\s*财务费用"]),
    ("balance_sheet", "总资产", [r"^资产总计"]),
    ("balance_sheet", "总负债", [r"^负债合计"]),
    ("balance_sheet", "净资产", [r"^(?:股东权益合计|所有者权益合计|"
                                 r"所有者权益（或股东权益）合计)"]),
    ("balance_sheet", "流动资产合计", [r"^流动资产合计"]),
    ("balance_sheet", "流动负债合计", [r"^流动负债合计"]),
    ("balance_sheet", "货币资金", [r"^货币资金"]),
    ("balance_sheet", "应收账款", [r"^应收账款"]),
    ("balance_sheet", "存货", [r"^存货"]),
    ("balance_sheet", "商誉", [r"^商誉"]),
    ("balance_sheet", "短期借款", [r"^短期借款"]),
    ("balance_sheet", "应付账款", [r"^应付账款"]),
    ("balance_sheet", "长期借款", [r"^长期借款"]),
    ("balance_sheet", "一年内到期的非流动负债", [r"^一年内到期的非流动负债"]),
    ("balance_sheet", "应付债券", [r"^应付债券"]),
    ("cashflow", "经营活动现金流净额", [
        # 兼容行名里插入方向说明的写法，例如美的集团：
        #   经营活动产生/(使用)的现金流量净额 四(64)(h) 53,345,930 …
        # 与利润表的「净 (亏损) / 利润」属同一类陷阱（美的是惯犯）。
        r"^经营活动.{0,12}现金流量净额",
    ]),
]

_COMPILED = [(g, f, [re.compile(p) for p in pats]) for g, f, pats in _FIELDS]

# 需要保留符号的字段（可正可负）；其余字段按「金额绝对值」处理。
# 真实年报中成本费用常以括号负数列报（美的 2024：减：营业成本 四(49) (299,584,935)），
# 若原样保留负号，毛利率会算成 173% 这种离谱值，故统一取绝对值。
_SIGNED_FIELDS = {"净利润", "归母净利润"}


def detect_unit(text, default=0.0001):
    """识别报表金额单位，返回换算到万元的乘数（默认按「元」处理）。"""
    m = _UNIT_RE.search(text)
    if not m:
        return default
    return _UNIT_FACTORS.get(m.group(1), default)


def line_amounts(line):
    """抽取一行里的金额列表（保留顺序，圆括号为负）。"""
    out = []
    for m in _AMOUNT_RE.finditer(line):
        s = m.group(0)
        neg = s.startswith("(") and s.endswith(")")
        try:
            v = float(s.strip("()").replace(",", ""))
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def _claim(line):
    """返回该行首个命中的 (报表, 字段, 金额列表)；未命中返回 None。

    先 strip 再匹配，配合 _FIELDS 里的 ^ 锚定，避免子串误命中。
    """
    line = line.strip()
    if not line:
        return None
    for group, field, pats in _COMPILED:
        if any(p.search(line) for p in pats):
            vals = line_amounts(line)
            if len(vals) >= 1:
                return group, field, vals
    return None


def detect_years(texts, income_page, fallback=(2024, 2023)):
    """从利润表页头部识别两个报告期年份（返回 (上期, 本期)）。"""
    if income_page is None:
        return fallback
    head = "\n".join(texts[income_page].splitlines()[:6])
    years = []
    for y in _YEAR_RE.findall(head):
        if y not in years:
            years.append(y)
    if len(years) >= 2:
        return int(years[1]), int(years[0])
    return fallback


def detect_audit_opinion(texts, start, end):
    """识别审计意见类型。

    只在「一、审计意见」段落的结论性表述里判断——真实年报的「关键审计事项」
    会大量讨论持续经营、减值等话题，扫全文会把标准无保留意见误判为非标
    （万科 2024 年报实测踩过这个坑）。
    """
    blob = "\n".join(texts[start:end + 1])
    m = re.search(r"一、审计意见(.{0,900}?)(?=二、|形成审计意见的基础|$)", blob, re.S)
    section = m.group(1) if m else ""
    if not section:
        return "标准无保留意见"          # 取不到意见段落时不臆断
    for kw in ("无法表示意见", "否定意见", "保留意见"):
        if kw in section:
            return kw
    if "强调事项段" in section or "持续经营重大不确定性" in section:
        return "带强调事项段"
    return "标准无保留意见"


def parse_company(texts, company_name, industry, diag=None):
    """从页面文本解析出公司结构化数据（两期）。返回 (company, report)。"""
    diag = diag or diagnose(texts)
    start, end = diag["range"][0] - 1, diag["range"][1] - 1
    blob = "\n".join(texts[start:end + 1])
    factor = detect_unit(blob)
    income_page = (diag["statements"].get("利润表") or {}).get("chosen")
    y_prev, y_cur = detect_years(texts, (income_page - 1) if income_page else None)

    picked = {}          # (group, field) -> (金额列表, 页码, 原文行)
    for i in range(start, end + 1):
        for line in texts[i].splitlines():
            hit = _claim(line)
            if not hit:
                continue
            group, field, vals = hit
            if (group, field) in picked:
                continue
            picked[(group, field)] = (vals, i + 1, line.strip()[:70])

    periods = []
    for year, idx in ((y_prev, 1), (y_cur, 0)):
        periods.append({
            "year": year,
            "balance_sheet": {}, "income": {}, "cashflow": {},
            "audit_opinion": (detect_audit_opinion(texts, start, end) if idx == 0
                              else "标准无保留意见"),
        })
    for (group, field), (vals, _page, _line) in picked.items():
        if field == "归母净利润":
            continue                      # 归母仅作参考，不进指标口径
        signed = field in _SIGNED_FIELDS
        cur_v = vals[0] if signed else abs(vals[0])
        periods[1][group][field] = round(cur_v * factor, 2)
        if len(vals) >= 2:
            prev_v = vals[1] if signed else abs(vals[1])
            periods[0][group][field] = round(prev_v * factor, 2)

    company = {"company_name": company_name, "industry": industry, "periods": periods}
    normalize_company(company)

    report = {
        "unit_factor": factor,
        "years": [y_prev, y_cur],
        "fields_found": len(picked),
        "source_lines": {f"{g}.{f}": (v[1], v[2]) for (g, f), v in picked.items()},
    }
    company["_source"] = {
        "file": f"（规则抽取）{company_name}",
        "pages_total": len(texts),
        "pages_used": [start + 1, end + 1],
        "chars": len(blob),
        "model": "rule-based parse_lines",
    }
    return company, report
