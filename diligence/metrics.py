"""财务指标计算 —— 纯 Python 实现，数值计算不交给 LLM，保证准确与可复现。

缺失科目一律返回 None，绝不当作 0 参与运算：把「取不到数」静默当成 0 会算出
看似合理的错值（例如营业成本缺失时毛利率会变成 100%），进而让下游规则漏报风险。
"""


def _div(numerator, denominator):
    """安全除法，分母为 0 或任一为空时返回 None。"""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _sub(a, b):
    """相减；任一为 None 时返回 None（缺失科目不当 0）。"""
    if a is None or b is None:
        return None
    return a - b


def _add(a, b):
    """相加；任一为 None 时返回 None。"""
    if a is None or b is None:
        return None
    return a + b


def _avg(cur, prev):
    """期初期末平均余额；上期缺失时退化为期末余额；本期缺失返回 None。"""
    if cur is None:
        return None
    if prev is None:
        return cur
    return (cur + prev) / 2


def compute_metrics(company):
    """为每个报告期计算财务指标。

    company: {"company_name": str, "industry": str,
              "periods": [{"year": int, "balance_sheet": {...}, "income": {...},
                           "cashflow": {...}, "audit_opinion": str}, ...]}
    返回: {str(year): {指标名: float|None}, ...}

    口径说明（详见 README「指标口径与已知近似」）：
    - 周转率在存在上期数据时使用「期初期末平均余额」，否则退化为期末余额；
    - 利息保障倍数用 EBIT ≈ 净利润 + 财务费用（未加回所得税，属近似口径）；
    - ROE / 净现比使用「净利润」，分母为「净资产 / 营业收入」全口径（含少数股东权益）。
    """
    periods = sorted(company["periods"], key=lambda p: p["year"])
    result = {}

    for i, p in enumerate(periods):
        bs = p["balance_sheet"]
        inc = p["income"]
        cf = p["cashflow"]
        prev_bs = periods[i - 1]["balance_sheet"] if i > 0 else None
        prev_inc = periods[i - 1]["income"] if i > 0 else None
        m = {}

        # 偿债能力
        m["流动比率"] = _div(bs.get("流动资产合计"), bs.get("流动负债合计"))
        m["速动比率"] = _div(
            _sub(bs.get("流动资产合计"), bs.get("存货")),
            bs.get("流动负债合计"),
        )
        m["资产负债率"] = _div(bs.get("总负债"), bs.get("总资产"))

        # 盈利能力
        m["毛利率"] = _div(
            _sub(inc.get("营业收入"), inc.get("营业成本")),
            inc.get("营业收入"),
        )
        m["净利率"] = _div(inc.get("净利润"), inc.get("营业收入"))
        m["roe"] = _div(inc.get("净利润"), bs.get("净资产"))
        m["roa"] = _div(inc.get("净利润"), bs.get("总资产"))

        # 营运能力（有上期数据时用期初期末平均余额）
        m["应收账款周转率"] = _div(
            inc.get("营业收入"),
            _avg(bs.get("应收账款"), prev_bs.get("应收账款") if prev_bs else None),
        )
        m["存货周转率"] = _div(
            inc.get("营业成本"),
            _avg(bs.get("存货"), prev_bs.get("存货") if prev_bs else None),
        )

        # 现金流质量 / 结构
        m["净现比"] = _div(cf.get("经营活动现金流净额"), inc.get("净利润"))
        m["应收账款占营收比"] = _div(bs.get("应收账款"), inc.get("营业收入"))
        m["商誉占净资产比"] = _div(bs.get("商誉"), bs.get("净资产"))
        m["货币资金占总资产比"] = _div(bs.get("货币资金"), bs.get("总资产"))
        m["有息负债占总资产比"] = _div(bs.get("有息负债"), bs.get("总资产"))

        ebit = _add(inc.get("净利润"), inc.get("财务费用"))
        m["利息保障倍数"] = _div(ebit, inc.get("财务费用"))

        # 成长能力（需要上一期）
        if prev_inc is not None:
            m["营收增长率"] = _div(
                _sub(inc.get("营业收入"), prev_inc.get("营业收入")),
                prev_inc.get("营业收入"),
            )
            m["净利润增长率"] = _div(
                _sub(inc.get("净利润"), prev_inc.get("净利润")),
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
