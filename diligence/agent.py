"""抽取自校正智能体 —— 让模型「发现抽取出错并自己决定怎么补救」。

为什么这算智能体（而不是脚本）：
    校验告警是**外部信号**，不是我预设的流程分支。模型必须根据「具体是哪一类告警」
    决定「用哪一种补救动作」——不同告警对应不同动作，这个映射不是写死的。

闭环：
    抽取 → 数据自洽性校验 → 有告警？
        → 模型诊断成因并选择动作（retry_with_hint / relocate / accept）
        → 代码执行该动作（确定性） → 再抽取 → 再校验
    → 无告警或达到轮数上限 → 停

边界（刻意不给模型自主权）：
    - 数字全部来自报表文本与确定性代码，模型不产生任何数值；
    - 动作集合是固定的三种，模型只能「选」，不能自创；
    - 轮数上限由代码控制，模型不能延长。

降级：没有 API Key 时 `decide()` 走规则判据（按告警类型选动作），闭环照常工作。
"""

import json

ACTIONS = ("retry_with_hint", "relocate", "accept")

# 告警名 -> 规则降级时的默认动作（无 API Key 时使用）
_RULE_ACTIONS = {
    "会计恒等式不符": ("retry_with_hint",
                  "总资产应等于总负债加净资产。请核对是否把「流动负债合计」误当成「负债合计」、"
                  "把「归属于母公司股东权益」误当成「股东权益合计」，以及金额单位是否读错。"),
    "资不抵债": ("retry_with_hint",
             "请核对总负债与总资产是否读反、金额单位是否为百万元或千元。"),
    "资产负债率为负": ("retry_with_hint", "请核对总负债与总资产是否读反。"),
    "毛利率超过 100%": ("retry_with_hint",
                  "毛利率超过 100% 通常意味着营业成本漏读或被读成负数，"
                  "请确认营业成本为正数（报表中以括号列报的，取绝对值）。"),
    "净利率高于毛利率": ("retry_with_hint",
                  "净利率高于毛利率通常意味着净利润符号读反（报表中括号表示负数），请核对符号。"),
    "营收降幅失真": ("relocate", "营收同比降幅超过 100% 不合常理，可能是页区间取错，需重新定位。"),
    "仅抽取到单期数据": ("relocate",
                  "只抽到一期数据，说明定位到的页区间可能不是完整的两期报表，需扩大页区间。"),
    "单位换算疑似错误": ("retry_with_hint",
                  "上一轮金额与独立解析相差数量级，属整体单位换算错误：报表表头声明的金额单位"
                  "并非元，请严格按表头换算——「元」÷10000、「千元」÷10、"
                  "「百万元」×100，已是万元则不变。"),
}


def rule_based_decision(warnings):
    """降级判据：按告警类型选动作。返回与 LLM 决策同构的 dict。"""
    if not warnings:
        return {"diagnosis": "无告警", "action": "accept", "hint": "", "reason": "校验通过"}
    names = [w.get("name", "") for w in warnings]
    for name in names:
        if name in _RULE_ACTIONS:
            action, hint = _RULE_ACTIONS[name]
            return {"diagnosis": f"命中规则判据：{name}", "action": action,
                    "hint": hint, "reason": "规则降级路径（未配置模型）"}
    return {"diagnosis": f"未知告警：{names}", "action": "accept", "hint": "",
            "reason": "无法判定成因，接受当前结果并保留告警"}


_DECIDE_SYSTEM = (
    "你是财报结构化抽取的质检员。用户会给你一份「数据自洽性校验告警」，"
    "以及抽取所用页区间的信息。请判断最可能的成因，并从下列三个动作中**选择一个**：\n"
    "1. retry_with_hint —— 提示词理解偏差（金额单位读错、括号负数漏符号、"
    "把「合并及公司」四列表的后两列（母公司）当成合并数、亏损行名未识别）。"
    "选择它时必须给出简洁的补充提示（hint），供下一轮抽取使用。\n"
    "2. relocate —— 定位到的页区间可能不含完整的两期报表，或取到了母公司报表，"
    "需要调整页区间后重抽。\n"
    "3. accept —— 告警可由业务事实解释（例如银行/保险没有流动负债分类、"
    "非经常性损益导致净利率异常），不必重试。\n\n"
    "注意：你只负责判断成因与选择动作，不要输出任何金额数字。\n"
    '只输出 JSON：{"diagnosis": "...", "action": "retry_with_hint|relocate|accept", '
    '"hint": "...", "reason": "..."}'
)


def llm_decision(warnings, context, client, model):
    """让模型诊断成因并选择动作。解析失败时退回规则判据（不中断流程）。"""
    warn_text = "\n".join(
        f"- 第 {w.get('year')} 期：{w.get('name')} —— {w.get('detail')}" for w in warnings)
    user = (f"数据自洽性校验告警：\n{warn_text}\n\n"
            f"抽取上下文：{context}\n\n请按 JSON 格式给出判断。")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _DECIDE_SYSTEM},
                      {"role": "user", "content": user}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:  # noqa: BLE001
        fallback = rule_based_decision(warnings)
        fallback["reason"] = f"模型决策失败（{type(e).__name__}），退回规则判据"
        return fallback
    action = data.get("action")
    if action not in ACTIONS:
        fallback = rule_based_decision(warnings)
        fallback["reason"] = f"模型返回非法动作 {action!r}，退回规则判据"
        return fallback
    return {"diagnosis": str(data.get("diagnosis", ""))[:300],
            "action": action,
            "hint": str(data.get("hint", ""))[:500],
            "reason": str(data.get("reason", ""))[:300]}


def decide(warnings, context, client=None, model=None):
    """有模型用模型判断，没有则用规则判据。"""
    if client is not None and model:
        return llm_decision(warnings, context, client, model)
    return rule_based_decision(warnings)


def widen_range(page_range, n_pages, step=6):
    """relocate 动作：向两侧扩页区间（不越界）。"""
    start, end = page_range
    return max(0, start - step), min(n_pages - 1, end + step)


def run_self_correcting_extract(texts, extract_fn, validate_fn, page_range,
                                max_rounds=2, client=None, model=None,
                                context_extra=""):
    """执行「抽取 → 校验 → 诊断 → 补救」闭环。

    参数：
        texts       逐页文本
        extract_fn  (hint, page_range) -> company dict（由调用方注入，故本模块不依赖 pdfplumber）
        validate_fn (company) -> 告警列表
        page_range  初始页区间（0 起，含）
        max_rounds  最多补救轮数（0 表示只抽一次、不做校验补救）
    返回：(company, trace)
    """
    trace = []
    hint = ""
    rng = tuple(page_range)
    n_pages = len(texts)
    company = None

    for round_no in range(max_rounds + 1):
        company = extract_fn(hint, rng)
        warnings = validate_fn(company)
        n_used = rng[1] - rng[0] + 1
        record = {
            "round": round_no + 1,
            "page_range": [rng[0] + 1, rng[1] + 1],
            "pages_used": n_used,
            "hint": hint,
            "warnings": [w.get("name") for w in warnings],
            "action": None, "diagnosis": None, "reason": None,
        }
        trace.append(record)

        if not warnings:
            record["action"] = "clean"
            record["reason"] = "校验通过，无需补救"
            break
        if round_no >= max_rounds:
            record["action"] = "stop"
            record["reason"] = f"已达轮数上限（{max_rounds}），保留告警"
            break

        context = (f"共 {n_pages} 页，本轮使用第 {rng[0]+1}–{rng[1]+1} 页"
                   f"（{n_used} 页）{context_extra}")
        decision = decide(warnings, context, client=client, model=model)
        record["action"] = decision["action"]
        record["diagnosis"] = decision["diagnosis"]
        record["reason"] = decision["reason"]

        if decision["action"] == "accept":
            record["reason"] = (record["reason"] or "") + "（接受当前结果，告警保留）"
            break
        if decision["action"] == "relocate":
            new_rng = widen_range(rng, n_pages)
            if new_rng == rng:
                break                      # 无法再扩，停
            rng = new_rng
            hint = decision["hint"] or hint
        else:                              # retry_with_hint
            hint = decision["hint"] or hint
            if not hint:
                break

    if company is not None:
        # 浅拷贝后再挂元数据：不改动 extract_fn 传回的对象，
        # 避免调用方复用同一 dict（如内置样例）时被污染。
        company = dict(company)
        company["_trace"] = trace          # 轨迹由闭环自己留档，不依赖调用方
        company["_agent"] = {
            "rounds": len(trace),
            "self_corrected": len(trace) > 1,
            "final_warnings": trace[-1]["warnings"],
        }
    return company, trace


def format_trace(trace):
    """把轨迹转成可读文本（报告用）。"""
    lines = []
    for r in trace:
        head = (f"第 {r['round']} 轮：使用第 {r['page_range'][0]}–{r['page_range'][1]} 页"
                f"（{r['pages_used']} 页）")
        if r["warnings"]:
            head += f"，校验发现 {len(r['warnings'])} 项告警：" + "、".join(r["warnings"])
        else:
            head += "，校验通过"
        lines.append(head)
        if r["action"] and r["action"] not in ("clean",):
            lines.append(f"  · 智能体决策：{r['action']}"
                         + (f"（{r['diagnosis']}）" if r["diagnosis"] else "")
                         + (f" —— {r['reason']}" if r["reason"] else ""))
    return lines
