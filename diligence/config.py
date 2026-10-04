"""加载环境配置。"""
import os

try:
    from dotenv import load_dotenv
except ImportError:  # 纯规则模式允许不装 python-dotenv，直接读环境变量
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def llm_available() -> bool:
    return bool(DEEPSEEK_API_KEY)
