"""明鉴 · 财务尽调 Agent —— Streamlit Demo UI。

运行：streamlit run app.py
"""
import tempfile

import pandas as pd
import streamlit as st

from diligence.pipeline import run_diligence
from diligence.sample_data import SAMPLES
from diligence.extract import extract_from_pdf

st.set_page_config(page_title="明鉴 · 财务尽调 Agent", layout="wide")

_PCT = {"资产负债率", "毛利率", "净利率", "roe", "roa", "应收账款占营收比",
        "商誉占净资产比", "货币资金占总资产比", "有息负债占总资产比",
        "营收增长率", "净利润增长率"}
_RATIO = {"流动比率", "速动比率", "应收账款周转率", "存货周转率", "净现比",
          "利息保障倍数"}

_SEVERITY_COLOR = {"高": "red", "中": "orange", "低": "blue"}


def fmt_metric(name, v):
    if v is None:
        return "—"
    if name in _PCT:
        return f"{v:.1%}"
    if name in _RATIO:
        return f"{v:.2f}"
    return f"{v:,.0f}"


def metrics_df(metrics):
    years = sorted(metrics.keys())
    rows = []
    for name in metrics[years[-1]]:
        row = {"指标": name}
        for y in years:
            row[str(y)] = fmt_metric(name, metrics[y].get(name))
        rows.append(row)
    return pd.DataFrame(rows)


def render(result):
    level = result["risk_level"]
    st.subheader("综合风险等级")
    st.markdown(f"### :{_SEVERITY_COLOR.get(level, 'blue')}[{level}]")

    st.subheader("关键财务指标")
    st.dataframe(metrics_df(result["metrics"]), use_container_width=True, hide_index=True)

    st.subheader("风险清单")
    rules = result["rules"]
    if not rules:
        st.success("未命中显著风险规则，标的财务表现整体稳健。")
    else:
        for i, r in enumerate(rules, 1):
            color = _SEVERITY_COLOR.get(r["severity"], "blue")
            with st.expander(f"风险 {i}：{r['name']}（{r['severity']} · {r['category']}）", expanded=(r["severity"] == "高")):
                st.markdown(f"**{r['detail']}**")
                for e in r["evidence"]:
                    st.markdown(f"- {e}")

    st.subheader("风险研判")
    if result["narrative"]:
        st.info(result["narrative"])
    else:
        st.markdown("（未调用大模型，基于规则汇总）")

    st.caption("免责声明：本报告仅供研究参考，不构成投资建议。")


st.title("明鉴 · 企业财务尽调与风险研判 Agent")

with st.sidebar:
    st.header("数据源")
    source = st.radio("选择输入方式", ["使用样例", "上传财报 PDF"])
    use_llm = st.checkbox("调用大模型进行风险研判", value=True)

    if source == "使用样例":
        name = st.selectbox("样例", list(SAMPLES.keys()),
                            format_func=lambda k: SAMPLES[k]["company_name"])
    else:
        uploaded = st.file_uploader("上传财报 PDF", type=["pdf"])

    run = st.button("运行尽调", type="primary")

if run:
    if source == "使用样例":
        company = SAMPLES[name]
    else:
        if uploaded is None:
            st.warning("请先上传财报 PDF")
            st.stop()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(uploaded.getvalue())
            pdf_path = f.name
        with st.spinner("正在解析财报并运行尽调..."):
            company = extract_from_pdf(pdf_path)

    with st.spinner("正在计算指标、匹配规则、生成报告..."):
        report, result = run_diligence(company, use_llm=use_llm)

    st.markdown(f"### 标的企业：{company['company_name']}（{company['industry']}）")
    render(result)

    st.download_button("下载完整报告 (Markdown)", report,
                       file_name=f"{company['company_name']}_尽调报告.md")
