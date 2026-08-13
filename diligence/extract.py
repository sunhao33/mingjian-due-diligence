"""文档解析层：从财报 PDF 提取三大报表，结构化为统一 Schema。

流程：定位报表页 -> pdfplumber 提取文本 -> DeepSeek 抽取 JSON -> 代码归一化（含派生科目计算）。
"""
import json

import pdfplumber

from . import config
from .llm import get_client

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
    "归母净利润=归属于母公司所有者的净利润。\n"
    "5. 提取两个报告期（本期与上期），年份字段用整数。\n"
    "6. 从「审计报告」的「一、审计意见」段落提取审计意见类型，填入每个报告期的 audit_opinion 字段。"
    "判断依据仅限「一、审计意见」的结论性表述：若表述为「在所有重大方面…公允反映…」（无保留意见），"
    "则为「标准无保留意见」；只有当审计报告明确出现「保留意见」「无法表示意见」「否定意见」"
    "「带强调事项段」「带持续经营重大不确定性段落」等字样时才使用对应类型。"
    "注意：「关键审计事项」中讨论的持续经营、减值等事项不是审计意见类型；"
    "「管理层/注册会计师的责任」中关于持续经营假设的论述也不是意见类型。"
    "若文本中未出现审计意见，填 null。"
)


def _find_page(pdf, keyword):
    """返回第一个包含关键词的页面下标，找不到返回 None。"""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if keyword in text:
            return i
    return None


def _find_audit_page(pdf):
    """返回审计报告「一、审计意见」结论所在页下标，找不到返回 None。"""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "一、审计意见" in text or ("审计意见" in text and "我们认为" in text):
            return i
    return None


def _locate_statement_pages(pdf):
    """定位合并三大报表及审计报告所在页面区间，返回 (start, end) 下标（含）。"""
    # 优先精确匹配「合并」报表，避免误命中目录或「母公司资产负债表」
    bs = _find_page(pdf, "合并资产负债表") or _find_page(pdf, "资产负债表")
    cf = _find_page(pdf, "合并现金流量表") or _find_page(pdf, "现金流量表")
    if bs is None:
        return 0, len(pdf.pages) - 1  # 兜底：全文
    if cf is None:
        cf = min(bs + 6, len(pdf.pages) - 1)
    # 现金流量表通常跨 2-3 页，向后多取几页
    end = min(cf + 3, len(pdf.pages) - 1)
    # 向前覆盖审计报告结论（含「一、审计意见」），审计报告在财务报表之前
    audit = _find_audit_page(pdf)
    if audit is not None and audit < bs:
        start = max(0, audit - 1)
    else:
        start = max(0, bs - 3)
    return start, end


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


def _normalize(company):
    """补全字段，并在代码中计算派生科目「有息负债」（不信任 LLM 的算术）。"""
    for p in company.get("periods", []):
        bs = p.get("balance_sheet") or {}

        short = _num(bs.get("短期借款")) or 0
        long_ = _num(bs.get("长期借款")) or 0
        non_current = _num(bs.get("一年内到期的非流动负债")) or 0
        bonds = _num(bs.get("应付债券")) or 0
        interest_bearing = short + long_ + non_current + bonds
        bs["有息负债"] = interest_bearing if interest_bearing else None

        bs.setdefault("净资产", None)
        p["balance_sheet"] = bs
        p.setdefault("audit_opinion", "标准无保留意见")
    return company


def extract_from_pdf(pdf_path):
    """PDF -> 结构化公司数据。需配置 DEEPSEEK_API_KEY。"""
    client = get_client()
    if client is None:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用模型抽取财报。")

    with pdfplumber.open(pdf_path) as pdf:
        page_range = _locate_statement_pages(pdf)

    text = extract_text_from_pdf(pdf_path, page_range=page_range)

    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": _build_prompt(text)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return _normalize(data)
