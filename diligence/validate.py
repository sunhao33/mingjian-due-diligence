"""数据自洽性校验 —— 用会计恒等式与取值区间给抽取结果做体检。

定位：大模型抽取可能出错（漏读括号导致亏损变盈利、串行错位、单位换算错误）。
这些错误不会让程序崩溃，却会让结论反向。本模块用**纯算术**规则把它们变成显式告警：
- 会计恒等式：总资产 = 总负债 + 净资产
- 取值区间：资产负债率 ∈ [0, 1]、毛利率 ≤ 100%、增长率 ≥ -100%
- 结构关系：净利率不应高于毛利率（否则可能是净利润符号读反）
- 跨路径倍率：与独立规则抽取对照，发现**整体单位换算错误**

设计原则与 metrics.py 一致：缺数据不猜，只对确实能判定的矛盾告警。
"""

import math


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _pct(v):
    return f"{v:.1%}"


def _power_of_ten(ratio, tol=0.01):
    """若 ratio 接近 10 的整数次幂（非 0 次），返回该次幂，否则 None。"""
    if ratio is None or ratio <= 0:
        return None
    k = round(math.log10(ratio))
    if k == 0:
        return None
    if abs(ratio / (10 ** k) - 1) <= tol:
        return k
    return None


# 跨路径倍率对照使用的字段（数值大、受单位影响最明显）
_SCALE_FIELDS = (("balance_sheet", "总资产"), ("income", "营业收入"),
                 ("balance_sheet", "总负债"))


def check_scale(company, reference):
    """与独立路径（规则抽取）对照，发现**整体单位换算错误**。

    为什么必须单独有这一条：
        若把「千元」当成「元」换算，所有金额同比例缩放，
        于是**全部比率不变、会计恒等式也成立**——区间型与恒等式型校验一律失效。
        实测中美的集团 2024 年报就出现过 10 倍偏差且校验零告警，
        唯一能发现它的手段是与「按表头确定性识别单位」的规则抽取对照。
    """
    warns = []
    if not reference:
        return warns
    cur = {str(p.get("year")): p for p in company.get("periods", [])}
    ref = {str(p.get("year")): p for p in reference.get("periods", [])}
    years = sorted(set(cur) & set(ref), reverse=True)
    if not years:
        return warns
    year = years[0]
    for group, field in _SCALE_FIELDS:
        a = (cur[year].get(group) or {}).get(field)
        b = (ref[year].get(group) or {}).get(field)
        if not a or not b or a <= 0 or b <= 0:
            continue
        k = _power_of_ten(a / b)
        if k is not None:
            factor = 10 ** abs(k)
            warns.append({
                "year": int(year), "name": "单位换算疑似错误",
                "detail": f"{field} 与独立规则抽取相差约 {factor:.0f} 倍"
                          f"（{a:,.0f} vs {b:,.0f} 万元）。此类错误所有比率不变、"
                          f"会计恒等式也成立，属静默错误，须按报表表头声明的单位重新换算",
            })
            break                      # 一处数量级不符即可判定
    return warns


def check_company(company):
    """返回告警列表 [{"year": int, "name": str, "detail": str}, ...]，无问题时为空列表。

    开头并入 company["_warnings"] —— 抽取环节自产的告警（例如降级为规则抽取后
    「行业基准为假设值」），保证它们同样出现在报告的数据校验章节里。
    """
    warns = list(company.get("_warnings") or [])
    periods = sorted(company.get("periods", []), key=lambda p: p.get("year") or 0)

    prev_inc = None
    for p in periods:
        year = p.get("year")
        bs = p.get("balance_sheet") or {}
        inc = p.get("income") or {}

        ta = _num(bs.get("总资产"))
        tl = _num(bs.get("总负债"))
        eq = _num(bs.get("净资产"))

        # 1. 会计恒等式
        if ta and ta > 0 and tl is not None and eq is not None:
            gap = abs(ta - (tl + eq)) / abs(ta)
            if gap > 0.01:
                warns.append({
                    "year": year, "name": "会计恒等式不符",
                    "detail": f"总资产 {ta:,.0f} 万元 ≠ 总负债 + 净资产 {tl + eq:,.0f} 万元"
                              f"（偏差 {_pct(gap)}），疑似科目串行或单位错误",
                })

        # 2. 资产负债率区间
        if ta and ta > 0 and tl is not None:
            ratio = tl / ta
            if ratio > 1.0:
                warns.append({
                    "year": year, "name": "资不抵债",
                    "detail": f"资产负债率 {_pct(ratio)} 超过 100%，净资产为负，"
                              f"偿债与持续经营风险需单独核实",
                })
            elif ratio < 0:
                warns.append({
                    "year": year, "name": "资产负债率为负",
                    "detail": f"资产负债率 {_pct(ratio)} 不合常理，请核对总负债/总资产是否读反",
                })

        # 3. 毛利率上限
        rev = _num(inc.get("营业收入"))
        cost = _num(inc.get("营业成本"))
        gross_margin = None
        if rev and rev > 0 and cost is not None:
            gross_margin = (rev - cost) / rev
            if gross_margin > 1.0:
                warns.append({
                    "year": year, "name": "毛利率超过 100%",
                    "detail": f"毛利率 {_pct(gross_margin)}，通常意味着营业成本被漏读或读成负数",
                })

        # 4. 净利率不应高于毛利率（净利润符号读反时的典型征兆）
        np_ = _num(inc.get("净利润"))
        if rev and rev > 0 and np_ is not None and gross_margin is not None:
            net_margin = np_ / rev
            if net_margin > gross_margin + 0.01:
                warns.append({
                    "year": year, "name": "净利率高于毛利率",
                    "detail": f"净利率 {_pct(net_margin)} > 毛利率 {_pct(gross_margin)}，"
                              f"请核对净利润符号是否读反（报表中括号表示负数）"
                              f"或是否存在大额非经常性损益",
                })

        # 5. 营收同比降幅不可能超过 100%（营收恒为非负）
        #    注意：净利润不适用该规则——由盈利转亏损时降幅天然小于 -100%
        #    （万科 2024：+20.5 亿 → -48.7 亿，降幅 -338%，属正常经营结果）
        if prev_inc is not None:
            cur_v, prev_v = _num(inc.get("营业收入")), _num(prev_inc.get("营业收入"))
            if cur_v is not None and prev_v not in (None, 0) and prev_v > 0:
                if (cur_v - prev_v) / prev_v < -1.0:
                    warns.append({
                        "year": year, "name": "营收降幅失真",
                        "detail": f"营业收入由 {prev_v:,.0f} 变为 {cur_v:,.0f} 万元，"
                                  f"同比降幅超过 100%，两期数据口径可能不一致",
                    })
        prev_inc = inc

    # 6. 报告期数量
    if len(periods) < 2:
        warns.append({
            "year": periods[-1].get("year") if periods else None,
            "name": "仅抽取到单期数据",
            "detail": "同比类规则（毛利率下滑、营收/净利润增长、经营现金流恶化）将无法判定",
        })

    return warns


def format_warnings(warns):
    """转成报告用的一行行文本。"""
    return [f"第 {w['year']} 期：**{w['name']}** —— {w['detail']}" if w.get("year")
            else f"**{w['name']}** —— {w['detail']}" for w in warns]
