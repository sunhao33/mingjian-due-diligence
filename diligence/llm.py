"""DeepSeek 客户端 —— 用于风险归因等需要语言理解的环节。

数值计算与规则判定不经过 LLM，只有「解读 + 归因 + 表达」调用模型。
"""
import json

from . import config

_client = None


def get_client():
    global _client
    if _client is None and config.llm_available():
        from openai import OpenAI

        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY,
                         base_url=config.DEEPSEEK_BASE_URL)
    return _client


def summarize_risks(company, metrics, rules):
    """基于命中规则生成风险研判叙述。未配置 API 时返回 None。"""
    client = get_client()
    if client is None or not rules:
        return None

    latest_year = sorted(metrics.keys())[-1]
    rules_text = "\n".join(
        f"- [{r['severity']}] {r['name']}：{r['detail']}" for r in rules
    )
    system = (
        "你是一名资深投资尽调分析师。请基于给定的风险规则命中结果，"
        "用 3-5 句话撰写一段客观、克制的「风险研判」总结，"
        "说明该公司最需要关注的问题及其可能对投资决策的影响。"
        "不要编造规则之外的数据，不要给出投资建议。"
    )
    user = (
        f"公司：{company['company_name']}（{company['industry']}）\n"
        f"报告期：{latest_year}\n\n"
        f"命中风险：\n{rules_text}"
    )
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.2,
    )
    return resp.choices[0].message.content
