# 接入你的 agent

官方资料核对日期：2026-10-05。STU MCP 运行在学生自己的电脑，采用本地 stdio MCP；另外提供本地命令与可导入的 Skill。账号仍按学校来源独立管理，与 agent 客户端解耦。

## 支持范围

Codex、Claude Code、Cursor 是优先维护的核心适配；`generic` 是其他本地 stdio 客户端的通用导出。WorkBuddy、ZCode、Grok Build、DeepSeek Harness 保留为额外适配；豆包工作与 `generic-cli` 属于 Skill 候选方式。当前验证覆盖配置合并、导出命令实际执行和 MCP 握手，没有把这些结果等同于任何客户端应用内的完整验收。客户端或配置版本变化时，额外适配可能需要跟进；不确定时优先通用导出。

| 客户端 | 接入命令 | 本版本行为 |
| --- | --- | --- |
| Codex | `stu-mcp connect codex --apply` | 合并当前 `CODEX_HOME/config.toml`，默认 `~/.codex/config.toml` |
| Claude Code | `stu-mcp connect claude-code --apply` | 合并 `~/.claude.json` |
| Cursor | `stu-mcp connect cursor --apply` | 合并 `~/.cursor/mcp.json` |
| WorkBuddy | `stu-mcp connect workbuddy --apply` | 合并 `~/.workbuddy/mcp.json` 的 `mcpServers` |
| ZCode | `stu-mcp connect zcode --apply` | 合并 `~/.zcode/cli/config.json` 的 `mcp.servers`，保留原来有效的 `.agents` 服务 |
| Grok Build | `stu-mcp connect grok-build --apply` | 合并当前 `GROK_HOME/config.toml`，默认 `~/.grok/config.toml` |
| DeepSeek Harness 桌面端 | `stu-mcp connect deepseek-harness --apply` | 合并 `DSH_HOME/profiles/desktop/cordis.patch.yml`，默认 `~/.dsh/profiles/desktop/cordis.patch.yml` |
| 豆包工作 | `stu-mcp connect doubao-work --apply` | 生成本机 Skill ZIP，需导入技能并验证本机命令权限；未配置原生 MCP |
| 其他本地 MCP 客户端 | `stu-mcp connect generic` | 导出 stdio JSON，不猜配置路径 |
| 其他可执行本地命令的 agent | `stu-mcp connect generic-cli --apply` | 生成同一份本机 Skill ZIP |

只配置用户当前使用的客户端。省略 `--apply` 只预览。`stu-mcp clients` 返回所有方式、检测结果和官方资料；检测到配置目录不表示工具已加载。

启动项使用 STU MCP 安装环境的绝对 Python 路径，不含账密。保留其他服务、客户端设置及用户为 STU MCP 配置的额外选项，不擅自开启被用户停用的服务。写入前检查结构并备份，相同配置重复接入不重写。损坏配置、重复键、同名冲突与检测到的并发变化都会停止。`--replace` 仅在用户明确决定替换同名服务后使用；复杂 Cordis 覆盖项仍需在客户端检查。备份可能含其他工具的密钥，不展示或上传。

配置保存返回 `verification: configuration_only`。重新加载 / 重启并启用后，从当前 agent 发现并调用 `get_capabilities` 才算连接验证完成。

Python 启动路径必须保留 uv 虚拟环境的入口，即使它是符号链接，也不能解析成底层 Python。升级修复后重新执行对应的 `connect ... --apply`，会备份并更新已有 STU MCP 启动项，保留用户的其他设置。导出的 JSON 或 Skill ZIP 需要重新生成并替换客户端内的旧副本。

## WorkBuddy

[官方 MCP 指南](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide) 给出用户与项目路径及界面入口；[官方开放平台说明](https://open.workbuddy.cn/docs/connector) 确认 stdio 的 `type`、`command` 和 `args` 结构。

本版本使用用户级配置。保存后在 WorkBuddy 插件 / MCP 服务器里确认 STU MCP 并完成客户端要求的启用与授权，不替用户修改信任开关。

## ZCode

[官方 MCP 文档](https://www.zcode.network/cn/docs/mcp-services/) 区分用户级 `.zcode/cli/config.json` 与项目级 `.zcode/config.json`。

同一作用域存在原生 MCP 时，ZCode 会整体跳过 `.agents/mcp.json`。在原生配置尚无服务时，适配器把原来有效的用户级 `.agents` 服务一起合并到原生配置，保留其启用状态与环境变量，不改写 `.agents` 文件。结果只报告保留的服务数量，不输出配置。已有原生服务时，不重新激活已被忽略的回退服务。

保存后在设置 → MCP 服务器确认已启用。本版本不自动写入项目配置。

## Grok Build

这里指 xAI 官方 Grok Build。[官方 MCP 说明](https://docs.x.ai/build/features/mcp-servers) 使用 TOML 的 `mcp_servers`；[官方设置说明](https://docs.x.ai/build/settings) 给出 `GROK_HOME`。保存后使用 `/mcps` 检查并刷新，或重启。不配置 Grok 模型账户或修改模型设置。

## DeepSeek Harness 桌面端

依据 [Desktop 官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)、[profile / patch 官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/app-boot/README.zh.md) 和 [MCP 客户端官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.zh.md)，每个服务器作为 Cordis 插件条目插入桌面 profile，配置 `serverName`、`transport: stdio`、`command` 与 `args`。

先安装并打开一次桌面端。缺少 profile 清单时返回 `client_initialization_required`，不代建目录或安装另一份 CLI runtime。CLI 的 `web` 等 profile 不作为桌面配置目标。

只写桌面 patch 文件，保留注释与自定义 YAML 标签；`!!js` 等表达式不在安装器中执行。更高优先级的 `DSH_HOME/cordis.patch.yml` 已有同名服务时报告冲突。依赖清单、包选择和全局 patch 不变。退出并重开桌面端后验证工具发现；热重载是否即时生效取决于当前 profile。

## 豆包工作与通用 Skill

[飞书官方产品说明](https://www.feishu.cn/content/article/7677519271848610746) 确认可以创建、对话式安装和导入本地自定义技能，并能在授权范围内操作电脑与调用工具。它也提及自定义连接器；已查到的官方公开资料不足以确认本地 MCP 配置格式、stdio 支持和自动注册接口，本版本不猜测这些格式。

提供 **CLI + Skill 候选接入**：运行 `stu-mcp connect doubao-work --apply` 生成 `stu-campus.zip`，在豆包工作的技能入口导入。使用本地电脑环境，先执行版本和状态命令确认它确实能访问本机安装。技能导入与调用权限依赖当前客户端，尚未用真实豆包工作验收，不报告成原生 MCP 已连接。

ZIP 只有 `stu-campus/SKILL.md` 和 `stu-campus/runtime.json`；后者只含本机启动程序与参数，不含登录数据。无法执行时报告限制，不上传会话；云端或虚拟电脑不能代替用户电脑的安装与系统密钥库。包在 STU MCP 数据目录的 `exports`，可直接删除；导入后的技能在客户端移除。

Skill 覆盖通知正文 / 附件、成绩统计、课程 / 作业 / 日程、狐友公开讨论、服务入口与本机资料 / 待办，使用同一套数据、来源限制与加密存储，由当前 agent 分析。

## 当前验收状态

已用隔离目录验证配置合并、幂等、备份、冲突、ZCode 回退保留、Cordis 标签保留与 Skill 导出，并验证 STU MCP 的真实 stdio 协议与本地设置页。未逐一安装并登录新增客户端做端到端验收。学校真实账号的验收范围仍见 [验证记录](verification.md)。
