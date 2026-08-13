"""财务指标计算 —— 纯 Python 实现，数值计算不交给 LLM，保证准确与可复现。"""


def _div(numerator, denominator):
    """安全除法，分母为 0 或任一为空时返回 None。"""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _pct(value):
    return f"{value:.1%}" if value is not None else "—"


def compute_metrics(company):
    """为每个报告期计算财务指标。

    company: {"company_name": str, "industry": str,
              "periods": [{"year": int, "balance_sheet": {...}, "income": {...},
                           "cashflow": {...}, "audit_opinion": str}, ...]}
    返回: {str(year): {指标名: float|None}, ...}
    """
    periods = sorted(company["periods"], key=lambda p: p["year"])
    result = {}

    for i, p in enumerate(periods):
        bs = p["balance_sheet"]
        inc = p["income"]
        cf = p["cashflow"]
        m = {}

        # 偿债能力
        m["流动比率"] = _div(bs.get("流动资产合计"), bs.get("流动负债合计"))
        m["速动比率"] = _div(
            (bs.get("流动资产合计") or 0) - (bs.get("存货") or 0),
            bs.get("流动负债合计"),
        )
        m["资产负债率"] = _div(bs.get("总负债"), bs.get("总资产"))

        # 盈利能力
        m["毛利率"] = _div(
            (inc.get("营业收入") or 0) - (inc.get("营业成本") or 0),
            inc.get("营业收入"),
        )
        m["净利率"] = _div(inc.get("净利润"), inc.get("营业收入"))
        m["roe"] = _div(inc.get("净利润"), bs.get("净资产"))
        m["roa"] = _div(inc.get("净利润"), bs.get("总资产"))

        # 营运能力
        m["应收账款周转率"] = _div(inc.get("营业收入"), bs.get("应收账款"))
        m["存货周转率"] = _div(inc.get("营业成本"), bs.get("存货"))

        # 现金流质量 / 结构
        m["净现比"] = _div(cf.get("经营活动现金流净额"), inc.get("净利润"))
        m["应收账款占营收比"] = _div(bs.get("应收账款"), inc.get("营业收入"))
        m["商誉占净资产比"] = _div(bs.get("商誉"), bs.get("净资产"))
        m["货币资金占总资产比"] = _div(bs.get("货币资金"), bs.get("总资产"))
        m["有息负债占总资产比"] = _div(bs.get("有息负债"), bs.get("总资产"))

        ebit = (inc.get("净利润") or 0) + (inc.get("财务费用") or 0)
        m["利息保障倍数"] = _div(ebit, inc.get("财务费用"))

        # 成长能力（需要上一期）
        if i > 0:
            prev_inc = periods[i - 1]["income"]
            m["营收增长率"] = _div(
                (inc.get("营业收入") or 0) - (prev_inc.get("营业收入") or 0),
                prev_inc.get("营业收入"),
            )
            m["净利润增长率"] = _div(
                (inc.get("净利润") or 0) - (prev_inc.get("净利润") or 0),
                prev_inc.get("净利润"),
            )
        else:
            m["营收增长率"] = None
            m["净利润增长率"] = None

        # 原始值留档，便于规则与报告直接引用
        m["经营活动现金流净额"] = cf.get("经营活动现金流净额")
        m["净利润"] = inc.get("净利润")
        m["财务费用"] = inc.get("财务费用")

        result[str(p["year"])] = m

    return result
