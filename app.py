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

from diligence import config
from diligence.pipeline import run_diligence
from diligence.sample_data import SAMPLES
# 注意：diligence.extract 会拉起 pdfplumber，只在真正要解析 PDF 时再导入

st.set_page_config(page_title="明鉴 · 财务尽调 Agent", page_icon="📑", layout="wide")

_PCT = {"资产负债率", "毛利率", "净利率", "roe", "roa", "应收账款占营收比",
        "商誉占净资产比", "货币资金占总资产比", "有息负债占总资产比",
        "营收增长率", "净利润增长率"}
_RATIO = {"流动比率", "速动比率", "应收账款周转率", "存货周转率", "净现比",
          "利息保障倍数"}

# 按股票代码获取的年报缓存目录（.gitignore 已排除 data/downloads/，不会进版本库）
_DL_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "data", "downloads"))
# risk_level() 返回「高风险/中风险/关注/低风险」，与逐条风险的 severity 不是同一套取值
_LEVEL_BADGE = {"高风险": "badge-high", "中风险": "badge-mid",
                "关注": "badge-watch", "低风险": "badge-low"}

# 降级为规则抽取时可供选择的行业基准（对应 rules._debt_limit 的关键词分支）
_FALLBACK_INDUSTRIES = ["制造业", "房地产", "建筑", "食品饮料", "银行/金融"]
_LEVEL_EMOJI = {"高风险": "🔴", "中风险": "🟠", "关注": "🔵", "低风险": "🟢"}

_CSS = """
<style>
  .block-container {padding-top: 2.4rem; max-width: 1200px;}
  h1 {font-size: 1.95rem !important; letter-spacing: .5px;}

  /* 颜色一律取自 Streamlit 主题变量（--text-color / --background-color /
     --secondary-background-color），深浅色主题自动适配；
     边框用半透明灰、语义色用中间调，保证在白底与深底上都可读。
     侧栏不再覆盖背景色，交给主题自己处理。 */
  .hero {padding: 20px 24px; border-radius: 14px;
         border: 1px solid rgba(128,128,128,.25);
         background: var(--secondary-background-color); margin-bottom: 6px;}
  .hero-company {font-size: 1.25rem; font-weight: 700; color: var(--text-color);}
  .hero-sub {color: var(--text-color); opacity: .68; font-size: .9rem; margin-top: 2px;}

  .badge {display: inline-block; padding: 3px 14px; border-radius: 999px;
          font-weight: 700; font-size: .92rem;}
  .badge-high  {background: rgba(224,82,82,.16);  color: #e05252;
                border: 1px solid rgba(224,82,82,.45);}
  .badge-mid   {background: rgba(219,140,32,.16); color: #d98c20;
                border: 1px solid rgba(219,140,32,.45);}
  .badge-watch {background: rgba(64,132,224,.16); color: #4084e0;
                border: 1px solid rgba(64,132,224,.45);}
  .badge-low   {background: rgba(46,158,91,.16);  color: #2e9e5b;
                border: 1px solid rgba(46,158,91,.45);}

  .card {padding: 14px 16px; border-radius: 12px;
         border: 1px solid rgba(128,128,128,.25);
         background: var(--background-color); height: 100%;}
  .card-label {color: var(--text-color); opacity: .68; font-size: .8rem;}
  .card-value {font-size: 1.5rem; font-weight: 700; color: var(--text-color);
               line-height: 1.25;}
  .card-delta {font-size: .8rem; margin-top: 2px;}
  .up {color: #e05252;}                     /* 变差 */
  .down {color: #2e9e5b;}                   /* 变好 */
  .flat {color: var(--text-color); opacity: .6;}

  .evi {background: var(--secondary-background-color);
        border-left: 3px solid rgba(128,128,128,.5); padding: 6px 12px;
        border-radius: 0 6px 6px 0; color: var(--text-color);
        font-size: .88rem; margin: 4px 0;}
  .empty {padding: 46px 24px; border-radius: 14px;
          border: 1px dashed rgba(128,128,128,.4);
          background: var(--secondary-background-color);
          text-align: center; color: var(--text-color);}
  .empty b {color: var(--text-color);}
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


def _delta(cur, prev, higher_is_better=True, is_pct=False):
    """返回 (文本, css 类)：用于指标卡上的同比变化。

    is_pct=True 的指标（资产负债率、毛利率等）本身已是百分比，
    同比应显示**百分点**变化，否则 66.7%→76.0% 会被显示成「涨了 14.0%」，误导读者。
    """
    if cur is None or prev is None:
        return "", "flat"
    diff = cur - prev
    if abs(diff) < 1e-9:
        return ("持平", "flat")
    arrow = "▲" if diff > 0 else "▼"
    good = (diff > 0) == higher_is_better
    cls = "down" if good else "up"     # 红=变差、绿=变好，按"好坏"着色而非数字正负
    if is_pct:
        return (f"{arrow} {abs(diff) * 100:.1f} 个百分点", cls)
    # 比率类指标跨零时（如净现比 0.27 → −0.60），"变化百分之多少"没有意义
    # （会出现「▼325.0%」这种读不懂的数字），改为直说方向转变。
    if (prev < 0) != (cur < 0):
        return ("由正转负" if cur < 0 else "由负转正", cls)
    if abs(prev) > 1e-9 and abs(prev) < 1e6:
        return (f"{arrow} {abs(diff)/abs(prev):.1%} 较上期", cls)
    return (f"{arrow} {abs(diff):,.0f} 较上期", cls)


def _hero(company, industry, level, metrics):
    years = sorted(metrics.keys())
    latest, prev = metrics[years[-1]], (metrics[years[-2]] if len(years) > 1 else None)
    badge = _LEVEL_BADGE.get(level, "badge-watch")
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
        ("资产负债率", latest.get("资产负债率"), prev.get("资产负债率") if prev else None, False, True),
        ("毛利率", latest.get("毛利率"), prev.get("毛利率") if prev else None, True, True),
        ("净利率", latest.get("净利率"), prev.get("净利率") if prev else None, True, True),
        ("净现比", latest.get("净现比"), prev.get("净现比") if prev else None, True, False),
    ]
    cols = st.columns(4)
    for col, (label, cur, pre, hib, is_pct) in zip(cols, cards):
        txt, cls = _delta(cur, pre, hib, is_pct)
        col.markdown(
            f"""<div class="card">
                  <div class="card-label">{label}</div>
                  <div class="card-value">{_fmt_metric(label, cur)}</div>
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
    _hero(result["company"], result["industry"], level, result["metrics"])
    # 数据来源与公告出处：界面也要能看到，而不是只在下载的报告里
    # 注意 result["company"] 是公司名（字符串），公司字典里的 _source 由 pipeline 透传为 result["source"]
    src = result.get("source")
    if src:
        used = src.get("pages_used") or ["—", "—"]
        bits = [f"共 {src.get('pages_total', '—')} 页",
                f"自动定位第 {used[0]}–{used[1]} 页"]
        if src.get("rounds"):
            bits.append(f"抽取 {src['rounds']} 轮")
        st.caption(f"📄 数据来源：{src.get('file', '—')}（{'，'.join(bits)}）")
        if src.get("origin"):
            st.caption(f"🔗 公告出处：{src['origin']}")
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


def _apply_theme():
    """按侧栏开关切换整站深浅色。

    实现方式：修改 Streamlit 的 theme.base 配置并重跑。这样换肤是**整个应用**
    （含侧栏、控件、表格、代码块）一起换，而不是只给自定义卡片套一层颜色。

    注意：`st._config` 属内部接口，故做了兜底——失败时只在界面提示，
    不影响其余功能（本机 Streamlit 1.65 实测可用）。
    """
    want = "dark" if st.session_state.get("theme_dark") else "light"
    try:
        if st._config.get_option("theme.base") != want:
            st._config.set_option("theme.base", want)
            return True
    except Exception:  # noqa: BLE001
        st.session_state["theme_unsupported"] = True
    return False


# ───────────────────────── 页面 ─────────────────────────
st.title("📑 明鉴 · 企业财务尽调与风险研判 Agent")
st.caption("上传一份标的公司年报，自动完成解析、指标计算、规则匹配与风险研判，"
           "输出一份**可解释**的尽调初筛报告。")
# 样式必须在**每次渲染**都注入：空状态、侧栏、结果页都要用，
# 曾因把它写在 _hero() 里，导致未运行时的空状态卡片完全没有样式。
st.markdown(_CSS, unsafe_allow_html=True)

# 首屏同步一次主题开关的实际状态（避免显示与实际主题不一致）
if "theme_dark" not in st.session_state:
    try:
        st.session_state["theme_dark"] = (st._config.get_option("theme.base") == "dark")
    except Exception:  # noqa: BLE001
        st.session_state["theme_dark"] = False

with st.sidebar:
    st.toggle("🌙 深色模式", key="theme_dark",
              help="一键切换深色 / 浅色，整个应用（含侧栏与表格）一起换肤")
    if _apply_theme():
        st.rerun()
    if st.session_state.get("theme_unsupported"):
        st.caption("（当前环境不支持运行时换肤，可用 `--theme.base` 启动参数切换）")
    st.divider()

    st.markdown("### 数据源")
    source = st.radio("选择输入方式",
                      ["使用样例", "输入股票代码", "上传财报 PDF"],
                      label_visibility="collapsed")
    use_llm = st.checkbox("调用大模型进行风险研判", value=True,
                          help="未配置 DEEPSEEK_API_KEY 时自动降级为规则模式")

    if source == "使用样例":
        name = st.selectbox("样例", list(SAMPLES.keys()),
                            format_func=lambda k: SAMPLES[k]["company_name"])
        st.caption("内置样例为虚构数据，用于演示完整闭环。")
    elif source == "输入股票代码":
        from diligence import areport

        def _query(code_text):
            """查询并记住选中的年报；失败时清空选择并给出可读原因。"""
            try:
                code = areport.normalize_code(code_text)
                st.session_state["ann_pick"] = areport.list_annual_reports(code)[0]
                st.session_state.pop("ann_meta", None)   # 换了标的后丢弃旧记录
            except areport.ReportSourceError as e:
                st.session_state.pop("ann_pick", None)
                st.error(str(e))

        _code_in = st.text_input("股票代码", placeholder="如 000002 / 600519",
                                 help="沪深两市 6 位代码；自动获取最新年度报告")
        if st.button("查询最新年报", use_container_width=True):
            _query(_code_in)
        # 快捷选择：演示时一点即可，省去输入
        st.caption("或直接选：")
        for _col, (_c, _n) in zip(st.columns(3),
                                  (("000002", "万科A"), ("000333", "美的集团"),
                                   ("600519", "贵州茅台"))):
            if _col.button(_n, use_container_width=True, key=f"quick_{_c}"):
                _query(_c)
        _pick = st.session_state.get("ann_pick")
        if _pick:
            st.success(f"已找到：{_pick['title']}")
            st.caption(f"{_pick['date']} 公告 · {areport.market_of(_pick['code'])} · "
                       f"点「运行尽调」下载并解析")
        else:
            st.caption("取数失败时可改用「上传财报 PDF」——该路径不依赖任何外部接口。")
    else:
        uploaded = st.file_uploader("上传财报 PDF", type=["pdf"])
        st.caption("扫描件需先自行 OCR。")

    if source in ("输入股票代码", "上传财报 PDF"):
        # 行业只影响"资产负债率偏高"的参考线；大模型会从年报正文自动识别行业，
        # 这个选择仅在模型不可用、降级为规则抽取时生效（届时报告会明确告警）。
        st.selectbox("行业基准", _FALLBACK_INDUSTRIES, key="fallback_industry",
                     help="大模型会从年报正文自动识别所属行业；"
                          "若模型不可用而降级为规则抽取，则按这里的选择套用阈值")

    # ── 模型配置（可选）──────────────────────────────────────
    # 刻意不做成「必须填 Key 才能用」：不填也能跑完整流程（规则抽取 + 规则汇总），
    # 填了才能用大模型读取真实年报并生成归因叙述。
    _llm_ready = config.llm_available()
    with st.expander(("⚙️ 模型配置" + ("（已就绪）" if _llm_ready else "（可选）")),
                     expanded=False):
        if _llm_ready:
            st.success(f"已配置：{config.DEEPSEEK_MODEL}")
        else:
            st.info("未配置 —— 当前为**纯规则模式**，全部功能仍可用")
        typed = st.text_input("DeepSeek API Key", type="password", key="api_key_input",
                              placeholder="sk-...",
                              help="仅在本次会话内存中使用，不写入磁盘；"
                                   "留空则读取环境变量 / .env")
        if typed and typed.strip() != config.DEEPSEEK_API_KEY:
            from diligence.llm import reset_client

            config.DEEPSEEK_API_KEY = typed.strip()
            reset_client()          # 让旧客户端失效，下次调用按新 key 重建
            st.caption("✅ 本次会话已启用（关闭页面即失效）")
        st.caption("不填也能跑完整流程（真实年报走规则解析、研判走规则汇总）；"
                   "填了才能用大模型抽取并生成归因叙述。")

    st.divider()
    run = st.button("运行尽调", type="primary", use_container_width=True)
    if _llm_ready:
        st.caption("真实年报将走大模型抽取 + **自校正闭环**。")
    else:
        st.caption("纯规则模式不调用任何模型，可离线运行。")

if run:
    if source == "使用样例":
        company = SAMPLES[name]
        st.session_state["extract_notice"] = None
    elif source == "输入股票代码":
        from diligence import areport
        from diligence.extract import extract_with_fallback

        _pick = st.session_state.get("ann_pick")
        if not _pick:
            st.warning("请先填写股票代码并点「查询最新年报」")
            st.stop()
        _meta = st.session_state.get("ann_meta")
        if not _meta or _meta.get("art_code") != _pick.get("art_code"):
            try:
                with st.spinner(f"正在下载《{_pick['title']}》…"):
                    _path, _meta = areport.fetch_latest_annual(
                        _pick["code"], _DL_DIR, year=_pick["year"])
                st.session_state["ann_meta"] = _meta
            except areport.ReportSourceError as e:
                st.error(f"获取年报失败：{e}")
                st.info("可改用「上传财报 PDF」——该路径不依赖任何外部接口。")
                st.stop()
        with st.spinner("正在定位报表页并抽取…"):
            # 大模型不可用（无 Key / Key 失效 / 断网）时自动降级为规则抽取，不中断流程
            company, _notice = extract_with_fallback(
                _meta["path"], origin=areport.describe(_meta),
                company_name=areport.company_name_of(_pick.get("title", "")),
                industry=st.session_state.get("fallback_industry", "制造业"))
        st.session_state["extract_notice"] = _notice
    else:
        if uploaded is None:
            st.warning("请先上传财报 PDF")
            st.stop()
        from diligence.extract import extract_with_fallback

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(uploaded.getvalue())
            pdf_path = f.name
        try:
            with st.spinner("正在定位报表页并抽取…"):
                company, _notice = extract_with_fallback(
                    pdf_path, company_name=os.path.splitext(uploaded.name)[0],
                    industry=st.session_state.get("fallback_industry", "制造业"))
            st.session_state["extract_notice"] = _notice
        finally:
            os.unlink(pdf_path)  # 临时文件用后即删，避免残留财报底稿

    with st.spinner("正在计算指标、匹配规则、生成报告…"):
        report, result = run_diligence(company, use_llm=use_llm)
    st.session_state["result"] = result
    st.session_state["report"] = report
    st.session_state["html"] = result.get("html", "")
    st.session_state["cname"] = company["company_name"]

if "result" in st.session_state:
    _notice = st.session_state.get("extract_notice")
    _llm_err = (st.session_state.get("result") or {}).get("llm_error")
    if _notice:
        st.warning(
            f"⚠️ **未能调用大模型（{_notice}），已自动降级为规则抽取**\n\n"
            f"数据仍从年报原文解析，但三点差异需知悉：\n"
            f"1. **行业基准为假设值**：「{st.session_state.get('fallback_industry', '制造业')}」"
            f"（模型能从年报正文自动识别行业，规则抽取做不到）；\n"
            f"2. **抽取自校正闭环未生效**（该闭环依赖模型诊断）；\n"
            f"3. 风险研判为规则汇总，非模型归因。\n\n"
            f"如需完整能力：在侧栏「⚙️ 模型配置」填入有效的 DeepSeek API Key 后重新运行。"
        )
    elif _llm_err:
        # 只影响归因叙述这一段，其余（指标、规则、清单）不受影响
        st.info(f"ℹ️ 风险研判未能调用大模型（{_llm_err}），已改为规则汇总。"
                f"指标计算、规则判定与证据链不受影响。")
    render(st.session_state["result"])
    st.write("")
    _c = st.session_state["cname"]
    _dl1, _dl2 = st.columns([3, 1])
    with _dl1:
        # HTML 为默认：任何人双击都能用浏览器打开，且可一键打印成 PDF
        st.download_button("⬇️ 下载尽调报告（HTML，推荐 · 可打印为 PDF）",
                           st.session_state.get("html", ""),
                           file_name=f"{_c}_尽调报告.html", mime="text/html",
                           type="primary", use_container_width=True)
    with _dl2:
        st.download_button("下载 Markdown（开发者）", st.session_state["report"],
                           file_name=f"{_c}_尽调报告.md", use_container_width=True)
    st.caption("HTML 报告为单文件、无外部依赖：双击用浏览器打开，"
               "按 Ctrl+P 即可打印或另存为 PDF；Markdown 版供二次处理。")
else:
    # 单行 HTML：Streamlit 的 markdown 渲染对多行 HTML 块不可靠（缩进/空行会截断标签）
    st.markdown(
        '<div class="empty">'
        '<div style="font-size:2.2rem;line-height:1.2;">🔎</div>'
        '<p style="font-size:1.05rem;margin:6px 0 2px;"><b>尚未运行尽调</b></p>'
        '<p>左侧选数据源：<b>内置样例</b>（零配置即可跑通）、'
        '<b>输入股票代码</b>（自动获取最新年报）或 <b>上传财报 PDF</b>，<br/>'
        '然后点击 <b>运行尽调</b>。</p>'
        '</div>',
        unsafe_allow_html=True)
