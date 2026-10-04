"""结构化数据的归一化（纯标准库）。

从 extract.py 抽出，供「大模型抽取」与「规则抽取兜底」共用。
"""


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_company(company):
    """补全字段并计算派生科目「有息负债」（不信任任何来源的算术）。"""
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
        p.setdefault("income", {})
        p.setdefault("cashflow", {})
        p.setdefault("audit_opinion", "标准无保留意见")
    return company
