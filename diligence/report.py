"""报告生成 —— 将指标、规则命中、研判叙述汇总为 Markdown 尽调报告。"""
from datetime import date

from .rules import risk_level


def _fmt(value, unit=""):
    if value is None:
        return "—"
    return f"{value:,.0f}{unit}"


def _pct(value):
    return f"{value:.1%}" if value is not None else "—"


def _ratio(value):
    return f"{value:.2f}" if value is not None else "—"


def build_report(company, metrics, rules, narrative=None):
    years = sorted(metrics.keys())
    latest_year = years[-1]
    latest = metrics[latest_year]
    prev = metrics[years[-2]] if len(years) > 1 else None
    level = risk_level(rules)

    lines = []
    lines.append(f"# 财务尽调初筛报告")
    lines.append("")
    lines.append(f"- **标的企业**：{company['company_name']}")
    lines.append(f"- **所属行业**：{company['industry']}")
    lines.append(f"- **报告期**：{latest_year}" + (f"（对比 {years[-2]}）" if prev else ""))
    lines.append(f"- **生成日期**：{date.today().isoformat()}")
    lines.append(f"- **综合风险等级**：**{level}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 一、关键财务指标
    lines.append("## 一、关键财务指标")
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
    lines.append("---")
    lines.append("")

    # 二、风险清单
    lines.append("## 二、风险清单")
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

    # 三、风险研判
    lines.append("## 三、风险研判")
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
