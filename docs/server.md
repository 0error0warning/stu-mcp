# 个人服务器与远程接入（开发中）

本页对应开发分支，尚未随 v0.5.0 发布。桌面用户仍直接使用 stdio；服务器运行同一个包、同一套 38 项工具，通过标准 Streamable HTTP 接入。服务器无需安装 agent，也不调用模型。Hermes 私有 `school_hub` 不受本次改造影响。

## 选择运行方式

| 使用方式 | 运行位置 | 接入 |
| --- | --- | --- |
| 桌面 agent 使用本机功能 | 自己电脑 | `stu-mcp serve`，原 `connect CLIENT` 不变 |
| 服务器上的 agent | 同一服务器 | stdio，或复用自己的 HTTP 实例 |
| 多台设备使用同一账号的数据 | 个人服务器 | Streamable HTTP，通过 SSH 转发或 Tailscale Serve |

第一版是一人一个实例、一个服务进程。多个客户端共享该人的账号、缓存和草稿；不同人必须使用独立实例、数据目录与密钥。进程内报修草稿不跨重启恢复，已发送结果未知时仍只能只读核查。

## 最小启动

从已检出的开发版本安装；下列命令在**宿主终端**执行，不把密钥内容交给 agent。以 Linux 单用户服务为例，先选服务专用账号，再始终用这个账号初始化和运行：

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

## 按已有认证路线登录

`STU_MCP_INTERACTION=disabled` 只禁用现有人工浏览器流程，不阻止公开查询、已有会话读取、对分易回调或 WebVPN 无头自动重登。能力以 `get_capabilities.hosting.login_flows` 为准，`interaction.available` 只说明人工浏览器的显示前提，不代表全部认证功能不可用。各模块调用链见[认证基线](authentication.md)。

### 对分易：原微信回调

在宿主的人工终端执行，保持同一个运行账号、数据目录和主密钥配置：

```sh
stu-mcp login duifene
```

命令提供已有固定微信授权地址，由本人在微信完成授权，再在**隐藏输入**中粘贴返回链接。程序复用同一个对分易后台和原 `/api/connect → P.aspx` 交换，不创建另一套 Controller、不新增官网扫码协议。非 TTY 或不能隐藏输入时拒绝；不接受回调命令参数、环境变量或管道，也不能把链接发进聊天。

回调仅发送一次；CLI 未收到可信后台回执时返回 `unknown` 并只读检查状态，不重发。上游交换或课程读取失败仍沿用原后台的回滚与失败响应，不能把 `rejected` 一律理解为账号被拒绝。旧会话仍有效也不能证明新回调成功。命令不调用选课或 start、不新建监听计划；后台课程选择回显和原已授权持续计划恢复均沿用原规则，结果显示 `monitoring` / `resume_enabled`。普通 MCP 退出不关闭该后台。

### WebVPN：配置原有自动重登

```sh
stu-mcp webvpn-auto configure
stu-mcp webvpn-auto status
stu-mcp webvpn-auto remove
```

`configure` 是明确启用按需自动重登，要求人工 TTY，账号、密码、已绑定 TOTP 密钥都隐藏输入，并复用设置页已有的配置和加密存储。保存会断开原 WebVPN 会话、清理旧 OA 缓存；不在配置时发起认证。`status` 只返回开关/失败/冷却，不读取或显示凭据；`remove` 沿用原移除逻辑。特殊密钥编码可使用 `configure --encoding base32|base64|hex`，密钥本身不在参数里。

仅受保护 OA 读取需要时才调用已有 `headless=True` 登录，实际读通目标资源后保存会话。它不需要 DISPLAY；首次令牌绑定、学校图片码 `randCode` 或其他人工挑战会暂停，不承诺全自动解决。没有绑定密钥时，不能用当前六位动态码冒充长期配置。

### 仍需人工浏览器的来源

教务、MySTU、雨课堂首次登录，以及报修独立临时认证，当前仍沿用原人工浏览器，没有通过这次部署整理变成全 CLI。桌面 `stu-mcp setup`、原 `login` 和报修工具保持原行为；已有有效会话的查询本身无需显示。雨课堂匿名无头发码的调查不等于项目已经接入这套认证。

无显示的宿主遇到这些操作会明确返回 `interaction_unavailable`，不在后台等待一个用户看不到的登录窗口。不要通过导出 cookies 或改认证域绕过。可选设置页仍只绑定回环，`--port` 和私有端口转发保持可用，但转发设置页不会让服务器拥有显示能力。兼容的 `virtual-display` 配置值只检查操作者已有 DISPLAY，项目不启动显示服务，也不提供默认桌面部署栈。

[容器模板](server-container.md)现在只运行 MCP、保留无头 Chromium；没有 noVNC、VNC、桌面密码或设置页桥接。需要对分易网页时，可在宿主运行 `stu-checkin --port 8767 --no-browser`，独立转发其回环端口；CLI 回调不需要这一步。

## 网络与验证范围

客户端到 MCP、MCP 到学校是两段连接。Tailscale/SSH 只解决前者；服务器必须自己拥有学校 DNS 和合法校园访问路径。学校的校内地址不会因你电脑在校园而自动对服务器可达。`location_hint` 描述 **MCP 宿主**接入位置；不知道就保留 `unknown`。

`get_capabilities` 的 `hosting`、`execution` 说明实例角色、交互前提和存储后端选择，不假装已经验证后端可用。单项/批量网络结果的 `execution.scope=mcp_host` 和原核查时间一起阅读；缓存换实例标签不重做网络检查。诊断不会改 DNS、代理、TUN、hosts 或切换无线网络，业务站与 SSO 分开处理。

验证覆盖回环 HTTP 的真实 SDK 握手、两个客户端共用草稿、断开连接后的生命周期、错误鉴权、Host/Origin、请求大小限制、外置密钥合成读写及原 stdio 接口。CLI 回调/自动重登配置使用合成账号和回环后台验证；Docker 构建、真实账号认证、Tailscale 端到端及学校业务另列验收，不能由单元测试代替。公开 OAuth、多租户、自动账号迁移和跨机文件下载不在本版能力内。
