# 明鉴 · 财务尽调 Agent —— 部署镜像
# 构建：docker build -f deploy/Dockerfile -t mingjian:latest .
# 运行：docker run -d --name mingjian -p 8501:8501 mingjian:latest
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# 依赖单独一层，利用构建缓存
COPY deploy/requirements-lock.txt /app/deploy/requirements-lock.txt
RUN pip install --no-cache-dir -r /app/deploy/requirements-lock.txt

COPY . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=4).read()==b'ok' else 1)"

CMD ["python", "-m", "streamlit", "run", "app.py"]
