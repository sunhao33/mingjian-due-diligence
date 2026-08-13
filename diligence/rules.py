"""风控规则引擎 —— 每条规则命中后输出风险项（含证据引用）。

规则集中在此处，便于按行业、按机构扩展与配置。
"""

# 风险等级 -> 排序权重（越高越靠前）
_SEVERITY_ORDER = {"高": 3, "中": 2, "低": 1}


def _debt_limit(industry):
    """按行业返回资产负债率参考线；金融类返回 None（不适用通用阈值）。"""
    i = industry or ""
    if "地产" in i or "房地产" in i:
        return 0.85
    if "建筑" in i:
        return 0.80
    if "酒" in i or "食品" in i or "饮料" in i:
        return 0.50
    if "银行" in i or "保险" in i or "证券" in i or "金融" in i:
        return None
    return 0.70


def evaluate_rules(company, metrics):
    """根据指标命中规则，返回风险项列表。

    返回: [{"category": str, "name": str, "severity": str,
            "detail": str, "evidence": [str]}, ...]
    """
    years = sorted(metrics.keys())
    latest = metrics[years[-1]]
    prev = metrics[years[-2]] if len(years) > 1 else None
    audit = company["periods"][-1].get("audit_opinion", "标准无保留意见")

    hits = []

    def hit(category, name, severity, detail, evidence):
        hits.append({
            "category": category,
            "name": name,
            "severity": severity,
            "detail": detail,
            "evidence": evidence,
        })

    # ── 偿债能力（按行业基准）──
    debt_limit = _debt_limit(company.get("industry", ""))
    if (
        debt_limit is not None
        and latest["资产负债率"] is not None
        and latest["资产负债率"] > debt_limit
    ):
        hit("偿债", "资产负债率偏高", "高",
            f"资产负债率 {latest['资产负债率']:.1%}，超过 {company.get('industry', '行业')} {debt_limit:.0%} 参考线",
            [f"总负债 / 总资产 = {latest['资产负债率']:.1%}（行业参考 {debt_limit:.0%}）"])
    if latest["流动比率"] is not None and latest["流动比率"] < 1.0:
        hit("偿债", "流动比率偏低", "中",
            f"流动比率 {latest['流动比率']:.2f}，低于 1，短期偿债压力较大",
            [f"流动资产 / 流动负债 = {latest['流动比率']:.2f}"])

    # 利息保障倍数（仅当确有净利息支出时判断，避免净利息收入公司误报）
    if latest.get("财务费用") is not None and latest["财务费用"] > 0:
        icr = latest.get("利息保障倍数")
        if icr is not None and icr < 1:
            hit("偿债", "利息保障倍数过低", "高",
                f"利息保障倍数 {icr:.2f}，经营利润已不足以覆盖利息支出",
                [f"EBIT/利息 = {icr:.2f}（利息支出 {latest['财务费用']:,.0f} 万元）"])
        elif icr is not None and icr < 2:
            hit("偿债", "利息保障倍数偏低", "中",
                f"利息保障倍数 {icr:.2f}，利息覆盖能力偏弱",
                [f"EBIT/利息 = {icr:.2f}"])

    # ── 盈利 / 现金流质量 ──
    if (
        (latest["净利润"] or 0) > 0
        and latest["经营活动现金流净额"] is not None
        and latest["经营活动现金流净额"] < 0
    ):
        hit("现金流", "利润缺乏现金支撑", "高",
            "净利润为正但经营活动现金流为负，利润质量存疑",
            [f"净利润 {latest['净利润']:.0f} 万元，经营现金流净额 {latest['经营活动现金流净额']:.0f} 万元"])
    elif latest["净现比"] is not None and 0 <= latest["净现比"] < 0.5:
        hit("现金流", "净现比偏低", "中",
            f"净现比 {latest['净现比']:.2f}，经营现金流对利润覆盖不足",
            [f"经营现金流净额 / 净利润 = {latest['净现比']:.2f}"])

    # 经营现金流同比恶化（本期转负或大幅下滑）
    if (
        prev is not None
        and prev.get("经营活动现金流净额") is not None
        and prev["经营活动现金流净额"] > 0
        and latest["经营活动现金流净额"] is not None
    ):
        if latest["经营活动现金流净额"] < 0:
            hit("现金流", "经营现金流转负", "高",
                "经营活动现金流由正转负，造血能力恶化",
                [f"经营现金流净额：{prev['经营活动现金流净额']:,.0f} → "
                 f"{latest['经营活动现金流净额']:,.0f} 万元"])
        elif latest["经营活动现金流净额"] < 0.5 * prev["经营活动现金流净额"]:
            hit("现金流", "经营现金流大幅下滑", "中",
                "经营活动现金流同比下滑超过 50%",
                [f"经营现金流净额：{prev['经营活动现金流净额']:,.0f} → "
                 f"{latest['经营活动现金流净额']:,.0f} 万元"])

    # ── 收入质量 ──
    if latest["应收账款占营收比"] is not None and latest["应收账款占营收比"] > 0.30:
        hit("收入", "应收账款占比过高", "中",
            f"应收账款占营收 {latest['应收账款占营收比']:.1%}，收入回款质量需关注",
            [f"应收账款 / 营业收入 = {latest['应收账款占营收比']:.1%}"])

    # ── 毛利率同比恶化 ──
    if prev is not None and latest["毛利率"] is not None and prev["毛利率"] is not None:
        drop_pp = (prev["毛利率"] - latest["毛利率"]) * 100  # 下降的百分点数（正数）
        if drop_pp > 10:
            hit("盈利", "毛利率大幅下滑", "高",
                f"毛利率同比下降 {drop_pp:.1f} 个百分点（{prev['毛利率']:.1%} → {latest['毛利率']:.1%}）",
                [f"毛利率下降 {drop_pp:.1f} 个百分点"])
        elif drop_pp > 4:
            hit("盈利", "毛利率下滑", "中",
                f"毛利率同比下降 {drop_pp:.1f} 个百分点（{prev['毛利率']:.1%} → {latest['毛利率']:.1%}）",
                [f"毛利率下降 {drop_pp:.1f} 个百分点"])

    # ── 盈利 / 成长能力 ──
    if latest["净利润"] is not None and latest["净利润"] < 0:
        hit("盈利", "经营亏损", "高",
            f"净利润为负（{latest['净利润']:,.0f} 万元），公司处于亏损状态",
            [f"净利润 = {latest['净利润']:,.0f} 万元"])
    elif latest["净利润增长率"] is not None:
        if latest["净利润增长率"] < -0.50:
            hit("成长", "净利润大幅下滑", "高",
                f"净利润同比下滑 {latest['净利润增长率']:.1%}",
                [f"净利润增长率 = {latest['净利润增长率']:.1%}"])
        elif latest["净利润增长率"] < -0.20:
            hit("成长", "净利润下滑", "中",
                f"净利润同比下滑 {latest['净利润增长率']:.1%}",
                [f"净利润增长率 = {latest['净利润增长率']:.1%}"])

    if latest["营收增长率"] is not None and latest["营收增长率"] < -0.30:
        hit("成长", "营收大幅下滑", "高",
            f"营业收入同比下滑 {latest['营收增长率']:.1%}",
            [f"营收增长率 = {latest['营收增长率']:.1%}"])
    elif latest["营收增长率"] is not None and latest["营收增长率"] < 0:
        hit("成长", "营收负增长", "中",
            f"营业收入同比下滑 {latest['营收增长率']:.1%}",
            [f"营收增长率 = {latest['营收增长率']:.1%}"])

    # ── 减值 / 资产质量 ──
    if latest["商誉占净资产比"] is not None and latest["商誉占净资产比"] > 0.30:
        hit("资产", "商誉减值风险", "高",
            f"商誉占净资产 {latest['商誉占净资产比']:.1%}，存在大额商誉减值风险",
            [f"商誉 / 净资产 = {latest['商誉占净资产比']:.1%}"])

    # ── 存贷双高（财务粉饰嫌疑）──
    if (
        latest["货币资金占总资产比"] is not None
        and latest["有息负债占总资产比"] is not None
        and latest["货币资金占总资产比"] > 0.15
        and latest["有息负债占总资产比"] > 0.30
    ):
        hit("粉饰", "存贷双高", "高",
            "货币资金与有息负债同时偏高，存在资金占用或财务粉饰嫌疑",
            [f"货币资金占总资产 {latest['货币资金占总资产比']:.1%}",
             f"有息负债占总资产 {latest['有息负债占总资产比']:.1%}"])

    # ── 审计意见 ──
    if audit != "标准无保留意见":
        hit("合规", "非标准审计意见", "高",
            f"审计意见为「{audit}」",
            [f"审计意见：{audit}"])

    # 按严重程度排序
    hits.sort(key=lambda h: _SEVERITY_ORDER.get(h["severity"], 0), reverse=True)
    return hits


def risk_level(hits):
    """根据命中规则推导综合风险等级。"""
    highs = sum(1 for h in hits if h["severity"] == "高")
    mediums = sum(1 for h in hits if h["severity"] == "中")
    if highs >= 2:
        return "高风险"
    if highs == 1 and mediums >= 1:
        return "高风险"
    if highs == 1:
        return "中风险"
    if mediums >= 3:
        return "中风险"
    if mediums >= 1:
        return "关注"
    return "低风险"
