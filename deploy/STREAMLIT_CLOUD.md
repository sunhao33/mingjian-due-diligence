# 明鉴 · 公网部署说明（Streamlit Community Cloud）

> 赛道一硬性要求：作品须具备公网联通性，**仅限专网或校园网访问的视为无效作品**。
> 本文给出**免费、无需备案、无需服务器**的公网部署路径。

---

## 一、为什么用 Streamlit Community Cloud

明鉴是 **Streamlit 应用**（`streamlit run app.py`），需要 Python 服务端运行，
**不能**用 GitHub Pages 这类纯静态托管（那是 ToYu 宣传站用的方案）。

Streamlit Community Cloud 是官方免费托管，专为 Streamlit 应用设计：

| 对比项 | Streamlit Cloud（推荐） | 云服务器 + Docker |
|---|---|---|
| 费用 | **免费** | 约 30–60 元/月 |
| 备案 | **不需要** | 国内节点需要，1–3 周 |
| 运维 | 不用管 | 自己装 Docker、盯进程 |
| 部署耗时 | **约 5 分钟** | 半天起 |
| 睡眠策略 | 闲置后休眠，访问自动唤醒 | 常驻 |

> `deploy/README.md` 里原有的方案 A（云服务器 + Docker）仍然保留，作为
> 「需要长期稳定 + 自定义域名」时的进阶选项；日常评审用 Streamlit Cloud 即可。

---

## 二、部署前提对照（明鉴现状）

官方要求与明鉴实际情况逐项核对：

| 官方要求 | 明鉴情况 | 结论 |
|---|---|---|
| 公开的 GitHub 仓库 | `sunhao33/mingjian-due-diligence`（公开） | ✅ |
| 入口文件 | `app.py`（仓库根目录） | ✅ |
| 依赖清单 `requirements.txt` | 存在于仓库根目录 | ✅ |
| 不把密钥提交进仓库 | `.gitignore` 已忽略 `.env`，历史中也从未出现 | ✅ |
| 系统级依赖 `packages.txt` | 不需要（无 `apt-get` 依赖） | ✅ |

**四项必备条件全部满足**，可以部署。

---

## 三、必须先修一处：API Key 的读取方式

### 问题

`diligence/config.py` 目前这样读配置：

```python
from dotenv import load_dotenv
load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
```

这在本地没问题（读 `.env`），但 **Streamlit Community Cloud 不会把 secrets
注入成环境变量** —— 它把 secrets 放进 `st.secrets`。官方文档原文：

> Community Cloud lets you save your secrets within your app's settings.
> When developing locally, you can use `st.secrets` in your code to read
> secrets from a `.streamlit/secrets.toml` file.

所以按现状部署，**「风险研判」这一段 AI 摘要会静默缺失**（页面不报错，
只是没有那一段），排查起来很费时间。

> 好消息：项目本身做了优雅降级 —— `summarize_risks()` 在无 Key 时返回 `None`，
> 数值计算与规则判定完全不受影响。所以**部署不会失败**，只是少了 AI 那段。

### 修复

**用 `deploy/config.py.streamlit-cloud` 覆盖 `diligence/config.py`** ——
该文件已按下面内容写好，并在三种环境下实测通过（见本节末尾）。

```python
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
```

**实测记录**（三种环境都验证过）：

| 场景 | `llm_available()` | 读取结果 |
|---|---|---|
| 云端：`st.secrets` 有 key | `True` | `sk-from-secrets` |
| 本地：无 streamlit，走环境变量 | `True` | `sk-from-env` |
| 都没有 | `False` | 优雅降级，不抛异常 |

改完后 `from diligence.pipeline import run_diligence` 仍正常导入，样例数据
`['risky', 'healthy']` 可读。

> 顺带一提：改动**不依赖** `python-dotenv` —— 缺这个包时会静默跳过，
> 与原项目「纯规则模式允许不装 dotenv」的降级设计保持一致。

### 部署时填 secrets 的内容

在 Advanced settings 的 Secrets 框里粘贴（TOML 格式）：

```toml
DEEPSEEK_API_KEY = "sk-你的真实key"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
```

> 不填也能部署，页面照常出指标与风险清单，只是「风险研判」为空。

---

## 四、部署步骤（约 5 分钟）

### 步骤 1：登录

打开 <https://share.streamlit.io>，用 **GitHub 账号**登录并授权。

### 步骤 2：创建应用

点右上角 **Create app** → 选 **Deploy a public app from GitHub**，然后填：

| 字段 | 填什么 |
|---|---|
| Repository | `sunhao33/mingjian-due-diligence` |
| Branch | `master` |
| Main file path | `app.py` |
| App URL | 自定义子域名，例如 `mingjian-due-diligence` |

> **App URL 就是最终的公网地址**，形如
> `https://mingjian-due-diligence.streamlit.app`
> 这个名字会填进参赛信息表的「公网地址」栏，想好再定。

### 步骤 3：填 secrets（可选）

点 **Advanced settings** → 在 **Secrets** 框里粘贴第三节的 TOML 内容。

### 步骤 4：部署

点 **Deploy**。首次构建会按 `requirements.txt` 安装依赖，通常 2–5 分钟。
构建日志在页面上实时可见。

### 步骤 5：验证

构建完成后逐项确认：

- [ ] 页面能打开，标题显示「明鉴 · 企业财务尽调与风险研判 Agent」
- [ ] 侧栏能选内置样例（risky / healthy），点「开始尽调」出报告
- [ ] 未上传 PDF 时点分析，出现「请先上传财报 PDF」的提示（说明交互正常）
- [ ] 若配了 Key：报告里「风险研判」有一段 AI 生成的文字
- [ ] **用手机 4G（关掉 WiFi）再打开一次** —— 这是唯一能证明评委也能访问的方法

---

## 五、免费额度与限制（如实说明）

| 项目 | 说明 |
|---|---|
| 费用 | 免费 |
| 睡眠 | 闲置一段时间后应用休眠；**下次访问会自动唤醒**，首次打开要等十几秒 |
| 资源 | 社区版共享资源，不适合高并发或大计算量 |
| 存储 | 容器内的文件**重启即丢**，不能当数据库用 |
| 上传文件 | 处理完即弃，不会持久保存（对尽调场景够用） |

**应对睡眠问题的做法**：录演示视频或答辩前，**先自己打开一次**把应用唤醒，
避免评委第一次访问时等待过久。

---

## 六、关于「本地版本」与「远程仓库」不一致

排查时发现的现状，需要团队内部确认，**不属于部署步骤**：

| | 本地副本 | GitHub 远程 |
|---|---|---|
| 分支 | `main` | `master` |
| 提交 | 9 次（最新 10-06） | 4 次（最新 09-29） |
| 历史 | **与远程无共同祖先**（两边独立初始化） | 同左 |
| 独有模块 | `agent` / `areport` / `html_report` / `locate` / `normalize` / `parse_lines` / `validate` | — |
| 独有功能 | 按股票代码自动获取年报、自包含 HTML 报告、公网部署脚本 | 仓库美化、统一免责声明 |

也就是说：**本地版本功能更多，远程版本是较早的一份**。

**这次部署用的是远程版本**（Streamlit Cloud 从 GitHub 拉取），所以线上会是
功能较少的那一版。如果要把本地的功能也上线，需要先合并两边历史，两种做法：

- **做法一（保守）**：把本地功能模块挑成补丁，提交到远程 `master` 上，
  保留远程的历史与文案提交
- **做法二（彻底）**：用本地版本覆盖远程历史再推上去，但**会丢掉队友那 4 次提交**，
  需要先跟队友确认

> 这一步涉及别人的代码历史，**建议两人一起决定后再动**。

---

## 七、附：检查清单

部署前：

- [ ] 确认要部署的是哪一版（远程 `master` 还是合并后的版本）
- [ ] 若用本地功能版，先确认 `.env` 没有被提交（`git ls-files | findstr .env`）
- [ ] `requirements.txt` 在仓库根目录

部署后：

- [ ] 公网地址记下来，填进参赛信息表
- [ ] 手机 4G 实测可访问
- [ ] 样例与上传两条路径都跑一遍
- [ ] 配了 Key 的话确认 AI 摘要有输出
- [ ] 把地址同步给队友与指导老师

---

*本文基于 2026-10-07 的仓库状态与实际核对结果编写。官方文档：*
*<https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app>*
