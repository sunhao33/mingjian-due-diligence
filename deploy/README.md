# 部署与公网访问方案

赛道一硬性要求：**作品应具备公网内的联通性且能流畅运行；仅限在某个专网或校园网上访问的作品，由于无法评审，将被视为无效参赛作品。**
因此「能在本机跑」不够，必须让评审在公网直接打开。

---

## 方案对比

| 方案 | 公网入口 | 稳定性 | 成本 | 适用场景 |
|------|---------|--------|------|---------|
| **A. 云服务器 + Docker**（推荐） | 固定 IP / 域名 | 长期稳定 | 约 30–60 元/月 | **正式提交与评审期间** |
| B. 云服务器 + systemd + Nginx | 域名 + HTTPS | 长期稳定 | 同上 + 域名 | 需要 HTTPS 与自定义域名 |
| C. 本机 + SSH 反向隧道 | `https://xxx.lhr.life` | 临时，断线即失效 | 免费 | 录视频、临时演示（**不能作为评审入口**） |

---

## 方案 A：云服务器 + Docker（推荐）

镜像定义见 `deploy/Dockerfile`，编排见 `deploy/docker-compose.yml`。

> **依赖清单验证记录（2026-10-04）**：`pip install --dry-run --ignore-installed -r deploy/requirements-lock.txt`
> 解析通过，依赖树为 streamlit 1.65.0 / pandas 3.0.6 / pdfplumber 0.11.10 / openai 3.9.0 /
> python-dotenv 1.2.4 及 44 个传递依赖（含 pydantic、httpx2、pyarrow 等）。
> 本机未安装 Docker，故**镜像构建本身未在本机执行**，首次部署时请在服务器上确认构建日志。

```bash
# 1. 服务器上安装 docker（示例：Ubuntu 22.04）
curl -fsSL https://get.docker.com | sh

# 2. 上传代码
scp -r mingjian-due-diligence user@<服务器IP>:/opt/

# 3. 构建并启动
cd /opt/mingjian-due-diligence
docker compose -f deploy/docker-compose.yml up -d --build

# 4. 验证
curl -s http://127.0.0.1:8501/_stcore/health      # 期望输出 ok
```

浏览器访问 `http://<服务器IP>:8501`。若云厂商有安全组，需放行 8501（或按方案 B 走 80/443）。

需要大模型功能时，在仓库根目录放 `.env`（`DEEPSEEK_API_KEY=...`），并取消 `docker-compose.yml` 中 `env_file` 的注释。

---

## 方案 B：systemd + Nginx（HTTPS）

**1）systemd 服务** `/etc/systemd/system/mingjian.service`

```ini
[Unit]
Description=Mingjian Due Diligence Agent
After=network.target

[Service]
WorkingDirectory=/opt/mingjian-due-diligence
Environment="PATH=/opt/mingjian-due-diligence/.venv/bin"
ExecStart=/opt/mingjian-due-diligence/.venv/bin/python -m streamlit run app.py \
  --server.port=8501 --server.address=127.0.0.1 --server.headless=true \
  --server.fileWatcherType=none --browser.gatherUsageStats=false
Restart=always
RestartSec=5
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now mingjian
systemctl status mingjian
```

**2）Nginx 反向代理**（需为 Streamlit 的 WebSocket 放行 Upgrade 头）

```nginx
server {
    listen 80;
    server_name your.domain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
```

```bash
certbot --nginx -d your.domain.com     # 自动签发 HTTPS 证书
```

---

## 方案 C：本机临时隧道（已验证可用）

无需账号，本机开着即可对外提供 HTTPS 入口：

```powershell
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 `
    -R 80:localhost:8501 nokey@localhost.run
```

输出形如 `https://xxxxxxxx.lhr.life tunneled with tls termination`，该地址即为公网入口。

**实测记录（2026-10-04）**：隧道建立后，从外部网络访问 `https://fc9001b4fad3e3.lhr.life/_stcore/health` 返回 `200 ok`，主页正常加载 —— 证明作品的公网联通性成立。

⚠️ **局限性**：每次重连域名都会变化，进程结束即失效，且依赖本机开机联网。**仅适合录视频与临时演示，不能作为评审期间的正式入口。**

---

## 安全提醒（重要）

1. **不要在公开实例上配置高额度 API Key**：Demo 无登录，任何人打开页面即可上传 PDF 触发抽取，会消耗你的 DeepSeek 额度。建议单独申请一个低额度 Key，或在部署时加访问口令。
2. 上传的年报会先落到临时文件（`app.py` 已改为**用后即删**），但报表文本会发送至 DeepSeek API —— 不要把含未公开底稿的实例公开。
3. Streamlit 默认已开启 XSRF 防护与 CORS 校验，不要为图省事关掉。
4. 公开部署后建议再跑一遍 `python tests/test_offline.py`，确认部署环境与本地行为一致。

---

## 上线后验证清单

- [ ] `curl http://<入口>/_stcore/health` 返回 `ok`
- [ ] 浏览器打开首页，侧栏「数据源」可见
- [ ] 选 risky 样例 → 运行尽调 → 显示 **高风险**（8 条命中）
- [ ] 选 healthy 样例 → 运行尽调 → 显示 **低风险**（0 命中）
- [ ] 手机浏览器打开布局可用（评审可能用移动端）
- [ ] 下载 Markdown 报告按钮可用
