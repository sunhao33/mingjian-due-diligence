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

## 三、API Key 的读取方式（已修复，此处仅作记录）

> **状态：已修复并推送（提交 `4f6ad0b`）。部署时不需要再改代码。**

### 问题

`diligence/config.py` 原来只用 `os.getenv` 读配置：

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

所以按原样部署，**「风险研判」这一段 AI 摘要会静默缺失**（页面不报错，
只是没有那一段），排查起来很费时间。

> 项目本身做了优雅降级 —— `summarize_risks()` 在无 Key 时返回 `None`，
> 数值计算与规则判定完全不受影响。所以**部署不会失败**，只是少了 AI 那段。

### 修复内容

`_secret()` 先查 `st.secrets`，取不到再回落 `os.getenv`；`load_dotenv`
放进 `try/except`，缺 `python-dotenv` 时静默跳过 —— 与原项目
「纯规则模式允许不装 dotenv」的降级设计一致。

**实测记录**（三种环境分别用独立子进程测，避免相互污染）：

| 场景 | `llm_available()` | 读取结果 |
|---|---|---|
| 云端：`st.secrets` 有 key | `True` | `sk-cloud` |
| 本地：无 streamlit，走环境变量 | `True` | `sk-local` |
| 都没有（移走 `.env` 后测） | `False` | 优雅降级，`BASE_URL`/`MODEL` 落默认值 |

另确认 `pipeline` 正常导入、样例 `['risky', 'healthy']` 可读、
`run_diligence()` 离线模式跑通（返回 `(report, result)` 二元组）。

> `deploy/config.py.streamlit-cloud` 是该文件的副本，便于单独取用或回滚。

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

> ⚠️ **必须用 GitHub 账号登录**。如果之前用邮箱注册过 Streamlit 账号，
> 要改走 GitHub 授权 —— 否则工作台里看不到「Create app」，因为
> Community Cloud 是从 GitHub 仓库拉代码的。

### 步骤 2：点右上角 Create app

登录后进入工作台（页面顶部有 `My apps` / `My profile` / `Explore` 这些标签），
**右上角**有一个 `Create app` 按钮，点它。

> 工作台中间如果是「No apps to show in this workspace / Deploy one now」，
> 点那个 **Deploy one now** 也是一样的效果。

### 步骤 3：回答「Do you already have an app?」

会弹出一个询问，选 **`Yup, I have an app`**。
（另一条 `Nope, I don't have an app` 是给从模板新建的人用的，不走这条。）

> 这一步官方文档有写，但很容易漏 —— 漏了就会觉得"找不到该填的地方"。

### 步骤 4：填表单

表单长这样（字段名照抄官方）：

| 字段 | 填什么 |
|---|---|
| **Repository** | `sunhao33/mingjian-due-diligence` |
| **Branch** | `master` |
| **Main file path** | `app.py` |
| **App URL (optional)** | 自定义子域名，例如 `mingjian-due-diligence` |

- Repository 右侧有 `Paste GitHub URL`，也可以直接粘仓库地址。
- App URL 填好后下方会显示绿色的 **`Domain is available`**，说明这个名字没人占。
- 不填 App URL 也行，但系统会按
  `[用户名]-[仓库名]-[文件名]-[随机哈希]` 生成一串很长的地址，不好记也不好念。

> 官方说明：App URL 部署后仍可随时在 App settings 里修改。

### 步骤 5：填 secrets（可选）

点表单下方的 **`Advanced settings`** → 在 **Secrets** 框里粘贴第三节的
TOML 内容 → **Save**。

同一弹窗里还能选 **Python 版本**（默认 3.12）。

### 步骤 6：Deploy

点蓝色的 **`Deploy!`** 按钮。首次构建会按 `requirements.txt` 安装依赖，
通常 2–5 分钟。部署过程中右侧会显示日志（只有对该仓库有写权限的人能看）。

### 步骤 7：验证

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
