"""尽调主流程：结构化财报 -> 指标 -> 规则 -> 研判 -> 报告。"""
from .metrics import compute_metrics
from .rules import evaluate_rules, risk_level
from .report import build_report
from .llm import summarize_risks


def run_diligence(company, use_llm=True):
    """执行完整尽调闭环，返回 (report_markdown, result_dict)。"""
    metrics = compute_metrics(company)
    rules = evaluate_rules(company, metrics)

    narrative = None
    if use_llm:
        narrative = summarize_risks(company, metrics, rules)

    report = build_report(company, metrics, rules, narrative=narrative)

    result = {
        "company": company["company_name"],
        "industry": company["industry"],
        "risk_level": risk_level(rules),
        "metrics": metrics,
        "rules": rules,
        "narrative": narrative,
    }
    return report, result
