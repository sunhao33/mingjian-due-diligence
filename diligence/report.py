"""报告生成 —— 将指标、规则命中、研判叙述汇总为 Markdown 尽调报告。"""
from datetime import date

from .rules import risk_level


def _pct(value):
    return f"{value:.1%}" if value is not None else "—"


def _ratio(value):
    return f"{value:.2f}" if value is not None else "—"


def _has_trace(company):
    """是否展示「抽取自校正轨迹」：仅当走大模型抽取且发生过补救轮次。"""
    trace = company.get("_trace") or []
    return len(trace) > 1


def build_report(company, metrics, rules, narrative=None, warnings=None):
    years = sorted(metrics.keys())
    latest_year = years[-1]
    latest = metrics[latest_year]
    prev = metrics[years[-2]] if len(years) > 1 else None
    level = risk_level(rules)

    # 章节号随「是否出现数据校验 / 抽取轨迹」动态编排，避免空节占号
    names = (["关键财务指标"] + (["数据校验"] if warnings else [])
             + (["抽取自校正轨迹"] if _has_trace(company) else [])
             + ["风险清单", "风险研判"])
    no = {n: "一二三四五六七八九十"[i] for i, n in enumerate(names)}

    lines = []
    lines.append(f"# 财务尽调初筛报告")
    lines.append("")
    lines.append(f"- **标的企业**：{company['company_name']}")
    lines.append(f"- **所属行业**：{company['industry']}")
    lines.append(f"- **报告期**：{latest_year}" + (f"（对比 {years[-2]}）" if prev else ""))
    src = company.get("_source")
    if src:
        used = src.get("pages_used") or [None, None]
        lines.append(f"- **数据来源**：{src.get('file', '年报 PDF')}"
                     f"（共 {src.get('pages_total', '—')} 页，自动定位第 {used[0]}–{used[1]} 页，"
                     f"抽取模型 {src.get('model', '—')}）")
    lines.append(f"- **生成日期**：{date.today().isoformat()}")
    lines.append(f"- **综合风险等级**：**{level}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 关键财务指标
    lines.append(f"## {no['关键财务指标']}、关键财务指标")
    lines.append("")
    lines.append("| 指标 | 上一期 | 本期 | 说明 |")
    lines.append("|------|--------|------|------|")
    rows = [
        ("资产负债率", lambda m: _pct(m["资产负债率"]), "越低偿债压力越小"),
        ("流动比率", lambda m: _ratio(m["流动比率"]), "短期偿债能力"),
        ("毛利率", lambda m: _pct(m["毛利率"]), "产品盈利能力"),
        ("净利率", lambda m: _pct(m["净利率"]), "整体盈利能力"),
        ("ROE", lambda m: _pct(m["roe"]), "净资产回报"),
        ("应收账款周转率", lambda m: _ratio(m["应收账款周转率"]), "回款效率"),
        ("存货周转率", lambda m: _ratio(m["存货周转率"]), "存货运营效率"),
        ("净现比", lambda m: _ratio(m["净现比"]), "利润的现金含量"),
        ("营收增长率", lambda m: _pct(m["营收增长率"]), "成长性"),
        ("商誉占净资产比", lambda m: _pct(m["商誉占净资产比"]), "减值风险敞口"),
    ]
    for name, fn, note in rows:
        pv = fn(prev) if prev else "—"
        cv = fn(latest)
        lines.append(f"| {name} | {pv} | {cv} | {note} |")
    lines.append("")
    lines.append("> 口径说明：有上期数据时，周转率采用期初期末平均余额；"
                 "利息保障倍数 EBIT ≈ 净利润 + 财务费用（未加回所得税）；"
                 "ROE = 净利润 / 净资产；缺失科目一律记为「—」，不按 0 参与计算。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 数据校验（仅在发现问题时出现）
    if warnings:
        lines.append(f"## {no['数据校验']}、数据校验")
        lines.append("")
        lines.append("以下为**抽取数据的自洽性告警**，不影响规则执行，但提示结论所依赖的数据可能不可靠，建议回溯原始报表核对：")
        lines.append("")
        for w in warnings:
            prefix = f"第 {w['year']} 期：" if w.get("year") else ""
            lines.append(f"- {prefix}**{w['name']}** —— {w['detail']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 抽取自校正轨迹（仅在确实发生过补救轮次时出现）
    if _has_trace(company):
        from .agent import format_trace

        lines.append(f"## {no['抽取自校正轨迹']}、抽取自校正轨迹")
        lines.append("")
        lines.append("本次抽取启用了**自校正闭环**：每轮抽完先做数据自洽性校验，"
                     "若发现矛盾，由模型诊断成因并选择补救动作（补充提示 / 调整页区间 / 接受），"
                     "直至校验通过或达到轮数上限。以下为实际决策轨迹：")
        lines.append("")
        for line in format_trace(company["_trace"]):
            lines.append(f"- {line}" if line.startswith("第 ") else f"  {line}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 风险清单
    lines.append(f"## {no['风险清单']}、风险清单")
    lines.append("")
    if not rules:
        lines.append("未命中显著风险规则，标的财务表现整体稳健。")
    else:
        for i, r in enumerate(rules, 1):
            lines.append(f"### 风险 {i}：{r['name']}（{r['severity']} · {r['category']}）")
            lines.append(f"{r['detail']}。")
            for e in r["evidence"]:
                lines.append(f"- 证据：{e}")
            lines.append("")
    lines.append("---")
    lines.append("")

    # 风险研判
    lines.append(f"## {no['风险研判']}、风险研判")
    lines.append("")
    if narrative:
        lines.append(narrative)
        lines.append("")
    else:
        top = rules[:3]
        if top:
            lines.append("重点关注以下风险：")
            for r in top:
                lines.append(f"- **{r['name']}**：{r['detail']}。")
        else:
            lines.append("标的财务指标未出现显著异常，可作为正常标的进入下一阶段评估。")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 免责声明：本报告仅供研究参考，不构成投资建议。")
    lines.append("")
    return "\n".join(lines)
