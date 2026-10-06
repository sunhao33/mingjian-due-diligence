#!/usr/bin/env bash
# 明鉴 · 企业财务尽调与风险研判 Agent —— 一键部署脚本
#
# 适用：全新的 Ubuntu 22.04 / 24.04 服务器（阿里云、腾讯云等轻量应用服务器）
# 用法：
#   sudo bash deploy.sh                       # 不带 API Key（评委访问的形态，纯规则模式）
#   sudo DEEPSEEK_API_KEY=sk-xxx bash deploy.sh   # 带 API Key（可用真实年报做大模型抽取）
#
# 脚本做的事：装 Docker → 检查端口 → 构建镜像 → 起服务 → 健康检查 → 打印公网地址
set -euo pipefail

PORT="${PORT:-8501}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '    \033[31m✗ %s\033[0m\n' "$1"; exit 1; }

# ── 1. 环境检查 ──────────────────────────────────────────
step "1/6 检查运行环境"
[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo bash deploy.sh"
( . /etc/os-release 2>/dev/null && ok "系统：${PRETTY_NAME:-未知}" ) || warn "无法识别系统版本"
[ -f "$REPO_DIR/app.py" ] || die "未在 $REPO_DIR 找到 app.py，请在项目根目录的 deploy/ 下运行本脚本"
ok "项目目录：$REPO_DIR"

MEM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)
if [ "$MEM_MB" -gt 0 ] && [ "$MEM_MB" -lt 1500 ]; then
  warn "内存仅 ${MEM_MB}MB：解析 300 页以上年报可能吃紧，建议 2GB 起"
else
  ok "内存：${MEM_MB}MB"
fi

# ── 2. 安装 Docker ──────────────────────────────────────
step "2/6 准备 Docker"
if command -v docker >/dev/null 2>&1; then
  ok "已安装：$(docker --version)"
else
  warn "未安装，正在用官方脚本安装（约 1–2 分钟）…"
  curl -fsSL https://get.docker.com | sh >/dev/null || die "Docker 安装失败，请检查网络"
  ok "已安装：$(docker --version)"
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ── 3. 端口检查 ─────────────────────────────────────────
step "3/6 检查端口 $PORT"
if command -v ss >/dev/null 2>&1 && ss -ltn "( sport = :$PORT )" 2>/dev/null | grep -q ":$PORT"; then
  warn "端口 $PORT 已被占用，正在停止旧的 mingjian 容器"
  docker rm -f mingjian >/dev/null 2>&1 || true
fi
ok "端口 $PORT 可用"

# ── 4. 写入运行配置（可选 API Key，不进镜像）─────────────
step "4/6 运行配置"
ENV_FILE="$REPO_DIR/.env"
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  printf 'DEEPSEEK_API_KEY=%s\n' "$DEEPSEEK_API_KEY" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "已写入 .env（含 API Key，权限 600）"
else
  # 必须保留这个文件：docker-compose.yml 的 env_file 指向它，
  # 文件缺失会导致 compose 直接启动失败（这一条踩过坑）。
  printf '# 未配置 API Key —— 当前以纯规则模式运行（全部功能可用）\n# 需要大模型能力时，写入下面一行后重启容器：\n# DEEPSEEK_API_KEY=sk-xxx\n' > "$ENV_FILE"
  warn "未提供 API Key —— 将以「纯规则模式」运行（已生成 .env 占位）"
fi

# ── 5. 构建并启动 ───────────────────────────────────────
step "5/6 构建镜像并启动（首次约 2–5 分钟）"
cd "$REPO_DIR/deploy"
docker compose up -d --build || die "启动失败，请查看：docker compose logs"

# 自检：镜像里绝不能有 .env（Dockerfile 有 COPY . .，靠 .dockerignore 拦住）
if docker run --rm --entrypoint sh mingjian:latest -c 'test -f /app/.env' 2>/dev/null; then
  warn "镜像内发现 /app/.env —— .dockerignore 未生效，密钥有泄露风险！"
else
  ok "镜像内不含 .env（.dockerignore 生效，密钥只在运行时注入）"
fi

step "等待服务就绪"
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/_stcore/health" >/dev/null 2>&1; then
    ok "服务已就绪（第 ${i} 次探测）"
    break
  fi
  [ "$i" -eq 40 ] && die "启动超时，请查看：docker compose logs --tail=50"
  sleep 3
done

# ── 6. 自检并打印访问地址 ───────────────────────────────
step "6/6 自检"
BODY=$(curl -fsS "http://127.0.0.1:$PORT/_stcore/health" || true)
[ "$BODY" = "ok" ] && ok "本地健康检查通过：ok" || warn "本地健康检查返回：$BODY"

PUB_IP=$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null \
         || curl -fsS --max-time 8 https://ifconfig.me 2>/dev/null \
         || hostname -I 2>/dev/null | awk '{print $1}' || echo "服务器公网IP")

printf '\n\033[1;32m================ 部署完成 ================\033[0m\n'
printf '  访问地址： \033[1;33mhttp://%s:%s\033[0m\n' "$PUB_IP" "$PORT"
printf '  健康检查： http://%s:%s/_stcore/health\n' "$PUB_IP" "$PORT"
printf '\033[1;32m=========================================\033[0m\n'
cat <<'TIP'

接下来必须做的两件事（否则可能「本机能开、外网打不开」）：

  1) 到云厂商控制台的「防火墙 / 安全组」放行 TCP 8501 端口（来源 0.0.0.0/0）
     —— 默认只开了 22，这一步是最常见的卡点。

  2) 用手机 4G（不要连 WiFi）打开上面的访问地址验证。
     能看到「明鉴 · 企业财务尽调与风险研判 Agent」页面即为公网可达。

常用命令：
  查看日志： cd deploy && docker compose logs -f
  重启服务： cd deploy && docker compose restart
  停止服务： cd deploy && docker compose down
TIP
