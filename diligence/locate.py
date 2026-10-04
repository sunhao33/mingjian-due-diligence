"""报表页面定位 —— 纯标准库实现，不依赖 pdfplumber（便于零依赖测试）。

定位思路：不再「取第一个含关键词的页」，而是给每一页打「像不像一张报表」的分。
真实年报里，报表名会大量出现在目录、审计报告正文、附注交叉引用中，
按首次命中会定位到错误页面；反过来，真正的报表页有两个稳定特征：
  1）报表名独立成行（页首标题，可能带「合并/合并及公司/本行/母公司」前缀与「（续）」后缀）；
  2）金额极其密集（一页几十个带千分位的数字）。
目录页（满是引导点）与审计报告正文（只是「提到」报表名）则要扣分。
"""

import re

# 报表标题：允许各类前缀与「（续）」后缀
_TITLE_RE = re.compile(
    r"^(?:合并及?(?:银行|公司)?|本行|母公司)?\s*"
    r"(?:资产负债表|利润表|现金流量表|股东权益变动表)\s*(?:（续）|\(续\))?$"
)
_AMOUNT_RE = re.compile(r"\d[\d,]{4,}")          # 5 位以上数字（含千分位）
_TOC_MARKERS = ("....", "……", "………")
_TITLE_BONUS = 100
_TOC_PENALTY = -80
_AUDIT_PENALTY = -60


def page_texts(pdf):
    """一次遍历取回全部页面文本，避免重复解析（400 页年报可省数分钟）。"""
    return [(page.extract_text() or "") for page in pdf.pages]


def statement_score(text, keys):
    """给单页打分：命中标题独立成行 + 金额密集才算高置信报表页。"""
    if not any(k in text for k in keys):
        return 0
    score = 0
    head = [ln.strip() for ln in text.splitlines() if ln.strip()][:6]
    for ln in head:
        if _TITLE_RE.match(ln) and any(k in ln for k in keys):
            score += _TITLE_BONUS
            break
    score += len(_AMOUNT_RE.findall(text))
    if any(m in text for m in _TOC_MARKERS):
        score += _TOC_PENALTY                      # 目录页
    if text.lstrip().startswith("审计报告") or "一、审计意见" in text[:200]:
        score += _AUDIT_PENALTY                    # 审计报告正文只是「提到」报表名
    return score


def find_statement_page(texts, keys):
    """在所有页里挑最像该报表的一页；没有像样的候选则返回 None。"""
    best, best_score = None, 0
    for i, text in enumerate(texts):
        s = statement_score(text, keys)
        if s > best_score:
            best, best_score = i, s
    return best


def find_audit_page(texts):
    """审计意见结论所在页。"""
    for i, text in enumerate(texts):
        if "一、审计意见" in text or ("审计意见" in text and "我们认为" in text):
            return i
    return None


def locate_statement_pages(pdf=None, texts=None):
    """定位三大报表（含审计意见页）所在区间，返回 (start, end) 下标（含）。

    关键保证：**任何情况下都满足 start <= end**。
    早期版本对工商银行年报会返回 (195, 44) 这样的反向区间，
    切片为空 → 抽取到空文本且不报错，属最危险的一类静默失败。
    """
    if texts is None:
        if pdf is None:
            return 0, 0
        texts = page_texts(pdf)
    n = len(texts)
    if n == 0:
        return 0, 0

    bs = find_statement_page(texts, ("资产负债表",))
    inc = find_statement_page(texts, ("利润表",))
    cf = find_statement_page(texts, ("现金流量表",))
    found = [p for p in (bs, inc, cf) if p is not None]
    if not found:
        return 0, n - 1                            # 一份都没认出来：退回全文，不丢数据

    start = max(0, min(found) - 2)
    end = min(n - 1, max(found) + 4)               # 报表通常跨 2–3 页
    audit = find_audit_page(texts)
    if audit is not None and audit < start:
        start = max(0, audit - 1)                  # 向前纳入审计意见结论
    if end < start:                                # 兜底：绝不返回反向区间
        end = min(n - 1, start + 8)
    return start, end


# 三类报表的判定关键词（与 locate_statement_pages 内部保持一致）
STATEMENT_KEYS = (
    ("资产负债表", ("资产负债表",)),
    ("利润表", ("利润表",)),
    ("现金流量表", ("现金流量表",)),
)


def diagnose(texts):
    """定位诊断：说明「数据是从哪几页来的」，用于追溯与排障。

    返回 {"pages", "range", "statements": {名称: {"chosen", "top"}}, "audit_page"}，
    其中页码均为 1 起的用户可见页码。
    """
    detail = {}
    for name, keys in STATEMENT_KEYS:
        scored = sorted(((statement_score(t, keys), i + 1) for i, t in enumerate(texts)),
                        key=lambda x: (-x[0], x[1]))[:3]
        detail[name] = {
            "chosen": next((p for s, p in scored if s > 0), None),
            "top": [{"page": p, "score": s} for s, p in scored],
        }
    start, end = locate_statement_pages(texts=texts)
    audit = find_audit_page(texts)
    return {
        "pages": len(texts),
        "range": [start + 1, end + 1],
        "statements": detail,
        "audit_page": (audit + 1) if audit is not None else None,
    }


def format_diagnosis(diag):
    """把诊断结果转成可读多行文本。"""
    lines = [f"PDF 共 {diag['pages']} 页，自动定位第 {diag['range'][0]}–{diag['range'][1]} 页"
             f"（{diag['range'][1] - diag['range'][0] + 1} 页）"]
    for name, info in diag["statements"].items():
        if info["chosen"]:
            top = "、".join(f"P{c['page']}({c['score']})" for c in info["top"])
            lines.append(f"  {name}：选中 P{info['chosen']}；候选得分 {top}")
        else:
            lines.append(f"  {name}：未找到（该报表可能为图片版，需 OCR）")
    if diag["audit_page"]:
        lines.append(f"  审计意见页：P{diag['audit_page']}")
    return lines
