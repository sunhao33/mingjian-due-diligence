"""命令行入口：对样例公司跑尽调闭环并输出报告。

用法：
    python main.py                 # 跑全部样例（健康 vs 风险）
    python main.py risky           # 只跑风险样本
    python main.py risky --no-llm  # 不调用模型（仅规则 + 指标）
"""
import argparse
import sys

from diligence.sample_data import SAMPLES
from diligence.pipeline import run_diligence
from diligence import config


def main():
    parser = argparse.ArgumentParser(description="明鉴 · 财务尽调 Agent")
    parser.add_argument("name", nargs="?", choices=list(SAMPLES.keys()),
                        help="样例名称（默认跑全部）")
    parser.add_argument("--no-llm", action="store_true",
                        help="不调用大模型，仅用规则引擎生成报告")
    parser.add_argument("--pdf", default="", help="从财报 PDF 解析并跑尽调（覆盖样例）")
    parser.add_argument("--out", default="", help="报告输出目录（可选）")
    args = parser.parse_args()

    if args.pdf:
        from diligence.extract import extract_from_pdf
        company = extract_from_pdf(args.pdf)
        report, result = run_diligence(company, use_llm=not args.no_llm)
        print("=" * 60)
        print(report)
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
            import os
            os.makedirs(args.out, exist_ok=True)
            path = os.path.join(args.out, f"{name}_report.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"[已保存] {path}\n")


if __name__ == "__main__":
    sys.exit(main())
