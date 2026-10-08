"""文档解析层：从财报 PDF 提取三大报表，结构化为统一 Schema。

流程：定位报表页 -> pdfplumber 提取文本 -> DeepSeek 抽取 JSON -> 代码归一化（含派生科目计算）。
"""
import json
import os

import pdfplumber

from . import config
from .llm import get_client
from .locate import diagnose as _diagnose
from .locate import format_diagnosis as _format_diagnosis
from .locate import locate_statement_pages as _locate_statement_pages
from .locate import page_texts as _page_texts

# 需要 LLM 从文本中抽取的原始科目（派生科目由代码计算）
_BALANCE_SHEET = [
    "货币资金", "应收账款", "存货", "流动资产合计", "商誉", "总资产",
    "短期借款", "应付账款", "流动负债合计", "长期借款",
    "一年内到期的非流动负债", "应付债券", "总负债", "净资产",
]
_INCOME = [
    "营业收入", "营业成本", "销售费用", "管理费用", "财务费用",
    "净利润", "归母净利润",
]
_CASHFLOW = [
    "经营活动现金流净额", "投资活动现金流净额", "筹资活动现金流净额",
]

SCHEMA = {
    "balance_sheet": _BALANCE_SHEET,
    "income": _INCOME,
    "cashflow": _CASHFLOW,
}

_EXTRACT_SYSTEM = (
    "你是上市公司财报结构化抽取引擎。请从给定的财报文本中，抽取三大报表的"
    "关键科目金额，输出严格符合要求的 JSON。要求：\n"
    "1. 金额统一换算为「万元」（原文为元，除以 10000，保留 2 位小数）。\n"
    "2. 只输出 JSON，不要输出任何解释文字。找不到的科目填 null，不要编造。\n"
    "3. 只取【合并】报表数据，忽略「母公司资产负债表/利润表/现金流量表」。\n"
    "4. 科目名称映射：总资产=资产总计；总负债=负债合计；"
    "净资产=所有者权益（或股东权益）合计；营业收入=营业总收入；"
    "归母净利润=归属于母公司股东的净利润（也写作「归属于母公司所有者的净利润」）。\n"
    "5. 提取两个报告期（本期与上期），年份字段用整数。\n"
    "6. 【单位识别·极重要】报表表头会声明金额单位，必须先识别再换算为万元："
    "「单位：元」除以 10000；「金额单位为人民币千元」除以 10；"
    "「金额单位均为人民币百万元」乘以 100；已是「万元」则不变。"
    "真实年报三种单位都常见（万科用元、美的用千元、工商银行用百万元），"
    "算错单位会造成 10 倍或 100 倍的错误且不易察觉，务必逐份确认。\n"
    "7. 【列选择·极重要】银行、保险与部分制造业会把合并与母公司报表合并成一张"
    "「合并及公司资产负债表/利润表/现金流量表」，此时每行有四个金额列，"
    "顺序为「合并本期、合并上期、公司本期、公司上期」。"
    "本作品的 Schema 只要【合并】数据，请取每行的【前两个】金额，"
    "不要取后面属于「公司（母公司）」的两列；该两列常以 - 占位。\n"
    "8. 【负数识别】金额被圆括号包裹表示负数，例如 (48,703,934,402.33) 等于 "
    "-48703934.40 万元（按元计）；不要因为括号而漏读符号，也不要把亏损记成正数。\n"
    "9. 【行名变体】亏损公司的报表会把行名写成插入式表述，例如"
    "「四、净 (亏损) / 利润」「二、营业 (亏损) / 利润」「归属于母公司股东的净 (亏损) / 利润」"
    "「三、(亏损) / 利润总额」，分别对应「净利润」「营业利润」「归母净利润」「利润总额」；"
    "报表标题也可能带年份前缀，如「2024年度合并及公司利润表」，请按语义匹配，"
    "不要因为字面不完全一致就填 null。同理，「一、营业总收入」对应「营业收入」，"
    "「减：营业成本」对应「营业成本」。\n"
    "10. 从「审计报告」的「一、审计意见」段落提取审计意见类型，填入每个报告期的 audit_opinion 字段。"
    "判断依据仅限「一、审计意见」的结论性表述：若表述为「在所有重大方面…公允反映…」（无保留意见），"
    "则为「标准无保留意见」；只有当审计报告明确出现「保留意见」「无法表示意见」「否定意见」"
    "「带强调事项段」「带持续经营重大不确定性段落」等字样时才使用对应类型。"
    "注意：「关键审计事项」中讨论的持续经营、减值等事项不是审计意见类型；"
    "「管理层/注册会计师的责任」中关于持续经营假设的论述也不是意见类型。"
    "若文本中未出现审计意见，填 null。"
)


def _find_page(pdf, keyword):
    """返回第一个包含关键词的页面下标，找不到返回 None（保留给简单场景）。"""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if keyword in text:
            return i
    return None


def extract_text_from_pdf(pdf_path, page_range=None):
    """提取 PDF 文本；page_range 为 (start, end) 时仅提取该区间。"""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        if page_range is None:
            pages = pdf.pages
        else:
            start, end = page_range
            pages = pdf.pages[start:end + 1]
        for page in pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _build_prompt(text):
    fields = json.dumps(SCHEMA, ensure_ascii=False, indent=2)
    return (
        "需要抽取的科目字段如下：\n"
        f"{fields}\n\n"
        "请从以下财报文本中抽取上述字段，输出 JSON，结构为：\n"
        '{"company_name": "...", "industry": "...", "periods": ['
        '{"year": 整数, "balance_sheet": {...}, "income": {...}, '
        '"cashflow": {...}, "audit_opinion": "标准无保留意见/保留意见/..."}, ...]}\n\n'
        f"财报文本：\n{text}"
    )


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# 归一化（派生科目计算）与规则抽取兜底共用，见 normalize.py
from .normalize import normalize_company as _normalize  # noqa: E402


def diagnose_pdf(pdf_path):
    """只做页面定位并返回诊断（不调用模型、不需要 API Key）。"""
    with pdfplumber.open(pdf_path) as pdf:
        texts = _page_texts(pdf)
        diag = _diagnose(texts)
    diag["file"] = os.path.basename(pdf_path)
    return diag


def friendly_reason(exc):
    """把模型调用异常翻译成用户看得懂、且能据以行动的一句话。"""
    name = type(exc).__name__
    text = str(exc)
    if "AuthenticationError" in name or "401" in text:
        return "API Key 无效或已过期"
    if "RateLimit" in name or "429" in text:
        return "调用频率或额度超限"
    if "APIConnection" in name or "Timeout" in name or "Connection" in name:
        return "网络无法访问模型服务"
    if "Insufficient" in text or "402" in text:
        return "账户余额不足"
    if "未配置" in text:
        return "未配置 API Key"
    return f"模型调用失败（{name}）"


def extract_by_rules(pdf_path, company_name=None, industry="制造业", origin=None):
    """纯规则抽取，不调用任何模型。

    用于三种情况：没有 API Key、Key 失效、网络不可达。
    代价是行业只能"假设"：规则抽取无法像模型那样从年报正文读出所属行业，
    因此按传入的 industry 套用阈值，并在数据校验里留下一条显式告警。
    """
    from .parse_lines import parse_company

    with pdfplumber.open(pdf_path) as pdf:
        texts = _page_texts(pdf)

    name = company_name or os.path.splitext(os.path.basename(pdf_path))[0]
    company, rep = parse_company(texts, name, industry)

    src = dict(company.get("_source") or {})
    src.update({"file": os.path.basename(pdf_path), "pages_total": len(texts),
                "model": "规则抽取（未使用大模型）", "rounds": 1})
    if origin:
        src["origin"] = origin
    company["_source"] = src

    # 让报告显式说明"行业基准是假设值"，避免读者把阈值当成事实
    warns = list(company.get("_warnings") or [])
    warns.append({
        "year": None, "name": "行业基准为假设值",
        "detail": f"本次未使用大模型，无法从年报正文识别所属行业，规则阈值按"
                  f"「{industry}」套用；若行业不符，请在界面选择正确行业后重跑",
    })
    company["_warnings"] = warns
    return company, rep


def extract_with_fallback(pdf_path, origin=None, company_name=None,
                          industry="制造业", self_correct=True, max_rounds=2):
    """优先大模型抽取；模型不可用时**自动降级为规则抽取**，保证仍能出报告。

    返回 (company, notice)：notice 为 None 表示走的是大模型路径；否则是可读的
    降级原因，供界面提示用户（并指引其更新 Key 或改选行业）。
    """
    try:
        return extract_from_pdf(pdf_path, self_correct=self_correct,
                                max_rounds=max_rounds, origin=origin), None
    except Exception as e:  # noqa: BLE001
        reason = friendly_reason(e)
        company, _rep = extract_by_rules(pdf_path, company_name=company_name,
                                        industry=industry, origin=origin)
        # 标记模型不可用：下游（如风险研判）据此跳过调用，省掉一次注定失败的往返
        company["_llm_unavailable"] = reason
        return company, reason


def _extract_once(client, texts, hint, page_range):
    """单轮抽取：按页区间取文 → 组装提示词（可带补救提示）→ 调模型 → 归一化。"""
    start, end = page_range
    text = "\n".join(t for t in texts[start:end + 1] if t)
    system = _EXTRACT_SYSTEM
    if hint:
        system += "\n\n【本轮特别注意】" + hint
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _build_prompt(text)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return _normalize(json.loads(resp.choices[0].message.content))


def extract_from_pdf(pdf_path, self_correct=True, max_rounds=2, origin=None):
    """PDF -> 结构化公司数据。需配置 DEEPSEEK_API_KEY。

    self_correct=True（默认）时启用抽取自校正闭环：每轮抽完先做数据自洽性校验，
    若有告警则由模型诊断成因并选择补救动作（补充提示 / 调整页区间 / 接受），
    最多补救 max_rounds 轮。轨迹记录在 company["_trace"]。

    origin：数据出处说明（如「000002 万科A:2025年年度报告（2026-04-01 公告，
    东方财富公告接口）」）。由股票代码自动获取年报时填入，会出现在报告的数据来源区。
    """
    client = get_client()
    if client is None:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用模型抽取财报。")

    with pdfplumber.open(pdf_path) as pdf:
        texts = _page_texts(pdf)                     # 单次遍历，定位与取文共用
        page_range = _locate_statement_pages(pdf, texts)

    from .agent import run_self_correcting_extract
    from .parse_lines import parse_company as _rule_parse
    from .validate import check_company, check_scale

    # 独立参照：规则抽取按报表表头确定性识别单位，用于发现整体倍率错误。
    # 这类错误所有比率不变，只有跨路径对照能发现（实测美的年报差 10 倍且校验零告警）。
    reference = None
    if self_correct:
        try:
            reference, _ = _rule_parse(texts, company_name="（规则参照）",
                                       industry="")
        except Exception:  # noqa: BLE001
            reference = None

    def _validate(comp):
        warns = check_company(comp)
        if reference:
            warns = warns + check_scale(comp, reference)
        return warns

    rounds = max_rounds if self_correct else 0
    company, trace = run_self_correcting_extract(
        texts,
        extract_fn=lambda hint, rng: _extract_once(client, texts, hint, rng),
        validate_fn=_validate if self_correct else check_company,
        page_range=page_range,
        max_rounds=rounds,
        client=client if self_correct else None,
        model=config.DEEPSEEK_MODEL if self_correct else None,
        context_extra=f"；文件 {os.path.basename(pdf_path)}",
    )

    final = trace[-1]
    s, e = final["page_range"][0] - 1, final["page_range"][1]
    company["_source"] = {
        "file": os.path.basename(pdf_path),
        "pages_total": len(texts),
        "pages_used": final["page_range"],
        "chars": sum(len(texts[i]) for i in range(s, e)),
        "model": config.DEEPSEEK_MODEL,
        "rounds": final["round"],
    }
    if origin:
        company["_source"]["origin"] = origin
    return company
