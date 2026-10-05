# 给 agent 的安装操作说明

用户复制安装 prompt 后，可以直接完成下列安装、诊断和接入步骤。只配置用户当前使用的客户端，不默认给所有已安装客户端写配置。

## 1. 环境与发行包

使用 `https://github.com/0error0warning/stu-mcp` 的 `v0.1.0` 版本。[发行页](https://github.com/0error0warning/stu-mcp/releases/tag/v0.1.0) 包含 wheel、源码与 SHA256 校验文件。不要安装未知 PyPI 同名包；当前未发布到 PyPI。

检查 `uv`。缺少时参考 [uv 官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)，使用官方安装器或系统已有的软件包管理器。优先用户目录安装；不需要管理员权限、不改全局 Python、不修改其他项目依赖。若终端还未刷新 PATH，使用安装好的 `uv` 绝对路径。

```sh
uv tool install --python 3.12 https://github.com/0error0warning/stu-mcp/releases/download/v0.1.0/stu_mcp-0.1.0-py3-none-any.whl
```

Python 3.12 缺失时，uv 可以按自己的受管理 Python 流程准备。安装后找到 `stu-mcp` 的用户级可执行文件；如果 PATH 未刷新，使用绝对路径执行接下来的命令。不要为了“修复安装”删除用户已有工具或配置。

已有 STU MCP 时先检查 `stu-mcp --version`。升级要使用同一仓库的明确版本，确认发行包与校验值，不默认使用不受控的分支代码。

## 2. 连接当前客户端

使用 `stu-mcp connect codex --apply`、`stu-mcp connect claude-code --apply` 或 `stu-mcp connect cursor --apply`。程序负责保留其他设置、备份和生成不含凭据的启动项。不要让 agent 把整个已有配置输出到对话中。

程序为 Codex 写当前 `CODEX_HOME/config.toml`（默认 `~/.codex/config.toml`）；Claude Code 写 `~/.claude.json`；Cursor 写 `~/.cursor/mcp.json`。使用绝对 Python 启动路径，避免桌面客户端的 PATH 与终端不同。

客户端无法识别时，只询问用户正在使用哪个客户端。支持本地 stdio MCP 的其他客户端用 `stu-mcp connect generic`，按该客户端的官方配置方式添加。托管/网页客户端如果只支持远程 MCP，应报告限制，不能声称已经接通。

同名冲突会返回 `client_config_conflict`；保留现状，向用户展示冲突类型，只有明确选择替换后才使用 `--replace`。原配置备份位于用户 STU MCP 数据目录的 `backups`，包含原来的设置，不要上传。

保存后提醒用户重新加载/重启 MCP 客户端，并完成该客户端要求的启用步骤。配置写入不等于当前会话已经加载新工具。

## 3. 验证公开功能

```sh
stu-mcp status
stu-mcp refresh public --limit 5
stu-mcp refresh oa --limit 5
```

公开功能无需系统密钥库、学生账号或模型 API key。`partial` 可能表示有界范围，检查 `limited`、`coverage` 和 `errors`；不要把缓存为空或连接错误写成“学校没有信息”。学校接口当前可达性随网络变化，需要时使用校园网络。

客户端加载 MCP 后，调用 `get_capabilities`，再按用户目标刷新相应来源。公开查询验证失败时，保留成功安装和客户端配置，并准确报告网络/数据源限制。

## 4. 按需登录

设置页首次点击登录会按需准备浏览器。agent 也可以在用户需要个人功能时提前准备：

```sh
stu-mcp browser install
stu-mcp setup
```

也可以用 MCP `open_setup`。设置页或 CLI `stu-mcp login jw|mystu|yuketang|webvpn` 打开学校/雨课堂页面，用户自己操作。验证码、MFA 或二维码在官方页面处理。agent 不索要、不代填、不记录密码、cookie、token、验证码或 TOTP 密钥，不截图用户登录过程，不导出 storage-state。

需要教务成绩时，先让用户在设置页选择“使用学校现有教务 HTTP 接口”。该选项默认关闭，只兼容教务，开启后教务会话和成绩会经过 HTTP，密码仍在 HTTPS 统一认证页输入。不要让 agent 自动替用户改这个传输选项。

在有桌面的电脑上完成浏览器登录。Linux 安全密钥库未运行或被锁定时，向用户报告 `secure_storage_unavailable`，不要安装明文 keyring 后端作为替代。无账号功能仍能使用。

首版个人来源的真实登录尚未验收，学校页面也可能改变。报告本次实际成功的来源，不把适配器单元测试当作用户账号验证。账户切换/重新登录会清除此来源缓存，随后重新刷新。

## 5. 汇报

只报告版本、已配置的客户端、公开查询实际结果、需要用户完成的重新加载/按需登录。不要输出认证信息。没有必要配置模型 API key、Hermes、云服务器、后台 AI 或任何微信私聊/群聊功能。
