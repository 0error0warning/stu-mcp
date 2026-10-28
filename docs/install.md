# 给 agent 的安装操作说明

本页对应 v0.7.2 学生预览版。本人可选择浏览器设置页或完整 CLI，两者共用 HTTP 认证核心；本机 stdio 与个人服务器私有 HTTP 共用同一包。服务器接入见[服务器说明](server.md)，各来源的人工步骤和成功证明见[认证说明](authentication.md)。旧版行为保留在历史发行记录，不套用到新版。

用户复制安装 prompt 后，可以直接完成下列安装、诊断和接入步骤。只配置用户当前使用的客户端，不默认给所有已安装客户端写配置。

## 1. 环境与发行包

使用 `https://github.com/0error0warning/stu-mcp` 的 `v0.7.2` 学生预览版。[发行页](https://github.com/0error0warning/stu-mcp/releases/tag/v0.7.2) 提供 wheel、源码包与 SHA256 校验文件。不要安装未知 PyPI 同名包；当前未发布到 PyPI。

检查 `uv`。缺少时参考 [uv 官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)，使用官方安装器或系统已有的软件包管理器。优先用户目录安装；不需要管理员权限、不改全局 Python、不修改其他项目依赖。若终端还未刷新 PATH，使用安装好的 `uv` 绝对路径。

```sh
uv tool install --python 3.12 https://github.com/0error0warning/stu-mcp/releases/download/v0.7.2/stu_mcp-0.7.2-py3-none-any.whl
```

Python 3.12 缺失时，uv 可以按自己的受管理 Python 流程准备。安装后找到 `stu-mcp` 的用户级可执行文件；如果 PATH 未刷新，使用绝对路径执行接下来的命令。不要为了“修复安装”删除用户已有工具或配置。

已有 STU MCP 时先检查 `stu-mcp --version`。v0.6.1 起可运行 `stu-mcp update`，完整行为见[更新说明](updates.md)。旧版还没有此命令，首次升级按下一节安装明确版本。

### 从旧版升级

1. 先完成或关闭尚未发送的报修草稿；提交结果未知时先只读查单。停止同一安装的签到后台。手动安装前还须关闭旧设置页并让旧 MCP 宿主进程退出：stdio 在客户端禁用或关闭该 MCP，HTTP 停止宿主 MCP 服务；不能仅关闭网页或断开 HTTP 客户端。
2. v0.6.0 及更旧版本需在上面的安装命令加入 `--force`，安装明确的 `v0.7.2` wheel，且仅在步骤 1 的旧进程已退出后执行。v0.6.1 及以后正常使用 `stu-mcp update`，不用 `--force`；若 v0.6.1 的更新检查受 GitHub 匿名 API 限流影响，按上述手动方式安装当前 wheel。不要删除 STU MCP 或对分易用户数据目录，也不要清空客户端配置或更换密钥库后端。
3. 运行 `stu-mcp --version` 确认已安装版本。stdio 接入重新加载 MCP，使客户端启动新进程；私有 HTTP 接入须在宿主重启 MCP 服务，仅重连客户端无效。随后调用 `get_capabilities` 核实当前连接的运行版本。手动重建安装环境或启动路径改变时，重新执行当前客户端的 `stu-mcp connect CLIENT --apply`。
4. 需要设置页时重新运行 `stu-mcp setup`。升级保留用户数据；缓存仍遵守当前解析契约，会话可能已过期，不能保证所有来源立即可读。WebVPN 自动重登仍由本人主动配置。
5. 使用通用 JSON 或技能接入时，按需重新导出并替换客户端中的旧副本；课表技能使用 `stu-mcp skill-export --skill stu-timetable-export --apply`。资源中的 `runtime.json` 是本机 Python 路径，换机器或重建安装环境后需重新生成。ZIP 不会自动安装技能或注册 MCP。对分易用户可重新打开网页，核对登录和已选课程，再按需要恢复监听。

配置写入前会备份并保留其他设置；同名冲突按下一节处理。验证失败时保留现有用户数据，分别报告安装、客户端加载和来源读取结果，不通过删配置或清缓存掩盖问题。

从 v0.5.0 升级默认不需要重新安装 Playwright 或 Chromium，也不需要卸载已有浏览器。新版学校认证使用 HTTP；只有明确选择浏览器兼容或离线 PNG 渲染时才需相应可选依赖。升级后不能把旧浏览器后台或旧 MCP 进程当作已经加载新版。

## 2. 连接当前客户端

`v0.7.2` 包含 51 项 MCP 工具：保留本人理论课表及两项一卡通查询，新增向维护者提交脱敏反馈的 report_feedback，保留默认 HTTP 认证、个人服务器接入和更新入口。各项验证边界见[验证索引](verification.md)，对分易用法见[后台说明](checkin.md)。从源码构建时，在明确版本或 revision 的仓库根目录运行 `uv build`，再安装对应 wheel，不把分支名当作可复现版本。

先运行 `stu-mcp clients`，按当前客户端选择 `stu-mcp connect CLIENT --apply`。自动合并配置支持 `codex`、`claude-code`、`cursor`、`workbuddy`、`zcode`、`grok-build` 和 `deepseek-harness`。官方路径、特殊合并规则和验收状态见 [客户端适配说明](clients.md)。程序负责保留其他设置、备份和生成不含凭据的启动项，不输出完整已有配置。

使用绝对 Python 启动路径，避免桌面客户端的 PATH 与终端不同。DeepSeek Harness 需先安装并打开一次桌面端，再写它的桌面 profile；没有初始化时报告该步骤，不另建 CLI profile。

豆包工作使用 `stu-mcp connect doubao-work --apply` 生成本机 Skill 包，再按客户端支持方式安装，并在本地电脑环境验证命令执行；其他可执行本机命令的 agent 可用 `generic-cli`。包生成成功不等于已导入、能执行命令或已配置原生 MCP，如实报告。可先用 CLI 验证公开查询，再由用户安装技能。不调用未公开的客户端内部接口或扫描账户数据库来自动注册。

客户端无法识别时，只询问用户正在使用哪个客户端。支持本地 stdio MCP 的其他客户端用 `stu-mcp connect generic`，按该客户端的官方配置方式添加。托管/网页客户端如果只支持远程 MCP，应报告限制，不能声称已经接通。

同名冲突会返回 `client_config_conflict`；保留现状，向用户展示冲突类型，只有明确选择替换后才使用 `--replace`。原配置备份位于用户 STU MCP 数据目录的 `backups`，包含原来的设置，不要上传。

保存后提醒用户重新加载/重启并启用；写入不等于已加载新工具。Skill 接入要执行版本 / 状态命令验证本机权限。

## 3. 验证公开功能

```sh
stu-mcp status
stu-mcp refresh public --limit 5
stu-mcp refresh oa --limit 5
```

公开功能无需系统密钥库、学生账号或模型 API key。`partial` 可能表示有界范围，检查 `limited`、`coverage` 和 `errors`；不要把缓存为空或连接错误写成“学校没有信息”。学校接口当前可达性随网络变化，需要时使用校园网络。

OA 先尝试匿名读取；若当前路径不可达或内容受限，可能返回 WebVPN 登录要求。这不表示安装失败，也不要求先配置全部学校账号。

客户端加载 MCP 后，调用 `get_capabilities`，再按用户目标刷新相应来源。公开查询验证失败时，保留成功安装和客户端配置，并准确报告网络/数据源限制。

## 4. 由本人完成登录

按用户需要配置账号，不要求所有来源依次登录。[配置与功能总表](campus-services.md#配置哪些登录当前能用哪些功能)列明支持范围；同属学校账号的未接入服务不会自动启用。让用户选择网页或 CLI，凭据由本人输入，不交给 agent，不导出浏览器资料。

### 本人浏览器中的设置页

本机用户可以让 agent 调用 `open_setup`，默认在自己的浏览器打开私密设置页；也可运行 `stu-mcp setup`。页面包含学校统一账号、雨课堂、对分易、WebVPN 和一卡通五类配置，在同一工作区输入账号、扫描官方二维码或粘贴原微信回调。学校账号一次输入，连接全部已接入业务。WebVPN 主表单支持可选令牌密钥，由程序生成动态码并验证登录。公开查询仍无需配置账号。

网页直接调用受保护的回环设置 API，与 CLI 共用 HTTP 认证、业务 proof 和保存屏障，不模拟终端，也不由 agent 操作浏览器收取凭据。普通学校密码只用于当次认证，各业务会话分别加密保存；WebVPN 长期自动重登需另行明确启用。显式取消或设置服务关闭会清理未完成交互；浏览器关页会尝试取消，未送达时任务按有效期失效。已完成登录及原有监听计划不会因此撤销。设置页私密地址不通过 MCP 返回；本机自动打开失败或无桌面时可使用下列完整 CLI。远程私密转发见[服务器说明](server.md)。

### 完整 CLI

在运行 MCP 的同一账号、数据目录和凭据后端中执行；源码开发时可在仓库根目录加 `uv run`。默认不安装服务端浏览器或桌面：

```sh
stu-mcp login school --allow-http-callback
stu-mcp login yuketang
stu-mcp login duifene
stu-mcp login webvpn
```

`login school` 默认处理教务、MySTU、报修，一次输入普通学校账号密码，各业务独立认证和保存；不保存密码。CLI 未允许教务 HTTP 回调且没有既有明确兼容设置时，该业务报告未完成。`--services mystu repair` 可限定业务，`--reauthenticate` 强制重登；原单业务命令继续可用。已有同账号会话仅按本地状态跳过，不证明学校当前接受。

`stu-mcp status`、MCP `get_capabilities` 和设置页共用 `capability_catalog`，展示配置组、对应功能和接入缺口。页面以「已配置」等状态汇总，仅未完成项目列原因；本地配置不代表在线可读。查看目录不会认证或启动后台。完整失败和并发退出规则见[认证说明](authentication.md#统一账号与网页配置)。

### 通用输入与兼容条件

CLI 的账号密码/动态码/回调只在本人 TTY 隐藏输入，不放参数、环境变量或管道。雨课堂在终端显示官方二维码，由本人手机确认；对分易使用原微信授权回调。私密设置页可完成相同交互，输入和二维码不进入聊天或 MCP。学校新挑战会明确停止，不自动转 Playwright 或重复提交。

CLI 教务参数允许本次官方 HTTP 票据回调，并随已核实会话保留对应读取路线，不改全局选项；`stu-mcp transport --jw-http on` 可明确开启持续兼容。网页的学校账号流程内部处理这条固定路线，不要求额外勾选技术选项。`stu-mcp transport --oa-http on` 仍是另一项默认关闭、须明确开启的 OA HTTP 8118 兼容。HTTP 可暴露该来源票据、会话或内容，不能扩展到其他地址或业务。普通学校/CAS 密码和动态码始终使用 HTTPS；一卡通使用独立查询密码和正常图片验证码，按其官方明文 HTTP 入口单独认证，不复用这些兼容开关，详见[一卡通说明](smartcard.md)。本人网页输入只经过受保护的本机回环设置 API，不开放公网收密页。

WebVPN 长期自动重登可选。设置页在主表单接收已绑定 TOTP 密钥/otpauth 地址，安全保存后直接用它生成动态码并验证登录；已有且启用的自动配置可直接复用。无密钥的手动登录仍可输入当前动态码。CLI `stu-mcp webvpn-auto configure` 继续只保存配置，随后 `login webvpn` 可复用它。状态不回填凭据，六位动态码不能替代密钥，不执行令牌绑定。受保护读取先复用会话，必要时一轮纯 HTTP 认证，拒绝/人工挑战暂停，网络错误不应触发反复重登。`logout webvpn` 移除该来源会话、OA缓存及自动凭据。

仅在本人明确选择兼容时才使用 Playwright；源码可 `uv sync --extra browser` 后运行 `uv run stu-mcp browser install`、`uv run stu-mcp login mystu --browser`。wheel 用户需要安装该版本的 `browser` extra；默认 Docker 不包含此依赖或显示服务。完整流程与成功证明统一见[认证说明](authentication.md)，服务器密钥初始化见[服务器部署](server.md)。

密钥库不可用时报告 `secure_storage_unavailable`，不安装明文 keyring 后端。服务器可由本人显式初始化外置私密主密钥后端；不读取项目 `.env`、私有 School Hub 配置或其他浏览器账户。公开功能无需账号和解密密钥。

登录返回会话保存不等于全部业务通过。随后按需刷新可采集来源，核实实际数据和范围；报修、对分易、外卖使用各自工具，不是通用 `refresh` 参数。综合报修 `r`、一网通办、上网认证和套餐管理目前没有相应 MCP 登录命令，列出入口不等于已适配其业务。失败保留已有配置并准确分类。更多账号、会话自然过期、容器内学校业务及跨机仍分别验收，见[验证索引](verification.md)。

## 5. 汇报

只报告版本、已配置的客户端、公开查询实际结果及按需登录步骤。升级后明确区分 stdio 重载 MCP 与 HTTP 重启宿主服务，并核对运行版本。不要输出认证信息。没有必要配置模型 API key、Hermes、云服务器、后台 AI 或任何微信私聊/群聊功能。
