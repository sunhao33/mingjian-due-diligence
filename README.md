# 明鉴 · 企业财务尽调与风险研判 Agent

> 上传一份标的公司财报，智能体自动完成解析、指标计算、规则匹配与风险研判，输出一份可解释的尽调初筛报告。

面向**投资尽调初筛**场景的 AI 财务尽调 Agent。以公开上市公司财报（PDF）为输入，通过多步编排自动完成「资料理解 → 指标计算 → 规则匹配 → 风险提示 → 报告生成」的任务闭环。

## 功能特性

- **资料理解**：`pdfplumber` 定位并提取三大报表（资产负债表 / 利润表 / 现金流量表），LLM 抽取为结构化 Schema；
- **指标计算**：纯 Python 计算偿债、盈利、营运、成长、现金流五大类财务指标，数值不交给 LLM；
- **规则匹配**：可配置风控规则引擎（8 大类 13+ 条），含行业基准（房地产 85% / 建筑 80% / 白酒食品 50% / 金融豁免）；
- **风险提示**：命中项带证据引用（指标 + 阈值 + 实际值），LLM 归因生成研判；
- **报告生成**：输出结构化 Markdown 尽调报告，可导出。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 DeepSeek API Key

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
cp .env.example .env
```

`.env` 内容：

```
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 命令行运行

```bash
# 跑全部样例（健康 vs 风险）
python main.py

# 只跑风险样本
python main.py risky

# 纯规则模式（不调用 LLM，仅规则 + 指标）
python main.py risky --no-llm

# 从财报 PDF 解析并跑尽调
python main.py --pdf /path/to/annual_report.pdf
```

### 4. Streamlit Demo

```bash
python -m streamlit run app.py
```

浏览器打开后，可选择「使用样例」或「上传财报 PDF」，点击「运行尽调」即可查看风险等级、关键指标、风险清单与研判结论，并可下载 Markdown 报告。

## 项目结构

```
.
├── app.py                    # Streamlit Demo UI
├── main.py                   # 命令行入口
├── diligence/                # 核心模块
│   ├── config.py             # 环境配置加载
│   ├── extract.py            # PDF 解析 + LLM 结构化抽取
│   ├── metrics.py            # 财务指标计算（纯代码）
│   ├── rules.py              # 风控规则引擎 + 风险分级
│   ├── llm.py                # DeepSeek 客户端 + 风险研判
│   ├── report.py             # Markdown 报告生成
│   ├── pipeline.py           # 尽调主流程编排
│   └── sample_data.py        # 内置样例数据
├── scripts/
│   └── gen_test_pdf.py       # 从样例数据生成测试 PDF
├── 方案书.md                 # 参赛方案书
└── requirements.txt
```

## 真实数据验证

| 标的 | 行业 | 综合风险等级 | 命中关键风险 |
|------|------|-------------|-------------|
| 贵州茅台（2024 年报） | 白酒 | 低风险 | 未命中显著规则 |
| 万科 A（2024 年报） | 房地产 | 高风险 | 经营亏损、利息保障倍数过低、毛利率下滑、营收负增长 |

## 免责声明

本工具由 AI 辅助生成，仅供研究参考，不构成投资建议。定位于「尽调初筛辅助」，最终判断由投资团队完成。
