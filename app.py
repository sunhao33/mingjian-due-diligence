"""明鉴 · 财务尽调 Agent —— Streamlit Demo UI。

运行：streamlit run app.py

界面结构：
    首屏引导 → 侧栏数据源 → 运行 → 英雄区（标的企业 + 风险等级徽标 + 核心指标卡）
                                    → 分页签（财务指标 / 风险清单 / 研判与追溯）
"""
import os
import tempfile

import pandas as pd
import streamlit as st

from diligence.pipeline import run_diligence
from diligence.sample_data import SAMPLES
# 注意：diligence.extract 会拉起 pdfplumber，只在真正要解析 PDF 时再导入

st.set_page_config(page_title="明鉴 · 财务尽调 Agent", page_icon="📑", layout="wide")

_PCT = {"资产负债率", "毛利率", "净利率", "roe", "roa", "应收账款占营收比",
        "商誉占净资产比", "货币资金占总资产比", "有息负债占总资产比",
        "营收增长率", "净利润增长率"}
_RATIO = {"流动比率", "速动比率", "应收账款周转率", "存货周转率", "净现比",
          "利息保障倍数"}

_SEVERITY_COLOR = {"高": "red", "中": "orange", "低": "blue"}
# risk_level() 返回「高风险/中风险/关注/低风险」，与逐条风险的 severity 不是同一套取值
_LEVEL_COLOR = {"高风险": "red", "中风险": "orange", "关注": "blue", "低风险": "green"}
_LEVEL_BADGE = {"高风险": "badge-high", "中风险": "badge-mid",
                "关注": "badge-watch", "低风险": "badge-low"}
_LEVEL_EMOJI = {"高风险": "🔴", "中风险": "🟠", "关注": "🔵", "低风险": "🟢"}

_CSS = """
<style>
  .block-container {padding-top: 2.4rem; max-width: 1200px;}
  h1 {font-size: 1.95rem !important; letter-spacing: .5px;}
  section[data-testid="stSidebar"] {background: #fafbfc;}
  section[data-testid="stSidebar"] h1 {font-size: 1.15rem !important;}

  .hero {padding: 20px 24px; border-radius: 14px; border: 1px solid #e6e8eb;
         background: linear-gradient(135deg, #fbfcfe 0%, #f4f7fb 100%); margin-bottom: 6px;}
  .hero-company {font-size: 1.25rem; font-weight: 700; color: #1b1f24;}
  .hero-sub {color: #5b6470; font-size: .9rem; margin-top: 2px;}
  .badge {display: inline-block; padding: 3px 14px; border-radius: 999px;
          font-weight: 700; font-size: .92rem;}
  .badge-high  {background: #fdecea; color: #b3261e; border: 1px solid #f3c2bd;}
  .badge-mid   {background: #fff4e5; color: #b26a00; border: 1px solid #f3d9b5;}
  .badge-watch {background: #eaf2fd; color: #1a5fb4; border: 1px solid #c5daf5;}
  .badge-low   {background: #e9f7ee; color: #1a7f37; border: 1px solid #bfe5cb;}

  .card {padding: 14px 16px; border-radius: 12px; border: 1px solid #e6e8eb;
         background: #fff; height: 100%;}
  .card-label {color: #6b7280; font-size: .8rem;}
  .card-value {font-size: 1.5rem; font-weight: 700; color: #1b1f24; line-height: 1.25;}
  .card-delta {font-size: .8rem; margin-top: 2px;}
  .up {color: #b3261e;} .down {color: #1a7f37;} .flat {color: #6b7280;}

  .evi {background: #f7f8fa; border-left: 3px solid #c9ced6; padding: 6px 12px;
        border-radius: 0 6px 6px 0; color: #333; font-size: .88rem; margin: 4px 0;}
  .empty {padding: 46px 24px; border-radius: 14px; border: 1px dashed #cfd6de;
          background: #fbfcfe; text-align: center; color: #5b6470;}
  .empty b {color: #1b1f24;}
</style>
"""


def _fmt_metric(name, v):
    if v is None:
        return "—"
    if name in _PCT:
        return f"{v:.1%}"
    if name in _RATIO:
        return f"{v:.2f}"
    return f"{v:,.0f}"


def fmt_metric(name, v):          # 兼容旧调用名
    return _fmt_metric(name, v)


def metrics_df(metrics):
    years = sorted(metrics.keys())
    rows = []
    for name in metrics[years[-1]]:
        row = {"指标": name}
        for y in years:
            row[str(y)] = _fmt_metric(name, metrics[y].get(name))
        rows.append(row)
    return pd.DataFrame(rows)


def _delta(cur, prev, higher_is_better=True):
    """返回 (文本, css 类)：用于指标卡上的同比变化。"""
    if cur is None or prev is None:
        return "", "flat"
    diff = cur - prev
    if abs(diff) < 1e-9:
        return ("持平", "flat")
    arrow = "▲" if diff > 0 else "▼"
    good = (diff > 0) == higher_is_better
    cls = "down" if good else "up"     # 红涨绿跌按"好/坏"着色，不按数字正负
    if abs(prev) > 1e-9 and abs(prev) < 1e6:
        return (f"{arrow} {abs(diff)/abs(prev):.1%} 较上期", cls)
    return (f"{arrow} {abs(diff):,.0f} 较上期", cls)


def _hero(company, industry, level, metrics, warnings):
    years = sorted(metrics.keys())
    latest, prev = metrics[years[-1]], (metrics[years[-2]] if len(years) > 1 else None)
    badge = _LEVEL_BADGE.get(level, "badge-watch")
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="hero">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;">
                <div>
                  <div class="hero-company">{company}</div>
                  <div class="hero-sub">{industry} · 报告期 {years[-1]}"""
        + (f"（对比 {years[-2]}）" if prev else "")
        + f"""</div>
                </div>
                <div style="text-align:right;">
                  <div class="hero-sub" style="margin-bottom:6px;">综合风险等级</div>
                  <span class="badge {badge}">{_LEVEL_EMOJI.get(level,'')} {level}</span>
                </div>
              </div>
            </div>""",
        unsafe_allow_html=True)

    st.write("")
    cards = [
        ("资产负债率", latest.get("资产负债率"), prev.get("资产负债率") if prev else None, False, ""),
        ("毛利率", latest.get("毛利率"), prev.get("毛利率") if prev else None, True, ""),
        ("净利率", latest.get("净利率"), prev.get("净利率") if prev else None, True, ""),
        ("净现比", latest.get("净现比"), prev.get("净现比") if prev else None, True, ""),
    ]
    cols = st.columns(4)
    for col, (label, cur, pre, hib, unit) in zip(cols, cards):
        txt, cls = _delta(cur, pre, hib)
        col.markdown(
            f"""<div class="card">
                  <div class="card-label">{label}</div>
                  <div class="card-value">{_fmt_metric(label, cur)}{unit}</div>
                  <div class="card-delta {cls}">{txt or "&nbsp;"}</div>
                </div>""",
            unsafe_allow_html=True)


def _render_warnings(warnings):
    if not warnings:
        return
    st.markdown("#### ⚠️ 数据校验告警")
    st.caption("以下为抽取数据的自洽性告警：不影响规则执行，但提示结论所依赖的数据可能不可靠。")
    for w in warnings:
        prefix = f"第 {w['year']} 期：" if w.get("year") else ""
        st.warning(f"{prefix}**{w['name']}** —— {w['detail']}")


def _render_rules(rules):
    if not rules:
        st.success("未命中显著风险规则，标的财务表现整体稳健。")
        return
    for i, r in enumerate(rules, 1):
        sev = r["severity"]
        icon = {"高": "🔴", "中": "🟠", "低": "🔵"}.get(sev, "⚪")
        title = f"{icon} 风险 {i}：{r['name']}　·　{sev} · {r['category']}"
        with st.expander(title, expanded=(sev == "高")):
            st.markdown(f"**{r['detail']}**")
            st.markdown("**证据链**")
            for e in r["evidence"]:
                st.markdown(f'<div class="evi">{e}</div>', unsafe_allow_html=True)


def _render_trace(result):
    trace = result.get("trace")
    if not trace or len(trace) < 2:
        return
    from diligence.agent import format_trace

    st.markdown("#### 🤖 抽取自校正轨迹")
    st.caption("每轮抽完先做数据自洽性校验；发现矛盾时由模型诊断成因并选择补救动作。")
    for line in format_trace(trace):
        if line.startswith("第 "):
            st.markdown(f"**{line}**")
        else:
            st.caption(line)


def render(result):
    level = result["risk_level"]
    _hero(result["company"], result["industry"], level,
          result["metrics"], result.get("warnings"))
    _render_warnings(result.get("warnings"))

    st.write("")
    tab1, tab2, tab3 = st.tabs(["📊 关键财务指标", f"⚠️ 风险清单（{len(result['rules'])}）",
                                "🧭 研判与追溯"])
    with tab1:
        st.dataframe(metrics_df(result["metrics"]), use_container_width=True,
                     hide_index=True)
        st.caption("口径：有上期数据时周转率取期初期末平均余额；利息保障倍数 "
                   "EBIT ≈ 净利润 + 财务费用；缺失科目一律记为「—」，不按 0 计算。")
    with tab2:
        _render_rules(result["rules"])
    with tab3:
        st.markdown("#### 风险研判")
        if result["narrative"]:
            st.info(result["narrative"])
        else:
            st.markdown("（未调用大模型，基于规则汇总；配置 `DEEPSEEK_API_KEY` 后可由模型生成归因叙述）")
        _render_trace(result)
        if result.get("warnings"):
            st.markdown("#### 数据校验明细")
            for w in result["warnings"]:
                st.markdown(f"- **{w['name']}**：{w['detail']}")
    st.write("")
    st.caption("免责声明：本报告仅供研究参考，不构成投资建议。")


# ───────────────────────── 页面 ─────────────────────────
st.title("📑 明鉴 · 企业财务尽调与风险研判 Agent")
st.caption("上传一份标的公司年报，自动完成解析、指标计算、规则匹配与风险研判，"
           "输出一份**可解释**的尽调初筛报告。")

with st.sidebar:
    st.markdown("### 数据源")
    source = st.radio("选择输入方式", ["使用样例", "上传财报 PDF"], label_visibility="collapsed")
    use_llm = st.checkbox("调用大模型进行风险研判", value=True,
                          help="未配置 DEEPSEEK_API_KEY 时自动降级为规则模式")

    if source == "使用样例":
        name = st.selectbox("样例", list(SAMPLES.keys()),
                            format_func=lambda k: SAMPLES[k]["company_name"])
        st.caption("内置样例为虚构数据，用于演示完整闭环。")
    else:
        uploaded = st.file_uploader("上传财报 PDF", type=["pdf"])
        st.caption("需配置 API Key；扫描件需先自行 OCR。")

    st.divider()
    run = st.button("运行尽调", type="primary", use_container_width=True)
    st.caption("纯规则模式不调用任何模型，可离线运行。")

if run:
    if source == "使用样例":
        company = SAMPLES[name]
    else:
        if uploaded is None:
            st.warning("请先上传财报 PDF")
            st.stop()
        from diligence.extract import extract_from_pdf

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(uploaded.getvalue())
            pdf_path = f.name
        try:
            with st.spinner("正在定位报表页并调用模型抽取…"):
                company = extract_from_pdf(pdf_path)
        finally:
            os.unlink(pdf_path)  # 临时文件用后即删，避免残留财报底稿

    with st.spinner("正在计算指标、匹配规则、生成报告…"):
        report, result = run_diligence(company, use_llm=use_llm)
    st.session_state["result"] = result
    st.session_state["report"] = report
    st.session_state["cname"] = company["company_name"]

if "result" in st.session_state:
    render(st.session_state["result"])
    st.download_button("⬇️ 下载完整报告 (Markdown)", st.session_state["report"],
                       file_name=f"{st.session_state['cname']}_尽调报告.md")
else:
    st.markdown(
        """<div class="empty">
             <div style="font-size:2rem;">🔎</div>
             <p><b>尚未运行尽调</b></p>
             <p>在左侧选择「使用样例」或「上传财报 PDF」，然后点击 <b>运行尽调</b>。<br/>
                样例无需任何配置即可跑通完整闭环。</p>
           </div>""",
        unsafe_allow_html=True)
