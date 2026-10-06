"""生成自包含的 HTML 尽调报告 —— 浏览器双击即可打开，可直接打印成 PDF。

为什么选 HTML 而不是 PDF：
- **零依赖、跨平台**：纯字符串拼装，不需要中文字体文件（fpdf2 方案要绑 9 MB
  的 simhei.ttf，且 Linux 服务器上并没有这个字体）；
- **人人打得开**：任何系统双击都用默认浏览器打开，可一键打印/另存为 PDF，也可直接邮件发送；
- **排版可控**：全部样式内联，不引用任何外部资源，离线也能正常显示。

内容上刻意做了两件事，让非财务背景的读者也看得懂：
1. **结论先行**：开头一段大白话总述（风险等级 + 最需要担心什么）；
2. **白话解释**：每条风险除证据外，附一段「这是什么意思」的通俗说明。
"""

import html

from .rules import risk_level

_LEVEL_CLASS = {"高风险": "lv-high", "中风险": "lv-mid",
                "关注": "lv-watch", "低风险": "lv-low"}
_SEV_CLASS = {"高": "sev-high", "中": "sev-mid", "低": "sev-low"}

# 每条风险的「白话解释」：写给不懂财务的人看。
# 键必须与 rules.py 中 hit(category, name, ...) 的 **name（第二个参数）** 完全一致，
# 有测试专门校验覆盖率（名称写错会当场失败）。
PLAIN = {
    "资产负债率偏高":
        "公司账上的资产，有相当一部分是借钱买来的。借得多、自有本钱少，"
        "遇上行情不好或银行收紧贷款时，还钱压力会明显变大。",
    "流动比率偏低":
        "一年内要还的短期债务，与手头能快速变现的流动资产相比偏多。"
        "短期周转的缓冲垫很薄，一旦回款变慢就容易紧张。",
    "利息保障倍数过低":
        "公司赚的钱已经不够付利息了。正常经营产生的利润连利息都覆盖不住，"
        "说明经营本身在失血，而不是「暂时周转不开」。",
    "利息保障倍数偏低":
        "赚的钱付完利息后剩得不多。虽然目前还覆盖得住，但安全垫很薄，"
        "利率上行或利润下滑就可能覆盖不住。",
    "利润缺乏现金支撑":
        "账面显示赚钱，但实际收到的现金很少甚至为负。这种利润质量存疑，"
        "可能是货卖出去了钱还没收回来，或者利润主要来自非现金项目。",
    "净现比偏低":
        "每赚 1 元账面利润，实际收回的现金不到 1 元。利润的「含金量」偏低。",
    "经营现金流转负":
        "公司主营业务从「往回收钱」变成了「往外倒钱」。持续下去，"
        "再多的账面利润也撑不住日常运转。",
    "经营现金流大幅下滑":
        "主营业务收回来的现金明显变少。可能是下游回款变慢，也可能是采购付款提前，"
        "需要看现金流量表的构成再下结论。",
    "应收账款占比过高":
        "卖出去的东西有相当大一部分钱还没收回来，「白条」占比偏高。"
        "一旦下游资金紧张，这部分就可能变成坏账。",
    "毛利率大幅下滑":
        "卖东西的差价明显变薄，且幅度较大。常见原因是价格战、原材料涨价或"
        "产品结构恶化，需要判断是一次性还是趋势性。",
    "毛利率下滑":
        "卖东西赚的差价变薄了。可能是原材料涨价、产品降价，"
        "也可能是竞争加剧导致议价能力下降。",
    "经营亏损":
        "公司本期是亏钱的。需要判断这是行业周期导致的暂时性亏损，"
        "还是商业模式本身出了问题。",
    "净利润大幅下滑":
        "利润出现大幅缩水。要区分是一次性因素（如资产减值、诉讼计提）"
        "还是经营本身在恶化——前者可修复，后者更麻烦。",
    "净利润下滑":
        "利润同比减少。幅度尚不剧烈，但要看趋势会不会延续下去。",
    "营收大幅下滑":
        "收入出现明显萎缩，通常伴随客户流失、需求下降或行业下行，"
        "需要弄清下滑是一次性事件还是趋势。",
    "营收负增长":
        "公司的生意规模在收缩。需要区分是主动收缩（砍掉不赚钱的业务）"
        "还是被动丢单（客户或市场份额流失）。",
    "商誉减值风险":
        "公司过去收购别家时多付了钱，这笔「多付的钱」记在账上。"
        "如果被收购方业绩不达预期，这笔钱就要一次性减掉，直接冲击利润。",
    "存贷双高":
        "账上现金很多、借的钱也很多，两者同时偏高。正常经营不需要既囤着大量现金"
        "又大量举债，需要核实这些资金是否受限（保证金、共管账户等），"
        "以及是否存在财务粉饰。",
    "非标准审计意见":
        "会计师事务所对这份财报出具了「保留意见」等非标结论，"
        "意味着连审计师也无法完全确认报表的可靠性，属于重要警示信号。",
}


def _esc(x):
    return html.escape("" if x is None else str(x))


def _fmt(name, v, pct_names=(), ratio_names=()):
    if v is None:
        return "—"
    if name in pct_names:
        return f"{v:.1%}"
    if name in ratio_names:
        return f"{v:.2f}"
    return f"{v:,.0f}"


_PCT = {"资产负债率", "毛利率", "净利率", "roe", "roa", "应收账款占营收比",
        "商誉占净资产比", "货币资金占总资产比", "有息负债占总资产比",
        "营收增长率", "净利润增长率"}
_RATIO = {"流动比率", "速动比率", "应收账款周转率", "存货周转率", "净现比",
          "利息保障倍数"}

# 指标卡上「越大越好 / 越小越好」
_HIGHER_BETTER = {"毛利率": True, "净利率": True, "净现比": True, "roe": True,
                  "roa": True, "流动比率": True, "速动比率": True,
                  "资产负债率": False}


def _delta_txt(cur, prev, name):
    """同比文案：百分比类用「个百分点」，比率跨零直说方向转变。"""
    if cur is None or prev is None:
        return "", "flat"
    diff = cur - prev
    if abs(diff) < 1e-9:
        return "持平", "flat"
    hib = _HIGHER_BETTER.get(name, True)
    good = (diff > 0) == hib
    cls = "good" if good else "bad"
    arrow = "▲" if diff > 0 else "▼"
    if name in _PCT:
        return f"{arrow} {abs(diff) * 100:.1f} 个百分点", cls
    if (prev < 0) != (cur < 0):
        return ("由正转负" if cur < 0 else "由负转正"), cls
    if abs(prev) > 1e-9 and abs(prev) < 1e6:
        return f"{arrow} {abs(diff) / abs(prev):.1%} 较上期", cls
    return f"{arrow} {abs(diff):,.0f} 较上期", cls


def _one_liner(level, rules, years):
    """开头的大白话总述：结论先行，让读者三秒抓住重点。"""
    if not rules:
        return ("本期未命中显著风险规则，主要财务指标处于合理区间，"
                "未发现需要立即关注的异常信号。")
    highs = [r for r in rules if r.get("severity") == "高"]
    names = "、".join(f"「{r['name']}」" for r in rules[:3])
    lead = {"高风险": "整体风险偏高，建议谨慎对待",
            "中风险": "存在若干需要关注的问题",
            "关注": "整体尚可，但有值得留意的信号",
            "低风险": "整体财务表现稳健"}.get(level, "")
    return (f"报告期 {years[-1]}，共命中 {len(rules)} 条风险规则"
            f"（其中高风险 {len(highs)} 条）。{lead}，最需要关注的是 {names}。"
            "下文逐条给出判断依据与通俗解释。")


def render_html(company, metrics, rules, narrative=None, warnings=None,
                trace=None, title="企业财务尽调与风险研判报告"):
    """把尽调结果渲染成自包含 HTML（无外部资源，可直接打印）。"""
    years = sorted(metrics.keys())
    latest, prev = metrics[years[-1]], (metrics[years[-2]] if len(years) > 1 else None)
    name = company.get("company_name", "—")
    industry = company.get("industry", "—")
    src = company.get("_source") or {}
    level = risk_level(rules)          # 与命令行/界面共用同一判定，不要另算一套

    cards = [("资产负债率", False), ("毛利率", True), ("净利率", True), ("净现比", True)]
    card_html = []
    for key, _ in cards:
        cur = latest.get(key)
        pre = prev.get(key) if prev else None
        txt, cls = _delta_txt(cur, pre, key)
        card_html.append(
            f'<div class="card"><div class="k">{_esc(key)}</div>'
            f'<div class="v">{_esc(_fmt(key, cur, _PCT, _RATIO))}</div>'
            f'<div class="d {cls}">{_esc(txt) or "&nbsp;"}</div></div>')

    # 指标表
    rows = []
    for k in latest:
        cells = "".join(
            f'<td>{_esc(_fmt(k, metrics[y].get(k), _PCT, _RATIO))}</td>' for y in years)
        rows.append(f"<tr><th>{_esc(k)}</th>{cells}</tr>")
    table = ('<table class="metrics"><thead><tr><th>指标</th>'
             + "".join(f"<th>{_esc(y)}</th>" for y in years)
             + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")

    # 风险清单
    risk_html = []
    if not rules:
        risk_html.append('<p class="ok">未命中显著风险规则。</p>')
    for i, r in enumerate(rules, 1):
        sev = r.get("severity", "")
        plain = PLAIN.get(r.get("name", ""), "")
        evi = "".join(f'<li>{_esc(e)}</li>' for e in r.get("evidence", []))
        risk_html.append(
            f'<div class="risk {_SEV_CLASS.get(sev, "")}">'
            f'<div class="rhead"><span class="num">{i}</span>'
            f'<span class="rname">{_esc(r.get("name"))}</span>'
            f'<span class="tag">{_esc(sev)} · {_esc(r.get("category"))}</span></div>'
            f'<p class="rsum">{_esc(r.get("detail"))}</p>'
            + (f'<p class="plain"><b>通俗解释：</b>{_esc(plain)}</p>' if plain else "")
            + (f'<div class="evi"><b>判断依据</b><ul>{evi}</ul></div>' if evi else "")
            + "</div>")

    warn_html = ""
    if warnings:
        items = "".join(
            f'<li><b>{_esc(w.get("name"))}</b>：{_esc(w.get("detail"))}</li>'
            for w in warnings)
        warn_html = (f'<section><h2>数据自洽性校验</h2>'
                     f'<p class="note">以下为抽取数据的自动校验告警：不影响规则执行，'
                     f'但提示结论所依赖的数据可能不可靠，建议回溯原始报表核对。</p>'
                     f'<ul class="warn">{items}</ul></section>')

    trace_html = ""
    if trace and len(trace) > 1:
        from .agent import format_trace
        lines = "".join(f"<li>{_esc(x)}</li>" for x in format_trace(trace))
        trace_html = (f'<section><h2>抽取自校正轨迹</h2>'
                      f'<p class="note">每轮抽完先做数据校验；发现矛盾时由模型诊断成因'
                      f'并选择补救动作，直至通过或达到轮数上限。</p>'
                      f'<ul class="trace">{lines}</ul></section>')

    src_line = ""
    if src:
        used = src.get("pages_used") or ["—", "—"]
        src_line = (f'<p><b>数据来源</b>：{_esc(src.get("file", "—"))}'
                    f'（共 {_esc(src.get("pages_total", "—"))} 页，'
                    f'自动定位第 {_esc(used[0])}–{_esc(used[1])} 页'
                    + (f'，抽取 {_esc(src["rounds"])} 轮' if src.get("rounds") else "")
                    + f'，抽取模型 {_esc(src.get("model", "—"))}）</p>')
        if src.get("origin"):
            src_line += f'<p><b>公告出处</b>：{_esc(src["origin"])}</p>'

    from datetime import date
    narrative_html = (f'<section><h2>风险研判</h2>'
                      f'<p class="narr">{_esc(narrative)}</p></section>') if narrative else ""

    # 注意：整段必须用括号包住。若不包，`return f"""..."""` 在第一个三引号处
    # 就结束语句，后续以 `+` 开头的行会变成**独立的表达式语句**（被静默丢弃），
    # 结果是只返回了 HTML 的开头一段——这里踩过坑，别删这对括号。
    return (f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} · {_esc(title)}</title>
<style>
  :root {{ --ink:#1b1f24; --muted:#5b6470; --line:#e3e6ea; --bg:#f6f7f9;
           --red:#c0392b; --orange:#b26a00; --blue:#1a5fb4; --green:#1a7f37; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:28px 16px 60px; background:var(--bg); color:var(--ink);
          font:15px/1.75 "Microsoft YaHei","PingFang SC","Hiragino Sans GB",
          "Source Han Sans SC",sans-serif; }}
  .wrap {{ max-width:940px; margin:0 auto; background:#fff; border-radius:14px;
           box-shadow:0 2px 18px rgba(0,0,0,.07); padding:38px 44px 46px; }}
  h1 {{ font-size:1.7rem; margin:0 0 6px; }}
  h2 {{ font-size:1.15rem; margin:34px 0 12px; padding-bottom:8px;
        border-bottom:2px solid var(--line); }}
  .meta {{ color:var(--muted); font-size:.92rem; margin-bottom:20px; }}
  .level {{ display:inline-block; padding:5px 18px; border-radius:999px;
            font-weight:700; font-size:1rem; }}
  .lv-high {{ background:#fdecea; color:var(--red); border:1px solid #f3c2bd; }}
  .lv-mid  {{ background:#fff4e5; color:var(--orange); border:1px solid #f3d9b5; }}
  .lv-watch{{ background:#eaf2fd; color:var(--blue); border:1px solid #c5daf5; }}
  .lv-low  {{ background:#e9f7ee; color:var(--green); border:1px solid #bfe5cb; }}
  .head {{ display:flex; justify-content:space-between; align-items:flex-start;
           gap:20px; flex-wrap:wrap; }}
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin:18px 0 4px; }}
  .card {{ flex:1 1 190px; border:1px solid var(--line); border-radius:11px;
           padding:13px 16px; }}
  .card .k {{ color:var(--muted); font-size:.82rem; }}
  .card .v {{ font-size:1.45rem; font-weight:700; margin:2px 0; }}
  .card .d {{ font-size:.8rem; }}
  .good {{ color:var(--green); }} .bad {{ color:var(--red); }}
  .flat {{ color:var(--muted); }}
  .lead {{ background:#f8fafc; border-left:4px solid var(--blue); border-radius:0 8px 8px 0;
           padding:12px 18px; margin:16px 0 0; }}
  table.metrics {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
  table.metrics th, table.metrics td {{ border-bottom:1px solid var(--line);
           padding:7px 10px; text-align:right; }}
  table.metrics th:first-child, table.metrics td:first-child {{ text-align:left; }}
  table.metrics thead th {{ background:#fafbfc; font-weight:600; }}
  .risk {{ border:1px solid var(--line); border-left-width:4px; border-radius:0 10px 10px 0;
           padding:14px 18px; margin:12px 0; }}
  .risk.sev-high {{ border-left-color:var(--red); }}
  .risk.sev-mid  {{ border-left-color:var(--orange); }}
  .risk.sev-low  {{ border-left-color:var(--blue); }}
  .rhead {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .num {{ width:22px; height:22px; border-radius:50%; background:var(--ink); color:#fff;
          font-size:.78rem; display:inline-flex; align-items:center;
          justify-content:center; }}
  .rname {{ font-weight:700; }}
  .tag {{ color:var(--muted); font-size:.82rem; }}
  .rsum {{ margin:8px 0 6px; }}
  .plain {{ background:#fbfcfd; border:1px dashed var(--line); border-radius:8px;
            padding:9px 13px; margin:6px 0; color:#2b3138; font-size:.92rem; }}
  .evi {{ margin-top:6px; font-size:.9rem; }}
  .evi ul {{ margin:4px 0 0 18px; padding:0; color:var(--muted); }}
  .note {{ color:var(--muted); font-size:.88rem; }}
  ul.warn li {{ margin:6px 0; }}
  ul.trace li {{ margin:4px 0; font-size:.9rem; color:var(--muted); }}
  .narr {{ background:#f8fafc; border-radius:8px; padding:14px 18px; }}
  .ok {{ color:var(--green); }}
  footer {{ margin-top:34px; padding-top:14px; border-top:1px solid var(--line);
            color:var(--muted); font-size:.85rem; }}
  @media print {{
    body {{ background:#fff; padding:0; font-size:12pt; }}
    .wrap {{ box-shadow:none; border-radius:0; padding:0; max-width:none; }}
    .risk, table.metrics tr, .card {{ break-inside:avoid; page-break-inside:avoid; }}
    h2 {{ break-after:avoid; }}
    @page {{ margin:16mm; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>{_esc(name)}</h1>
      <div class="meta">{_esc(industry)} · 报告期 {_esc(years[-1])}"""
    + (f"（对比 {_esc(years[-2])}）" if prev else "") + f""" · 生成日期 {date.today().isoformat()}</div>
    </div>
    <div style="text-align:right">
      <div class="meta" style="margin:0 0 6px">综合风险等级</div>
      <span class="level {_LEVEL_CLASS.get(level, 'lv-watch')}">{_esc(level)}</span>
    </div>
  </div>

  <p class="lead">{_esc(_one_liner(level, rules, years))}</p>

  <div class="cards">{''.join(card_html)}</div>

  <section><h2>关键财务指标</h2>{table}
    <p class="note">口径：有上期数据时周转率采用期初期末平均余额；
    利息保障倍数 EBIT ≈ 净利润 + 财务费用；缺失科目一律记为「—」，不按 0 参与计算。</p>
  </section>

  <section><h2>风险清单（{len(rules)} 条）</h2>{''.join(risk_html)}</section>

  {narrative_html}
  {warn_html}
  {trace_html}

  <section><h2>数据来源与说明</h2>{src_line}
    <p class="note">本报告由「明鉴 · 企业财务尽调与风险研判 Agent」自动生成：
    数据抽取与语言组织使用大语言模型，全部指标计算、规则判定与校验均为确定性代码，
    模型不参与任何算术。报告仅供研究参考，不构成投资建议。</p>
  </section>

  <footer>本报告可按 Ctrl+P（Mac 为 ⌘P）直接打印或另存为 PDF。</footer>
</div>
</body>
</html>
""")
