# STU MCP

把汕头大学的通知、成绩、课程和作业，接入你常用的 agent。

STU MCP 在你的电脑运行，可为 Codex、Claude Code、Cursor、WorkBuddy、ZCode、Grok Build 和 DeepSeek Harness 桌面端生成接入配置；豆包工作与其他能执行本机命令的 agent 可使用导出的 Skill。无需 Hermes、自建服务器或模型 API key。公开功能可以直接使用，个人功能在需要时才登录。[接入方式与官方文档](docs/clients.md)

**0.2.0 是预览版本。** 新增客户端配置适配与 CLI + Skill 接入。公开网站与匿名 OA 已实际验证；新增客户端端到端接入、教务、MySTU、雨课堂的真实账号登录还需要学生参与验证。[验证范围](docs/verification.md)

## 复制这段话给你的 agent

适用于能在你电脑上执行安装和修改 MCP 配置的 agent。纯网页聊天或不支持本地 MCP 的托管服务，不能靠一段 prompt 自动安装到你的电脑。

```text
请在我的电脑安装并接入 STU MCP，仓库是 https://github.com/0error0warning/stu-mcp 。
请读取仓库 v0.2.0 的 README、docs/install.md 和 docs/clients.md，使用该版本的官方发行包；缺少 uv/Python 时按文档处理。
根据你当前所在的客户端，只配置 STU MCP，保留其他配置并备份。豆包工作用本机 Skill；需要我导入或授权时说明。不要展示或上传我现有配置里的密钥。
先验证无需登录的校园公开信息与 OA。需要成绩或课程时，再打开本地设置页让我在学校官方页面登录。
不要在对话里索要密码、cookie、token，不要配置模型 API key，不要接入微信私聊或群聊。
请报告安装和验证结果；如果客户端需要重新加载或重启，明确告诉我下一步。
```

完整的可复制版本：[安装 prompt](install-prompt.txt)。agent 的安装操作说明：[docs/install.md](docs/install.md)。

## 已实现的功能

| 来源 | 功能 | 需要配置什么 |
| --- | --- | --- |
| 学校公开网站 | 学校要闻、综合新闻、活动预告、学生处通知、校园服务入口 | 无需账号 |
| OA | 近期通知、正文、附件列表、PDF/文本附件文字 | 先匿名访问；受网络/访问限制时才尝试 WebVPN |
| 教务 | 本人成绩、学分加权统计、考试安排 | 单独启用旧 HTTP 接口兼容，在 HTTPS 统一认证页手动登录 |
| MySTU | 最新可用学期课程、作业/测验、Moodle/ELC 活动链接、个人日程 | 单独在学校登录页登录，ELC 可能还需完成一次登录 |
| 雨课堂 | 最新可用学期课程、作业/测验待办、课程公告 | 在雨课堂页面登录或扫码 |
| 本机 | 待办状态、可选学院/专业/年级/兴趣 | 无需模型密钥；资料完全可选 |

这是按需、有界的信息读取工具。刷新会报告获取范围、数量上限和失败部分；查询会报告缓存时间。空缓存不表示学校没有通知或作业。

不做微信私聊/群聊获取、聊天解密或历史扫描。首版也没有公众号采集、独立后台 AI、自动投递或自动提交作业。

## 手动安装

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，随后运行：

```sh
uv tool install --python 3.12 https://github.com/0error0warning/stu-mcp/releases/download/v0.2.0/stu_mcp-0.2.0-py3-none-any.whl
stu-mcp setup
```

设置页里选择客户端并保存接入。首次点击个人功能的“登录”会自动准备登录浏览器；也可预先运行 `stu-mcp browser install`。Python 和登录浏览器只需要首次准备。Linux 还需可用的 Secret Service/KWallet 和桌面环境；公开查询不依赖密钥库。

也可以在终端完成接入：

```sh
stu-mcp connect codex --apply
stu-mcp connect claude-code --apply
stu-mcp connect cursor --apply
stu-mcp connect workbuddy --apply
stu-mcp connect zcode --apply
stu-mcp connect grok-build --apply
stu-mcp connect deepseek-harness --apply
```

只运行自己需要的一条。省略 `--apply` 只预览；重复运行不产生重复配置。已存在其他同名服务时停止，检查后才使用 `--replace`。配置变更会保留原文件备份。保存后按客户端要求重新加载 MCP、重启或启用服务。

其他客户端：`stu-mcp connect generic` 输出不含凭据的标准 `mcpServers` 配置，选择本地 stdio 接入。

豆包工作：`stu-mcp connect doubao-work --apply` 生成可导入的本机 Skill；其他可执行本机命令的 agent 可用 `generic-cli`。设置页提供技能包下载。导入技能、允许本机执行后再验证；豆包工作的原生 MCP 接入尚未确认。[各客户端说明](docs/clients.md)

## 开始使用

告诉 agent：

- “看看最近的 OA 通知，找出竞赛和报名截止时间，读原文确认资格。”
- “先告诉我哪些功能无需登录；我只想启用成绩查询。”
- “刷新 MySTU，整理接下来两周的作业，区分学校提交状态和本地待办。”

终端也可以直接查询，适合没有 MCP 但可以执行命令的 agent：

```sh
stu-mcp status
stu-mcp refresh oa --limit 20
stu-mcp query notice --source oa --search 竞赛
stu-mcp login jw
stu-mcp refresh jw
stu-mcp query grade --source jw
```

CLI 别名为 `stu`。学校服务对校园网络、VPN、验证码或多因素认证的要求仍由学校决定。

## 凭据与隐私

账密只在学校页面输入，不保存在 STU MCP，也不需要发给 agent。登录会话、成绩和个人课程缓存加密保存，密钥放在系统密钥库中。密钥库不可用时停止对应个人功能，不退回明文。来源独立配置、独立退出；重新登录会清除该来源旧缓存，避免混入旧账号数据。

`stu-mcp logout jw`、`stu-mcp logout mystu`、`stu-mcp logout yuketang`、`stu-mcp logout webvpn` 移除相应会话及缓存。公开数据与可选兴趣资料不含登录凭据。数据默认位于当前用户的系统数据目录，开发时可用 `STU_MCP_HOME` 指定独立目录。

OA 的公开接口目前是 HTTP，程序仅匿名读取，绝不向该地址发送登录态。HTTPS 认证代理是否可用取决于学校环境，首版尚未完成真实 WebVPN 验证。

2026-10-05 实测教务 HTTPS 入口会跳转到 HTTP。本版提供独立的“使用学校现有教务 HTTP 接口”选项，默认关闭，需要成绩时在设置页开启。密码只在学校 HTTPS 统一认证页输入；开启后，教务会话和成绩会通过 HTTP 传输，保存到本机时仍加密。此例外只允许教务主机，不影响 MySTU、雨课堂或 WebVPN 的 HTTPS 要求。真实学生登录仍需验收。

同一系统账号下拥有完整执行权限的程序仍可能访问你的密钥库或进程内存；加密存储不等于防御已控制电脑的 agent。[详细安全边界](SECURITY.md)

## 开发与贡献

```sh
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run stu-mcp setup
uv build
```

测试只使用合成账号/页面，不包含真实成绩、登录态、私聊数据或部署密钥。CI 覆盖 Windows、macOS、Linux 和 Python 3.11–3.13。[架构](docs/architecture.md) · [验证清单](docs/verification.md) · [代码来源](docs/provenance.json)

MIT 许可。独立学生开源项目，非汕头大学官方服务。
