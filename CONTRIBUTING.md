# 贡献指南

感谢你对 **明鉴 · 企业财务尽调与风险研判 Agent** 的关注！欢迎提交 Issue 与 Pull Request。

## 如何参与

1. **反馈问题**：在 [Issues](../../issues) 中提交 Bug 或功能建议，使用对应模板。
2. **提交代码**：Fork 本仓库 → 创建分支 → 修改 → 提交 Pull Request。
3. **扩展规则库**：新增风控规则或行业基准，欢迎贡献 `diligence/rules.py` 中的规则与阈值。

## 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 DeepSeek API Key
python main.py         # 运行样例验证
```

提交前请确保：

- 代码通过 `python main.py` 本地验证；
- 不要提交 `.env`、本地配置或大体积财报 PDF（`data/` 下 PDF 已被 `.gitignore` 忽略）；
- 规则/阈值改动请在 PR 中说明依据与口径。

## 代码风格

- Python 3.9+，遵循 PEP 8；
- 财务指标计算保持「纯代码、不交 LLM」的原则；
- 新增规则需包含：指标、阈值/条件、风险等级、解释模板、证据引用。

## 行为准则

请保持友善、专业，尊重他人劳动。欢迎任何形式的建设性贡献。
