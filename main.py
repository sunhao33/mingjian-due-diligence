"""命令行入口：对样例公司跑尽调闭环并输出报告。

用法：
    python main.py                      # 跑全部样例（健康 vs 风险）
    python main.py risky                # 只跑风险样本
    python main.py risky --no-llm       # 不调用模型（仅规则 + 指标）
    python main.py --pdf 年报.pdf       # 从财报 PDF 解析并跑尽调
    python main.py --pdf 年报.pdf --explain   # 只做页面定位诊断（不需要 API Key）
    python main.py --code 000002        # 按股票代码自动获取最新年报并跑尽调
    python main.py --code 000002 --list # 只列出可用年报，不下载
"""
import argparse
import os
import sys

from diligence.sample_data import SAMPLES
from diligence.pipeline import run_diligence
from diligence import config


def _save(report, out_dir, stem, html=None):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{stem}_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[已保存] {path}")
    if html:
        hpath = os.path.join(out_dir, f"{stem}_尽调报告.html")
        with open(hpath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[已保存] {hpath}  ← 浏览器双击即可打开，可 Ctrl+P 打印成 PDF")


def main():
    parser = argparse.ArgumentParser(description="明鉴 · 财务尽调 Agent")
    parser.add_argument("name", nargs="?", choices=list(SAMPLES.keys()),
                        help="样例名称（默认跑全部）")
    parser.add_argument("--no-llm", action="store_true",
                        help="不调用大模型，仅用规则引擎生成报告")
    parser.add_argument("--pdf", default="", help="从财报 PDF 解析并跑尽调（覆盖样例）")
    parser.add_argument("--code", default="", help="按股票代码自动获取最新年报并跑尽调")
    parser.add_argument("--list", action="store_true",
                        help="配合 --code：只列出可用的年度报告，不下载")
    parser.add_argument("--explain", action="store_true",
                        help="只做报表页面定位诊断并退出（配合 --pdf，不需要 API Key）")
    parser.add_argument("--out", default="", help="报告输出目录（可选）")
    args = parser.parse_args()

    if args.explain:
        if not args.pdf:
            print("--explain 需要配合 --pdf 使用，例如：python main.py --pdf 年报.pdf --explain")
            return 2
        from diligence.extract import diagnose_pdf
        from diligence.locate import format_diagnosis

        diag = diagnose_pdf(args.pdf)
        print(f"[定位诊断] {diag['file']}")
        for line in format_diagnosis(diag):
            print(line)
        return 0

    # ── 按股票代码取年报 ───────────────────────────────────
    if args.code:
        from diligence import areport

        try:
            code = areport.normalize_code(args.code)
            reps = areport.list_annual_reports(code)
        except areport.ReportSourceError as e:
            print(f"[取数失败] {e}")
            print("可改用：python main.py --pdf 年报.pdf（该路径不依赖外部接口）")
            return 3
        print(f"[{code} {areport.market_of(code)}] 找到 {len(reps)} 份年度报告：")
        for r in reps:
            print(f"  {r['year']} 年 | {r['date']} | {r['title']}")
        if args.list:
            return 0
        pick = reps[0]
        dest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "data", "downloads")
        try:
            path, meta = areport.fetch_latest_annual(code, dest_dir, year=pick["year"])
        except areport.ReportSourceError as e:
            print(f"[下载失败] {e}")
            return 3
        print(f"[已下载] {path}（{meta['size']/1024/1024:.1f} MB）")

        from diligence.extract import extract_from_pdf
        company = extract_from_pdf(path, origin=areport.describe(meta))
        report, result = run_diligence(company, use_llm=not args.no_llm)
        print("=" * 60)
        print(report)
        if args.out:
            _save(report, args.out, f"{code}_{pick['year']}", result.get("html"))
        return 0

    if args.pdf:
        from diligence.extract import extract_from_pdf
        company = extract_from_pdf(args.pdf)
        report, result = run_diligence(company, use_llm=not args.no_llm)
        print("=" * 60)
        print(report)
        if args.out:
            _save(report, args.out, "pdf", result.get("html"))
        return 0

    names = [args.name] if args.name else list(SAMPLES.keys())

    if not config.llm_available():
        print("[提示] 未检测到 DEEPSEEK_API_KEY，将跳过模型研判，仅用规则引擎。")

    for name in names:
        company = SAMPLES[name]
        use_llm = not args.no_llm
        report, result = run_diligence(company, use_llm=use_llm)
        print("=" * 60)
        print(report)
        print()

        if args.out:
            _save(report, args.out, name, result.get("html"))


if __name__ == "__main__":
    sys.exit(main())
