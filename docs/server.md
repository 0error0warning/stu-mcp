# 个人服务器与远程接入

本页对应 v0.7.0 学生预览版。桌面用户仍直接使用 stdio；服务器运行同一个包、同一套工具，通过标准 Streamable HTTP 接入。服务器无需安装 agent，也不调用模型。Hermes 私有 `school_hub` 不受本次改造影响。

统一账号 `login school`、配置分组能力目录和私密网页配置使用同一 HTTP 核心；完整 CLI 始终可用于无桌面服务器，不需要改远程接入架构。

## 选择运行方式

| 使用方式 | 运行位置 | 接入 |
| --- | --- | --- |
| 桌面 agent 使用本机功能 | 自己电脑 | `stu-mcp serve`，原 `connect CLIENT` 不变 |
| 服务器上的 agent | 同一服务器 | stdio，或复用自己的 HTTP 实例 |
| 多台设备使用同一账号的数据 | 个人服务器 | Streamable HTTP，通过 SSH 转发或 Tailscale Serve |

第一版是一人一个实例、一个服务进程。多个客户端共享该人的账号、缓存和草稿；不同人必须使用独立实例、数据目录与密钥。进程内报修草稿不跨重启恢复，已发送结果未知时仍只能只读核查。

## 最小启动

先按[安装说明](install.md)安装 v0.7.0；下列命令在**宿主终端**执行，不把密钥内容交给 agent。以 Linux 单用户服务为例，先选服务专用账号，再始终用这个账号初始化和运行：

```sh
export STU_MCP_HOME="$HOME/.local/share/stu-mcp"
export STU_CHECKIN_HOME="$HOME/.local/share/stu-checkin"
stu-mcp server-init "$HOME/.config/stu-mcp-secrets"
export STU_MCP_KEY_FILE="$HOME/.config/stu-mcp-secrets/master.key"
export STU_MCP_INTERACTION=disabled
stu-mcp serve --transport streamable-http \
  --auth-token-file "$HOME/.config/stu-mcp-secrets/http-token" \
  --name my-server
```

`server-init` 只在全新目录生成两个不同的随机文件，输出路径，不显示内容；已存在就拒绝覆盖。主密钥用于加密凭据，HTTP 令牌用于连接 MCP，不能互换。POSIX 文件须为运行账号所有且不向组/其他人开放（通常 0600、目录 0700）；Windows 使用账户 ACL，桌面仍推荐系统密钥库。服务不会自动生成、替换或降低密钥权限。

主密钥必须位于两个数据目录之外。数据目录分别保存自己的 `credentials.enc`，会话和个人缓存仍加密保存。主密钥与密文分开备份；主密钥丢失无法解密。更换 keyring/文件后端不会自动迁移已有登录，勿在原账户上随意切换。未设置 `STU_MCP_KEY_FILE` 时使用默认系统 keyring。

默认只监听 `127.0.0.1:8765`，MCP 地址为 `http://127.0.0.1:8765/mcp`。HTTP 即使在回环地址也必须提供独立 Bearer 令牌文件；私密文件内容不会进入 MCP 参数、结果、服务日志或生成的 agent 配置。修改令牌后重启实例才能生效。

## 从自己的设备连接

最小方案是在**客户端电脑**建立 SSH 转发：

```sh
ssh -N -L 8765:127.0.0.1:8765 user@server
```

客户端选择 Streamable HTTP，地址填 `http://127.0.0.1:8765/mcp`，并通过其本地安全配置/凭据界面提供 `Authorization: Bearer …`。令牌由本人通过安全渠道配置，不粘贴进聊天或仓库。当前 `connect CLIENT` 继续配置 stdio，不会把本机配置自动换成服务器，也不会读取令牌生成客户端配置。

另一种方案是 [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) 将私有 HTTPS 地址反向代理到服务器回环端口。先按 Tailscale 官方文档配置 Serve，再给 MCP 声明实际入口：

```sh
stu-mcp serve --transport streamable-http \
  --auth-token-file "$HOME/.config/stu-mcp-secrets/http-token" \
  --public-url https://your-node.your-tailnet.ts.net/mcp
```

代理需保留明确的外部 Host；该地址用于 Host/Origin 白名单，不是自动创建隧道。TLS 由代理终止，程序不信任任意转发头、不放开通配 Host/Origin。不要把设置页或桌面发布到 Funnel/公网。非回环监听只在操作者显式 `--host IP` 时开启，容器场景见[容器说明](server-container.md)。

私有预配置 Bearer 模式尚未实现 [MCP OAuth 授权发现](https://modelcontextprotocol.io/specification/latest/basic/authorization)。它适用于支持自定义 Bearer 的客户端；只接受 OAuth 的托管客户端目前不能直接接入。也不能假定云端 agent 能访问你电脑的 localhost 或 tailnet。标准传输与具体客户端实测分开判断，参见 [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/latest/basic/transports/streamable-http)。

## 在宿主终端登录

认证默认走纯 HTTP 和本人终端，不需要 DISPLAY、虚拟桌面或 Chromium。保持与 MCP 服务相同的运行账号、数据目录和密钥后端：

```sh
stu-mcp login mystu
stu-mcp login yuketang
stu-mcp login repair
stu-mcp login webvpn
stu-mcp login duifene
stu-mcp login jw --allow-http-callback
```

也可一次输入学校账号，为所选业务分别建立会话：

```sh
stu-mcp login school --services mystu repair
stu-mcp login school --services jw --allow-http-callback
stu-mcp login school --services mystu --reauthenticate
```

省略 `--services` 默认选择教务、MySTU、宿舍报修；不保存普通密码，各业务仍独立认证和加密存储。已保存的同账号会话仅按本地状态跳过，不能证明学校当前接受；`--reauthenticate` 强制重登所选业务。教务 HTTP 许可默认关闭，本次未选择且没有既有明确兼容设置时，该业务未完成而其他业务可继续。雨课堂、对分易、WebVPN 仍独立登录；`r` 综合报修等未接入服务不会因此启用。原单业务命令继续兼容。

账号、密码、动态码和回调均不放在参数、环境变量、stdin 管道或聊天中。雨课堂在终端显示官方二维码，由本人手机确认；对分易提供原微信授权地址，由本人完成授权并隐藏粘贴返回链接，复用原 worker，不改成官网 QR/SignalR 方案。

教务 `--allow-http-callback` 仅允许本次已知官方票据回调，不改变设置。需要持久兼容时，用 `stu-mcp transport --jw-http on`。OA 的 `stu-mcp transport --oa-http on` 是另一项独立选择，默认关闭；只允许已核验目录指定的官方 HTTP 8118 路由。HTTP 可能暴露该来源会话及内容，不能由 agent 自动开启。密码和 TOTP 始终只发 HTTPS 认证源。

WebVPN 长期自动重登可选，另行运行 `stu-mcp webvpn-auto configure`，隐藏输入已有绑定的 TOTP 密钥/otpauth 地址；`status/remove` 查看或移除配置。普通 `login webvpn` 也可输入当前动态码，不要求为单次登录保存长期密钥。自动认证只在受保护 OA 按需读取时触发，使用纯 HTTP；拒绝、绑定和人工挑战停止，不保活、不反复提交。

对分易 CLI 登录不选课、不调用 start、不创建监听计划。原已授权持续计划仍按后台账号与课程规则恢复，结果展示 `monitoring/resume_enabled`；回执未知只读检查，不重发。普通 MCP 退出不停止该 worker。

报修 `login repair` 建立独立加密会话，MCP 默认通过 HTTP 填写并展示实际完整表单，只有本轮用户明确确认后提交一次。本人终端也可使用 `repair drill`；具体字段、预览及回执规则统一见[报修流程](repair.md)。

本人也可在私密设置页直接输入或授权，网页与 CLI 共用 HTTP 核心，不让后台线程读取 TTY，也不模拟终端。需要旧 Playwright 兼容时，安装 `browser` extra 并明确选择 `login 来源 --browser`；该方式才需要服务端显示环境。项目不启动显示服务，HTTP 不自动回退浏览器。完整来源及存储契约见[认证说明](authentication.md)。

设置页按学校统一账号、雨课堂、对分易和 WebVPN 四类展示功能与汇总配置状态；学校账号一次连接全部已接入业务，已验证的教务回调由内部处理，不再显示业务选择或技术许可框。WebVPN 主表单可接收已有令牌密钥，保存后生成动态码验证登录；CLI 原有参数和命令保持兼容。普通学校密码只用于本次内存，认证输入和二维码不进入远程 MCP。`get_capabilities`、CLI `status` 与页面共用 `capability_catalog`，旧字段和 47 项工具保持兼容。本地配置、历史刷新与后台状态不是在线业务 proof；查看目录不登录或启动 worker。

本机 stdio 的 `open_setup` 默认自动打开本人的系统浏览器，私密地址不经 MCP 返回。无桌面服务器继续完整使用 CLI；本人需要私密链接时可用 `setup --no-browser`，网络转发另行选择，不在本次改造范围。设置页保持回环绑定及精确 Host/Origin 校验，页面令牌不进入聊天或 MCP 配置。取消只清理未完成的认证交互，不撤销已完成登录或停止既有已授权监听计划。

[默认容器](server-container.md)没有浏览器或桌面。若本人需要签到网页，可运行 `stu-checkin --port 8767 --no-browser` 并独立私有转发其回环端口；原回调 CLI 不需要此步骤。

## 更新服务器

以安装和运行服务的同一账号执行 `stu-mcp update`，或明确让 agent 调用 `update_self`。
这会更新 MCP **服务器**上的安装，客户端电脑不随之升级。先用 `stu-mcp update --check`
或 `check_updates` 可只查版本；默认没有定时任务。

升级前先停止同一安装的其他 MCP 实例和签到后台，处理当前报修流程。升级后，stdio 接入重新加载 MCP
以启动新进程；Streamable HTTP 必须在宿主重启 MCP 服务，再连接客户端。HTTP 重连本身不会重启宿主进程。
随后调用 `get_capabilities` 核对运行版本；签到后台按需重开，并核对其 `package_version`。
不会自动终止服务、热替换独立签到后台或清理密钥/数据。源码、Docker 和未知安装方式返回各自操作指引；
详见[更新说明](updates.md)和[容器更新](server-container.md#更新容器)。

## 网络与验证范围

客户端到 MCP、MCP 到学校是两段连接。Tailscale/SSH 只解决前者；服务器必须自己拥有学校 DNS 和合法校园访问路径。学校的校内地址不会因你电脑在校园而自动对服务器可达。`location_hint` 描述 **MCP 宿主**接入位置；不知道就保留 `unknown`。

`get_capabilities` 的 `hosting`、`execution` 说明实例角色、交互前提和存储后端选择，不假装已经验证后端可用。单项/批量网络结果的 `execution.scope=mcp_host` 和原核查时间一起阅读；缓存换实例标签不重做网络检查。诊断不会改 DNS、代理、TUN、hosts 或切换无线网络，业务站与 SSO 分开处理。

验证覆盖回环 HTTP 的真实 SDK 握手、两个客户端共用草稿、断开连接后的生命周期、错误鉴权、Host/Origin、请求大小限制、外置密钥合成读写及原 stdio 接口。HTTP 认证、加密保存、退出屏障及 CLI 有合成测试，正式适配器也已在当前账号验证特定学校业务；详情见本轮真人回执，不能推广到所有账号。CI 另有默认 Docker 镜像构建与离线启动检查；容器内学校认证、自然过期和 Tailscale 端到端仍需独立验收，最新范围见[验证索引](verification.md)。公开 OAuth、多租户、自动账号迁移和跨机文件下载不在本版能力内。
