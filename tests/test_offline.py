# -*- coding: utf-8 -*-
"""明鉴 · 离线自测：只依赖标准库，无网络、无 API Key。

运行：python tests/test_offline.py
覆盖：指标口径、缺失科目处理（回归）、规则命中、风险分级、报告渲染。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from diligence.metrics import compute_metrics           # noqa: E402
from diligence.report import build_report              # noqa: E402
from diligence.rules import evaluate_rules, risk_level  # noqa: E402
from diligence.sample_data import SAMPLES              # noqa: E402
from diligence.validate import check_company           # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def approx(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


def period(year, bs=None, inc=None, cf=None, audit="标准无保留意见"):
    """构造一期报表，dict 里的 None 表示该科目缺失。"""
    d = {
        "year": year,
        "balance_sheet": {
            "货币资金": 60000, "应收账款": 25000, "存货": 30000,
            "流动资产合计": 160000, "商誉": 5000, "总资产": 280000,
            "短期借款": 10000, "应付账款": 25000, "流动负债合计": 80000,
            "长期借款": 20000, "有息负债": 30000, "总负债": 120000, "净资产": 160000,
        },
        "income": {"营业收入": 250000, "营业成本": 165000,
                   "财务费用": 5000, "净利润": 35000},
        "cashflow": {"经营活动现金流净额": 40000},
        "audit_opinion": audit,
    }
    d["balance_sheet"].update(bs or {})
    d["income"].update(inc or {})
    d["cashflow"].update(cf or {})
    return d


def company(periods, industry="制造业"):
    return {"company_name": "测试样本", "industry": industry, "periods": periods}


# ── 样例闭环 ──
@case
def test_sample_healthy_is_low_risk():
    m = compute_metrics(SAMPLES["healthy"])
    hits = evaluate_rules(SAMPLES["healthy"], m)
    assert hits == [], f"健康样本不应命中规则，实际 {[h['name'] for h in hits]}"
    assert risk_level(hits) == "低风险"


@case
def test_sample_risky_is_high_risk():
    m = compute_metrics(SAMPLES["risky"])
    hits = evaluate_rules(SAMPLES["risky"], m)
    sev = [h["severity"] for h in hits]
    assert len(hits) == 8, f"风险样本应命中 8 条，实际 {len(hits)}"
    assert sev.count("高") == 5 and sev.count("中") == 3, sev
    assert risk_level(hits) == "高风险"


# ── 缺失科目不得被当成 0（回归用例）──
@case
def test_missing_cost_does_not_fake_100pct_margin():
    c = company([period(2024, inc={"营业成本": None})])
    metrics = compute_metrics(c)
    assert metrics["2024"]["毛利率"] is None, \
        f"营业成本缺失时毛利率应为 None，实际 {metrics['2024']['毛利率']}"
    hits = evaluate_rules(c, metrics)
    assert all("毛利率" not in h["name"] for h in hits)


@case
def test_missing_current_assets_does_not_go_negative():
    c = company([period(2024, bs={"流动资产合计": None, "存货": None})])
    m = compute_metrics(c)["2024"]
    assert m["速动比率"] is None, f"应为 None，实际 {m['速动比率']}"
    assert m["流动比率"] is None


@case
def test_missing_net_profit_skips_icr_and_loss_rule():
    c = company([period(2024, inc={"净利润": None})])
    metrics = compute_metrics(c)
    m = metrics["2024"]
    assert m["利息保障倍数"] is None, f"应为 None，实际 {m['利息保障倍数']}"
    assert m["净现比"] is None
    hits = evaluate_rules(c, metrics)
    assert all(h["name"] != "经营亏损" for h in hits), "净利润缺失不应判为亏损"


@case
def test_missing_prev_revenue_does_not_fake_growth():
    c = company([period(2023, inc={"营业收入": None}), period(2024)])
    metrics = compute_metrics(c)
    assert metrics["2024"]["营收增长率"] is None, \
        f"上期营收缺失时增长率应为 None，实际 {metrics['2024']['营收增长率']}"
    hits = evaluate_rules(c, metrics)
    assert all(h["category"] != "成长" for h in hits)


@case
def test_metrics_source_has_no_or_zero_fallback():
    path = os.path.join(ROOT, "diligence", "metrics.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "or 0" not in src, "metrics.py 不应再用 `or 0` 兜底缺失科目"


# ── 口径 ──
@case
def test_turnover_uses_average_balance():
    m = compute_metrics(SAMPLES["risky"])["2024"]
    expect = 200000 / ((50000 + 80000) / 2)      # (期初 + 期末) / 2
    assert approx(m["应收账款周转率"], expect), \
        f"应为 {expect:.4f}，实际 {m['应收账款周转率']}"


@case
def test_audit_opinion_taken_from_latest_year():
    # periods 顺序颠倒，规则仍须取年份最大那期的审计意见
    c = company([period(2024, audit="保留意见"), period(2023)])
    m = compute_metrics(c)
    hits = evaluate_rules(c, m)
    assert any(h["name"] == "非标准审计意见" for h in hits), \
        f"实际命中 {[h['name'] for h in hits]}"


# ── 分级与措辞 ──
@case
def test_risk_level_mapping():
    def hits(high, medium):
        return ([{"severity": "高"}] * high) + ([{"severity": "中"}] * medium)

    assert risk_level(hits(0, 0)) == "低风险"
    assert risk_level(hits(0, 1)) == "关注"
    assert risk_level(hits(0, 3)) == "中风险"
    assert risk_level(hits(1, 0)) == "中风险"
    assert risk_level(hits(1, 1)) == "高风险"
    assert risk_level(hits(2, 0)) == "高风险"


@case
def test_no_double_negative_wording():
    m = compute_metrics(SAMPLES["risky"])
    hits = evaluate_rules(SAMPLES["risky"], m)
    for h in hits:
        assert "下滑 -" not in h["detail"], h["detail"]
        for e in h["evidence"]:
            assert "下滑 -" not in e, e
    report = build_report(SAMPLES["risky"], m, hits)
    assert "下滑 -" not in report, "报告中出现「下滑 -x%」双负数措辞"


# ── 报告 ──
@case
def test_report_contains_evidence_and_caliber():
    m = compute_metrics(SAMPLES["risky"])
    hits = evaluate_rules(SAMPLES["risky"], m)
    report = build_report(SAMPLES["risky"], m, hits)
    assert report.startswith("# 财务尽调初筛报告")
    assert "证据：" in report
    assert "口径说明" in report
    assert "综合风险等级" in report


@case
def test_extract_prompt_covers_real_report_pitfalls():
    """万科 2024 年报实测发现的坑：括号表示负数、亏损公司的插入式行名。"""
    try:
        from diligence.extract import _EXTRACT_SYSTEM as S
    except ImportError:
        print("      (跳过：未安装 pdfplumber，本项需依赖环境)")
        return
    assert "括号" in S and "负数" in S, \
        "抽取提示词必须说明「圆括号表示负数」，否则亏损会被读成盈利"
    assert "净 (亏损) / 利润" in S, \
        "抽取提示词必须覆盖亏损公司的行名变体「净 (亏损) / 利润」"
    assert "归属于母公司股东的净利润" in S


# ── 数据自洽性校验（把抽取错误变成显式告警）──
@case
def test_validate_silent_on_builtin_samples():
    for name in ("risky", "healthy"):
        w = check_company(SAMPLES[name])
        assert w == [], f"{name} 样例不应产生校验告警，实际 {[x['name'] for x in w]}"


@case
def test_validate_detects_balance_identity_break():
    c = company([period(2024, bs={"总资产": 500000, "总负债": 300000, "净资产": 100000})])
    names = [w["name"] for w in check_company(c)]
    assert "会计恒等式不符" in names, names


@case
def test_validate_detects_insolvency():
    c = company([period(2024, bs={"总资产": 500000, "总负债": 560000, "净资产": -60000})])
    names = [w["name"] for w in check_company(c)]
    assert "资不抵债" in names, names


@case
def test_validate_detects_sign_error_via_margin_relation():
    # 模拟模型漏读括号：把亏损 8 万读成盈利，净利率会高于毛利率
    c = company([period(2024, inc={"营业收入": 200000, "营业成本": 140000,
                                   "净利润": 80000})])
    names = [w["name"] for w in check_company(c)]
    assert "净利率高于毛利率" in names, names


@case
def test_validate_flags_single_period():
    c = company([period(2024)])
    names = [w["name"] for w in check_company(c)]
    assert "仅抽取到单期数据" in names, names


@case
def test_report_shows_validation_section_only_when_warned():
    dirty = company([period(2024, bs={"总资产": 500000, "总负债": 560000,
                                      "净资产": -60000})])
    m = compute_metrics(dirty)
    rep = build_report(dirty, m, evaluate_rules(dirty, m),
                       warnings=check_company(dirty))
    assert "数据校验" in rep and "资不抵债" in rep
    clean = SAMPLES["healthy"]
    m2 = compute_metrics(clean)
    rep2 = build_report(clean, m2, evaluate_rules(clean, m2))
    assert "数据校验" not in rep2, "无告警时不应出现校验章节"


@case
def test_validate_allows_profit_to_loss_swing():
    """回归：由盈利转亏损时净利润降幅天然超过 100%，不得误报（万科 2024 真实情形）。"""
    c = company([period(2023, inc={"营业收入": 46573907, "营业成本": 39478386,
                                   "净利润": 2045556}),
                 period(2024, inc={"营业收入": 34317644, "营业成本": 30826487,
                                   "净利润": -4870393})])
    names = [w["name"] for w in check_company(c)]
    assert "净利润增长率失真" not in names, names
    assert names == [], f"真实的盈亏反转不应产生告警，实际 {names}"


@case
def test_validate_still_flags_impossible_revenue_drop():
    c = company([period(2023, inc={"营业收入": 100000}),
                 period(2024, inc={"营业收入": -5000})])
    names = [w["name"] for w in check_company(c)]
    assert "营收降幅失真" in names, names


# ── 报表页面定位（纯标准库逻辑，零依赖）──
@case
def test_locate_never_returns_inverted_range():
    """回归：工行年报曾导致 (195, 44) 这样的反向区间，切片为空且不报错。"""
    from diligence.locate import locate_statement_pages

    pages = ["目录"] * 250
    pages[2] = "目录\n合并资产负债表 ...... 206\n现金流量表 ...... 210"
    pages[195] = ("审计报告\n一、审计意见\n我们审计了……包括2024年12月31日的"
                  "合并及公司资产负债表、2024年度的合并及公司利润表、"
                  "股东权益变动表和现金流量表以及相关财务报表附注。")
    pages[41] = "现金流量表 ...... 210\n资产负债表 ...... 206"      # 目录残留
    start, end = locate_statement_pages(None, pages)
    assert start <= end, f"区间不得反向：{start}~{end}"


@case
def test_locate_picks_real_statement_pages_not_audit_report():
    from diligence.locate import locate_statement_pages

    money = " ".join(f"{i:,}.00" for i in range(12_000_000, 12_000_040))
    pages = ["封面"] * 250
    pages[1] = "目录\n合并资产负债表 ...... 206\n合并利润表 ...... 208"
    pages[195] = ("审计报告\n一、审计意见\n我们审计了……包括合并及公司资产负债表、"
                  "合并及公司利润表、股东权益变动表和现金流量表。")
    pages[205] = f"合并资产负债表\n资产总计 {money}\n负债合计 {money}"
    pages[207] = f"合并利润表\n营业收入 {money}\n净利润 {money}"
    pages[209] = f"现金流量表\n经营活动产生的现金流量净额 {money}"
    start, end = locate_statement_pages(None, pages)
    assert start <= 205 <= end, f"未覆盖资产负债表页：{start}~{end}"
    assert start <= 209 <= end, f"未覆盖现金流量表页：{start}~{end}"
    assert start <= 195, f"审计意见页应落在区间内（区间 {start}~{end}）"
    assert start > 41, f"不应把目录页当起点：{start}"


@case
def test_locate_falls_back_to_full_document():
    from diligence.locate import locate_statement_pages

    pages = ["无关内容"] * 30
    start, end = locate_statement_pages(None, pages)
    assert (start, end) == (0, 29), f"认不出报表时应退回全文，实际 {start}~{end}"


@case
def test_diagnose_explains_chosen_pages():
    """定位诊断：说明数据来自哪几页，供报告标注与排障。"""
    from diligence.locate import diagnose, format_diagnosis

    money = " ".join(f"{i:,}.00" for i in range(9_000_000, 9_000_030))
    pages = ["封面"] * 120
    pages[1] = "目录\n合并资产负债表 ...... 60"
    pages[59] = f"合并资产负债表\n资产总计 {money}"
    pages[61] = f"合并利润表\n营业收入 {money}"
    pages[63] = f"现金流量表\n经营活动产生的现金流量净额 {money}"
    diag = diagnose(pages)
    assert diag["pages"] == 120
    assert diag["statements"]["资产负债表"]["chosen"] == 60, diag["statements"]
    assert diag["statements"]["利润表"]["chosen"] == 62, diag["statements"]
    assert diag["statements"]["现金流量表"]["chosen"] == 64, diag["statements"]
    assert diag["range"][0] <= 60 <= diag["range"][1]
    text = "\n".join(format_diagnosis(diag))
    assert "资产负债表：选中 P60" in text, text


@case
def test_diagnose_marks_missing_statement():
    from diligence.locate import diagnose

    pages = ["无报表内容"] * 10
    diag = diagnose(pages)
    assert diag["statements"]["资产负债表"]["chosen"] is None
    assert diag["range"] == [1, 10], diag["range"]


@case
def test_report_shows_data_source_when_available():
    c = dict(SAMPLES["healthy"])
    c["_source"] = {"file": "某年报.pdf", "pages_total": 410,
                    "pages_used": [195, 219], "model": "deepseek-chat"}
    m = compute_metrics(c)
    rep = build_report(c, m, evaluate_rules(c, m))
    assert "数据来源" in rep and "195–219" in rep, rep[:400]
    # 样例数据没有来源信息时，不应出现该行
    c2 = SAMPLES["healthy"]
    rep2 = build_report(c2, compute_metrics(c2), evaluate_rules(c2, compute_metrics(c2)))
    assert "数据来源" not in rep2


# ── 规则抽取兜底（纯标准库，零依赖）──
def _pages(*lines_groups):
    """把若干「页」拼成页面文本列表。"""
    return ["\n".join(g) for g in lines_groups]


@case
def test_parse_lines_unit_detection():
    """真实年报三种单位并存：万科用元、美的用千元、工行用百万元。"""
    from diligence.parse_lines import detect_unit

    assert detect_unit("编制单位：万科 单位：元 币种：人民币") == 0.0001
    assert detect_unit("(除特别注明外，金额单位为人民币千元)") == 0.1
    assert detect_unit("（除特别注明外，金额单位均为人民币百万元）") == 100.0
    assert detect_unit("单位：万元") == 1.0
    # 千元换算方向必须是「除以 10」：1 千元 = 0.1 万元
    assert detect_unit("金额单位为人民币千元") < 1


@case
def test_parse_lines_amounts_and_parentheses():
    from diligence.parse_lines import line_amounts

    vals = line_amounts("四、净 (亏损) / 利润 (48,703,934,402.33) 20,455,558,414.74")
    assert vals == [-48703934402.33, 20455558414.74], vals
    # 附注号不应被当成金额
    assert line_amounts("减：营业成本 四(49) (299,584,935) (276,409,404)") == [-299584935.0,
                                                                            -276409404.0]


@case
def test_parse_lines_avoids_substring_collision():
    """回归：真实年报上「负债合计」曾误命中「流动负债合计」，导致会计恒等式不成立。"""
    from diligence.parse_lines import parse_company

    pages = _pages([
        "合并资产负债表",
        "编制单位：X 单位：元",
        "流动资产合计 917,512,076,855.03 1,150,260,062,360.68",
        "资产总计 1,286,259,859,765.82 1,504,850,172,117.83",
        "流动负债合计 719,061,817,650.72 821,785,258,492.10",
        "负债合计 947,405,197,282.08 1,101,916,641,170.57",
        "股东权益合计 338,854,662,483.74 402,933,530,947.26",
    ])
    company, _ = parse_company(pages, "测试", "房地产")
    cur = company["periods"][1]["balance_sheet"]
    assert cur["总负债"] == 94740519.73, f"应取负债合计，实际 {cur['总负债']}"
    assert cur["流动负债合计"] == 71906181.77
    assert cur["净资产"] == 33885466.25, f"应取股东权益合计，实际 {cur['净资产']}"
    # 会计恒等式必须成立（这正是当初抓到该 bug 的判据）
    from diligence.validate import check_company
    assert check_company(company) == [], check_company(company)


@case
def test_parse_lines_normalizes_cost_sign():
    """回归：美的把成本写成括号负数，若不取绝对值毛利率会变成 173%。"""
    from diligence.parse_lines import parse_company
    from diligence.metrics import compute_metrics

    pages = _pages([
        "2024年度合并及公司利润表",
        "(除特别注明外，金额单位为人民币千元)",
        "一、营业总收入 409,084,266 373,710,000",
        "减：营业成本 四(49) (299,584,935) (276,409,404)",
        "净利润 38,757,214 33,720,000",
    ])
    company, _ = parse_company(pages, "测试", "制造业")
    inc = company["periods"][1]["income"]
    assert inc["营业成本"] == 29958493.5, f"成本应为正数，实际 {inc['营业成本']}"
    gm = compute_metrics(company)["2024"]["毛利率"]
    assert gm is not None and 0 < gm < 1, f"毛利率应在 (0,1)，实际 {gm}"


@case
def test_parse_lines_audit_opinion_not_fooled_by_key_audit_matters():
    """回归：扫全文会把「关键审计事项」里的措辞误判为非标意见（万科 2024 踩过）。"""
    from diligence.parse_lines import detect_audit_opinion

    pages = _pages([
        "审计报告\n一、审计意见\n我们认为，后附的财务报表在所有重大方面按照企业会计准则的"
        "规定编制，公允反映了公司的财务状况。\n二、形成审计意见的基础\n……",
        "三、关键审计事项\n我们关注到管理层对持续经营重大不确定性的评估，"
        "并针对存货减值执行了程序。",
    ])
    assert detect_audit_opinion(pages, 0, 1) == "标准无保留意见"
    pages2 = _pages(["一、审计意见\n我们认为，除「形成保留意见的基础」段所述事项的影响外，"
                     "财务报表在所有重大方面公允反映了……\n二、形成保留意见的基础"])
    assert detect_audit_opinion(pages2, 0, 0) == "保留意见"


# ── 抽取自校正智能体（纯标准库，零依赖）──
def _fake_client(payload):
    """构造一个只返回固定 JSON 的假模型客户端。"""
    from types import SimpleNamespace
    msg = SimpleNamespace(content=payload)
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: resp)))


def _dirty_company():
    """会计恒等式不成立的样本：总资产 ≠ 总负债 + 净资产。"""
    return {"company_name": "脏数据", "industry": "制造业",
            "periods": [{"year": 2024,
                         "balance_sheet": {"总资产": 500000, "总负债": 300000,
                                           "净资产": 100000},
                         "income": {"营业收入": 200000, "营业成本": 140000,
                                    "净利润": 30000},
                         "cashflow": {"经营活动现金流净额": 30000}}]}


@case
def test_agent_rule_decision_prefers_diagnostic_hint():
    """无模型时按告警类型选动作，且提示要指向具体成因（不是泛泛而谈）。"""
    from diligence.agent import rule_based_decision

    d = rule_based_decision([{"name": "会计恒等式不符", "detail": "x", "year": 2024}])
    assert d["action"] == "retry_with_hint", d
    assert "流动负债合计" in d["hint"], d
    d2 = rule_based_decision([{"name": "仅抽取到单期数据", "detail": "x", "year": 2024}])
    assert d2["action"] == "relocate", d2
    d3 = rule_based_decision([])
    assert d3["action"] == "accept"


@case
def test_agent_loop_clean_data_needs_no_retry():
    """数据干净时必须零重试——否则就是无意义的折腾。"""
    from diligence.agent import run_self_correcting_extract
    from diligence.validate import check_company

    calls = []

    def fake_extract(hint, rng):
        calls.append((hint, rng))
        return SAMPLES["healthy"]

    company, trace = run_self_correcting_extract(
        ["", "", ""], fake_extract, check_company, (0, 2), max_rounds=2)
    assert len(trace) == 1, trace
    assert trace[0]["action"] == "clean"
    assert company["_agent"]["self_corrected"] is False
    assert len(calls) == 1


@case
def test_agent_loop_retries_and_recovers():
    """第一轮脏数据触发补救，第二轮（带提示）恢复干净 → 轨迹须记录两轮与提示。"""
    from diligence.agent import run_self_correcting_extract
    from diligence.validate import check_company

    seen = []

    def fake_extract(hint, rng):
        seen.append(hint)
        return _dirty_company() if len(seen) == 1 else SAMPLES["healthy"]

    company, trace = run_self_correcting_extract(
        ["", "", ""], fake_extract, check_company, (0, 2), max_rounds=2)
    assert len(trace) == 2, trace
    # 该样本只有一期，故校验会同时报出「仅抽取到单期数据」，属正确行为
    assert "会计恒等式不符" in trace[0]["warnings"], trace[0]
    assert trace[0]["action"] == "retry_with_hint", trace[0]
    assert trace[1]["action"] == "clean", trace[1]
    assert seen[1], "第二轮必须把补救提示传给抽取（否则等于没补救）"
    assert company["_agent"]["self_corrected"] is True
    assert company["_agent"]["final_warnings"] == []


@case
def test_agent_loop_respects_max_rounds():
    """一直脏也不能无限重试：必须在轮数上限处停下并保留告警。"""
    from diligence.agent import run_self_correcting_extract
    from diligence.validate import check_company

    company, trace = run_self_correcting_extract(
        ["", "", ""], lambda hint, rng: _dirty_company(), check_company, (0, 2),
        max_rounds=2)
    assert len(trace) == 3, f"应为 1 次初抽 + 2 次补救，实际 {len(trace)}"
    assert trace[-1]["action"] == "stop", trace[-1]
    assert trace[-1]["warnings"], "停止时必须保留告警，不能假装通过"


@case
def test_agent_uses_llm_decision_and_falls_back_on_bad_action():
    """模型决定动作；返回非法动作时退回规则判据，不能中断流程。"""
    from diligence.agent import decide

    good = _fake_client('{"diagnosis":"单位读错","action":"retry_with_hint",'
                        '"hint":"注意金额单位为千元","reason":"单位疑似读错"}')
    d = decide([{"name": "会计恒等式不符", "detail": "x", "year": 2024}],
               "ctx", client=good, model="deepseek-chat")
    assert d["action"] == "retry_with_hint" and "千元" in d["hint"], d

    bad = _fake_client('{"diagnosis":"随便","action":"自己发明一个动作"}')
    d2 = decide([{"name": "会计恒等式不符", "detail": "x", "year": 2024}],
                "ctx", client=bad, model="deepseek-chat")
    assert d2["action"] == "retry_with_hint", d2
    assert "非法动作" in d2["reason"], d2


@case
def test_agent_relocate_widens_page_range():
    from diligence.agent import widen_range

    assert widen_range((100, 110), 300, step=6) == (94, 116)
    assert widen_range((0, 5), 300, step=6) == (0, 11)      # 下界不越界
    assert widen_range((290, 299), 300, step=6) == (284, 299)  # 上界不越界


@case
def test_report_shows_agent_trace_only_after_correction():
    """轨迹章节只在确实补救过时出现（一次通过不占章节号）。"""
    from diligence.agent import run_self_correcting_extract
    from diligence.validate import check_company

    dirty_then_clean = []
    def fake_extract(hint, rng):
        dirty_then_clean.append(1)
        return _dirty_company() if len(dirty_then_clean) == 1 else SAMPLES["healthy"]

    company, trace = run_self_correcting_extract(
        ["", "", ""], fake_extract, check_company, (0, 2), max_rounds=2)
    metrics = compute_metrics(company)
    hits = evaluate_rules(company, metrics)
    rep = build_report(company, metrics, hits, warnings=check_company(company))
    assert "抽取自校正轨迹" in rep, "补救过就必须在报告里留痕"
    rep2 = build_report(SAMPLES["healthy"], compute_metrics(SAMPLES["healthy"]),
                        evaluate_rules(SAMPLES["healthy"],
                                       compute_metrics(SAMPLES["healthy"])))
    assert "抽取自校正轨迹" not in rep2


@case
def test_scale_check_detects_unit_error():
    """回归：整体单位读错时所有比率不变、恒等式成立，只有跨路径对照能发现。

    实测来源：美的集团 2024 年报（表头单位千元），旧提示词抽出总资产
    6,043,519 万元，正确值 60,435,185 万元，相差 10 倍且校验零告警。
    """
    from diligence.validate import check_company, check_scale

    ref = {"periods": [{"year": 2024,
                        "balance_sheet": {"总资产": 60435185.0, "总负债": 37668446.0,
                                          "净资产": 22766739.0},
                        "income": {"营业收入": 40908427.0}}]}
    wrong = {"periods": [{"year": 2024,
                          "balance_sheet": {"总资产": 6043518.5, "总负债": 3766844.6,
                                            "净资产": 2276673.9},
                          "income": {"营业收入": 4090842.7}}]}
    # 前提：比率型/恒等式型校验对整体缩放完全无感（这正是不易察觉的原因）
    ratio_checks = {"会计恒等式不符", "资不抵债", "资产负债率为负",
                    "毛利率超过 100%", "净利率高于毛利率", "营收降幅失真"}
    fired = {w["name"] for w in check_company(wrong)} & ratio_checks
    assert not fired, f"整体缩放不该触发这些校验，却报了 {fired}"
    warns = check_scale(wrong, ref)
    assert warns and warns[0]["name"] == "单位换算疑似错误", warns
    assert "10 倍" in warns[0]["detail"], warns
    # 数值正确时不得告警
    assert check_scale(ref, ref) == []


@case
def test_scale_check_ignores_non_power_of_ten_gap():
    """只有接近 10 的整数次幂才判为单位问题，普通口径差异不得误报。"""
    from diligence.validate import check_scale

    ref = {"periods": [{"year": 2024, "balance_sheet": {"总资产": 100000.0},
                        "income": {"营业收入": 50000.0}}]}
    off = {"periods": [{"year": 2024, "balance_sheet": {"总资产": 150000.0},
                        "income": {"营业收入": 50000.0}}]}
    assert check_scale(off, ref) == [], "1.5 倍属普通口径差异，不该判为单位错误"
    assert check_scale(ref, None) == []


# ── 界面冒烟测试（用桩替换 streamlit，不依赖真实运行环境）──
def _load_app(click_run=False):
    """加载 app.py，用桩替换 streamlit。返回 (module, 调用记录, st桩)。

    控件类桩必须返回与真实控件**语义一致**的值：radio/selectbox 返回首个选项、
    button 返回布尔、file_uploader 返回 None。否则页面会被带到错误分支上
    （踩过：button 桩返回真值对象 → 误入「上传 PDF」分支 → 在 getvalue() 上炸）。
    """
    import importlib.util
    import sys
    import types

    calls = []

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __getattr__(self, name):
            def _f(*a, **k):
                calls.append(name)
            return _f

    st = types.ModuleType("streamlit")

    def _rec(name):
        """显示类桩：记录调用名并返回上下文管理器。"""
        def _f(*a, **k):
            calls.append(name)
            return _Ctx()
        return _f

    for fn in ("set_page_config", "title", "caption", "markdown", "write", "divider",
               "warning", "success", "info", "error", "dataframe", "download_button",
               "stop", "spinner", "expander", "subheader", "text"):
        setattr(st, fn, _rec(fn))
    st.radio = lambda label, options, **k: options[0] if options else None
    st.selectbox = lambda label, options, **k: options[0] if options else None
    st.checkbox = lambda *a, **k: False          # 不调模型，走纯规则路径
    st.toggle = lambda *a, **k: False            # 深浅色开关：默认浅色
    st.text_input = lambda *a, **k: ""           # API Key 输入框：默认留空
    st.button = lambda *a, **k: click_run
    st.file_uploader = lambda *a, **k: None
    st.rerun = lambda *a, **k: None
    st.columns = lambda n=1, **k: [_Ctx() for _ in range(n if isinstance(n, int) else len(n))]
    st.tabs = lambda names, **k: [_Ctx() for _ in names]
    st.session_state = {}
    st.sidebar = _Ctx()

    app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "app.py")
    saved = sys.modules.get("streamlit")
    sys.modules["streamlit"] = st
    try:
        spec = importlib.util.spec_from_file_location(f"app_under_test_{click_run}", app_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["streamlit"] = saved
        else:
            sys.modules.pop("streamlit", None)
    return mod, calls, st


@case
def test_app_renders_empty_and_result_states():
    """UI 冒烟：空状态与结果页两条路径都要能跑通。

    回归来源：把指标卡同比改成百分点时，循环变量 unit 换成 is_pct，
    但 f-string 里残留 {unit}，点击「运行尽调」即 NameError。
    语法检查（ast.parse）发现不了，只有真正执行渲染才行。
    """
    try:
        import pandas  # noqa: F401
    except ImportError:
        return "skip: 未安装 pandas"

    # ① 空状态（未点击运行）
    _, calls, st1 = _load_app(click_run=False)
    assert calls, "空状态也应产生渲染调用"
    assert "result" not in st1.session_state

    # ② 结果页（模拟点击「运行尽调」：样例数据 + 纯规则 → 完整渲染）
    _, calls2, st2 = _load_app(click_run=True)
    assert "result" in st2.session_state, "点击运行后应写入结果"
    assert st2.session_state["result"]["rules"], "样例应命中风险规则"
    assert calls2, "结果页应产生渲染调用"


@case
def test_delta_shows_percentage_points_and_sign_flip():
    """指标卡同比口径：百分比类用「个百分点」，跨零的比率直说方向转变。"""
    try:
        import pandas  # noqa: F401
    except ImportError:
        return "skip: 未安装 pandas"

    mod, _calls, _st = _load_app(click_run=False)
    # 66.7% → 76.0% 应显示 9.3 个百分点，而不是「涨了 14.0%」
    txt, cls = mod._delta(0.760, 0.667, higher_is_better=False, is_pct=True)
    assert "9.3 个百分点" in txt, txt
    assert cls == "up", cls                 # 负债率上升 = 变差 = 红
    # 净现比 0.27 → −0.60 跨零，不应给出百分比变化
    txt2, _ = mod._delta(-0.60, 0.27, higher_is_better=True)
    assert txt2 == "由正转负", txt2
    # 普通比率仍用相对变化
    txt3, _ = mod._delta(1.20, 1.00, higher_is_better=True)
    assert "20.0%" in txt3, txt3


# ── A 股年报获取（纯标准库，零依赖）──
@case
def test_areport_code_normalization():
    """股票代码规范化：接受常见写法，拒绝非法输入。"""
    from diligence.areport import ReportSourceError, normalize_code

    assert normalize_code("000002") == "000002"
    assert normalize_code("sz000002") == "000002"
    assert normalize_code("000002.SZ") == "000002"
    assert normalize_code("  600519  ") == "600519"
    assert normalize_code("SH600519") == "600519"
    for bad in ("abc", "12", "", None, "12345678"):
        try:
            normalize_code(bad)
            raise AssertionError(f"{bad!r} 应被拒绝")
        except ReportSourceError:
            pass


@case
def test_areport_annual_title_filter():
    """年报标题识别：必须排除半年报/季报/摘要/英文版/更正公告。

    回归来源：初版用「'年度报告' in title」判断，
    结果「2026年半年度报告」也被当成年度报告（前者是后者的子串）。
    """
    from diligence.areport import is_annual_report, year_of

    assert is_annual_report("万科A:2025年年度报告")
    assert year_of("万科A:2025年年度报告") == 2025
    for bad in ("万科A:2026年半年度报告", "XX:2024年年度报告摘要",
                "XX:2025年第三季度报告", "XX:2024年年度报告（英文版）",
                "XX:关于2024年年度报告的更正公告", "XX:2024年年度报告已取消",
                "XX:2024年年度报告补充公告", ""):
        assert not is_annual_report(bad), f"{bad!r} 不该被当成年度报告"


@case
def test_areport_market_and_filename():
    from diligence.areport import market_of, safe_filename

    assert market_of("000002") == "深市"
    assert market_of("600519") == "沪市"
    assert market_of("300750") == "深市"
    assert market_of("830799") == "北交所"
    # 文件名不能含路径分隔符等非法字符
    fn = safe_filename("000002 万科A:2025年年度报告")
    assert "/" not in fn and "\\" not in fn and ":" not in fn
    assert fn.endswith(".pdf")


@case
def test_areport_picks_latest_and_reports_missing():
    """取数逻辑：在多次公告中选出最新年报；找不到时给出可读错误。"""
    from diligence import areport

    fake = {"data": {"list": [
        {"title": "XX:2026年半年度报告", "notice_date": "2026-08-28 00:00:00",
         "art_code": "A3"},
        {"title": "XX:2025年年度报告", "notice_date": "2026-04-01 00:00:00",
         "art_code": "A2"},
        {"title": "XX:2025年第三季度报告", "notice_date": "2025-10-30 00:00:00",
         "art_code": "A4"},
    ]}}
    saved = areport._get_json
    try:
        areport._get_json = lambda url, timeout=20: fake
        reps = areport.list_annual_reports("000002")
        assert len(reps) == 1, reps
        assert reps[0]["year"] == 2025 and reps[0]["art_code"] == "A2", reps
        # 没有年报时应抛出可读错误（供界面降级提示）
        fake["data"]["list"] = [{"title": "XX:2026年半年度报告", "art_code": "A3"}]
        try:
            areport.list_annual_reports("000002")
            raise AssertionError("应抛 ReportSourceError")
        except areport.ReportSourceError as e:
            assert "年度报告" in str(e)
    finally:
        areport._get_json = saved


@case
def test_report_shows_announcement_origin():
    """按代码取年报时，报告须标出公告出处（可追溯性原则）。"""
    from diligence.report import build_report

    company = dict(SAMPLES["risky"])
    company["_source"] = {
        "file": "000002_万科A_2025年年度报告.pdf", "pages_total": 300,
        "pages_used": [141, 162], "chars": 18400, "model": "deepseek-chat",
        "origin": "000002 万科A:2025年年度报告（2026-04-01 公告，东方财富公告接口）",
    }
    metrics = compute_metrics(company)
    hits = evaluate_rules(company, metrics)
    rep = build_report(company, metrics, hits)
    assert "公告出处" in rep, "按代码取数时必须标注公告出处"
    assert "2026-04-01" in rep and "东方财富" in rep
    # 手工上传 / 样例路径不应出现该行
    rep2 = build_report(SAMPLES["risky"], compute_metrics(SAMPLES["risky"]),
                        evaluate_rules(SAMPLES["risky"],
                                       compute_metrics(SAMPLES["risky"])))
    assert "公告出处" not in rep2


def main():
    passed = failed = 0
    for fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"ok    {fn.__name__}")
    print(f"\n{passed} passed, {failed} failed, {len(CASES)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
