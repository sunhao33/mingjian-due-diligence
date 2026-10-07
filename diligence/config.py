"""加载环境配置。

两条读取路径都要支持，因为本地和云端拿密钥的方式不同：
  · 本地开发：.env 文件 -> python-dotenv 写入环境变量
  · Streamlit Community Cloud：控制台的 Secrets -> **只进 st.secrets**，
    不会变成环境变量（官方文档明确说明）

原来只用 os.getenv，因此在云端读不到 key —— 页面不报错，只是
「风险研判」那一段静默缺失，排查起来很费时间。
"""
import os


def _secret(name, default=""):
    """优先 st.secrets，其次环境变量。"""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        # 纯命令行模式（main.py）没有 streamlit，或本地没有 secrets 文件
        pass
    return os.getenv(name, default)


def _load_dotenv_if_present():
    """本地 .env 支持。缺 python-dotenv 时静默跳过（与原有降级一致）。"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


_load_dotenv_if_present()

DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _secret("DEEPSEEK_MODEL", "deepseek-chat")


def llm_available() -> bool:
    return bool(DEEPSEEK_API_KEY)
