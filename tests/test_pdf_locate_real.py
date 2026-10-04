# -*- coding: utf-8 -*-
"""真实年报页面定位验证：检验 extract.py 能否圈出三大合并报表所在页。

需要 pdfplumber。用法：
    python tests/test_pdf_locate_real.py <年报.pdf>

判据（独立于被测算法）：报表页 = 页首若干行里出现「独立成行的报表标题」，
标题允许「合并 / 合并及公司 / 本行 / 母公司」前缀与「（续）」后缀。
脚本检查定位区间是否覆盖三类报表各自的标题页。

实测记录（2026-10-04）：
- 万科企业股份有限公司 2024 年年度报告（327 页）→ 定位 141–162 页，三大报表全覆盖
- 中国工商银行股份有限公司 2024 年年度报告（410 页）→ 定位 195–219 页，三大报表全覆盖
  （该报告把报表命名为「现金流量表」「合并及公司资产负债表」，
   且「合并资产负债表」首次出现在审计报告正文里 —— 早期按首次命中会定位失败）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import pdfplumber
except ImportError:
    print("跳过：未安装 pdfplumber（pip install -r requirements.txt）")
    sys.exit(0)

from diligence.locate import locate_statement_pages  # noqa: E402

TITLE_RE = re.compile(
    r"^(?:合并及?(?:银行|公司)?|本行|母公司)?\s*"
    r"(资产负债表|利润表|现金流量表)\s*(?:（续）|\(续\))?$"
)
STATEMENTS = ["资产负债表", "利润表", "现金流量表"]


def title_pages(texts, kind):
    """独立判据：页首出现独立成行的该类报表标题即算报表页。"""
    pages = []
    for i, text in enumerate(texts):
        head = [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
        for ln in head:
            m = TITLE_RE.match(ln)
            if m and m.group(1) == kind:
                pages.append(i + 1)
                break
    return pages


def main(path):
    with pdfplumber.open(path) as pdf:
        print(f"文件: {os.path.basename(path)}  "
              f"{os.path.getsize(path)/1024/1024:.1f} MB  共 {len(pdf.pages)} 页")
        texts = [(p.extract_text() or "") for p in pdf.pages]
        start, end = locate_statement_pages(pdf, texts)

    print(f"算法定位区间：第 {start+1} ~ {end+1} 页（{end-start+1} 页）")
    assert start <= end, f"区间反向：{start}~{end}"
    failed = 0
    for kind in STATEMENTS:
        real = title_pages(texts, kind)
        covered = [p for p in real if start + 1 <= p <= end + 1]
        if not real:
            print(f"  {kind:<8} 文档中未找到独立成行的标题（可能是图片版，需 OCR）")
        elif covered:
            print(f"  {kind:<8} ✓ 已覆盖（标题页 {real}）")
        else:
            print(f"  {kind:<8} ✗ 未覆盖（标题页 {real}）")
            failed += 1
    print(f"\n结论：{'三大报表全部覆盖' if failed == 0 else f'{failed} 项未覆盖'}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
