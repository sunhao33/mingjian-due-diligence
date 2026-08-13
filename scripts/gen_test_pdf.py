"""从样例数据生成测试财报 PDF，用于验证「PDF -> 解析 -> 报告」全链路。

用法：python scripts/gen_test_pdf.py risky  -> 输出 data/risky_report.pdf
"""
import os
import sys

from fpdf import FPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diligence.sample_data import SAMPLES  # noqa: E402

FONT = r"C:\Windows\Fonts\simhei.ttf"


def _section(pdf, title):
    pdf.set_font("SimHei", size=12)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")


def _rows(pdf, label, data, unit="万元"):
    pdf.set_font("SimHei", size=10)
    for key, val in data.items():
        text = f"{key}：{val} {unit}" if val is not None else f"{key}：—"
        pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")


def generate(company, out_path):
    pdf = FPDF()
    pdf.add_font("SimHei", "", FONT)
    pdf.add_page()
    pdf.set_font("SimHei", size=16)
    pdf.cell(0, 10, f"{company['company_name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"所属行业：{company['industry']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    for p in company["periods"]:
        pdf.set_font("SimHei", size=14)
        pdf.cell(0, 9, f"报告期：{p['year']} 年", new_x="LMARGIN", new_y="NEXT")
        _section(pdf, "资产负债表")
        _rows(pdf, "资产负债表", p["balance_sheet"])
        _section(pdf, "利润表")
        _rows(pdf, "利润表", p["income"])
        _section(pdf, "现金流量表")
        _rows(pdf, "现金流量表", p["cashflow"])
        pdf.cell(0, 6, f"审计意见：{p['audit_opinion']}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    pdf.output(out_path)
    return out_path


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "risky"
    os.makedirs("data", exist_ok=True)
    out = f"data/{name}_report.pdf"
    generate(SAMPLES[name], out)
    print(f"[已生成] {out}")
