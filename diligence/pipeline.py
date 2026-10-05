"""尽调主流程：结构化财报 -> 指标 -> 规则 -> 研判 -> 报告。"""
from .html_report import render_html
from .metrics import compute_metrics
from .rules import evaluate_rules, risk_level
from .report import build_report
from .validate import check_company


def run_diligence(company, use_llm=True):
    """执行完整尽调闭环，返回 (report_markdown, result_dict)。

    result 同时提供两种报告：Markdown（给开发者/二次处理）与
    自包含 HTML（给普通人——浏览器双击即开，可直接打印成 PDF）。
    """
    metrics = compute_metrics(company)
    rules = evaluate_rules(company, metrics)
    warnings = check_company(company)  # 先给数据做体检，再下风险结论

    narrative = None
    if use_llm:
        # 惰性导入：纯规则模式（--no-llm）不需要 openai / dotenv 参与
        from .llm import summarize_risks

        narrative = summarize_risks(company, metrics, rules)

    report = build_report(company, metrics, rules, narrative=narrative,
                          warnings=warnings)
    html_report = render_html(company, metrics, rules, narrative=narrative,
                              warnings=warnings, trace=company.get("_trace"))

    result = {
        "company": company["company_name"],
        "industry": company["industry"],
        "risk_level": risk_level(rules),
        "metrics": metrics,
        "rules": rules,
        "narrative": narrative,
        "warnings": warnings,
        "trace": company.get("_trace"),
        "source": company.get("_source"),      # 数据来源/公告出处，供界面展示
        "html": html_report,                   # 自包含 HTML 报告（浏览器可直接打开/打印）
    }
    return report, result
