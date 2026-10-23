# 认证、会话与来源边界

本文描述当前 v0.6.2 学生预览版沿用的认证：默认认证为 **HTTP + 本人终端**，不启动服务端浏览器，不需要桌面或 Chromium。旧 v0.5.0 wheel 仍采用原登录方式，升级后须让宿主进程加载新版；stdio 重载 MCP，私有 HTTP 重启宿主服务。Hermes 私有 `school_hub` 与本仓库分开维护。

“HTTP”包括学校表单、HTML 解析、二维码等待和回调交换，不限于 JSON API。雨课堂仍需本人手机确认，对分易仍需本人完成原微信授权；无浏览器部署不免除人工授权或 MFA。源码实现、合成测试、真人认证、业务读取和目标部署是不同的验收层级。

## 入口与职责

| 边界 | 实现与责任 |
| --- | --- |
| 本人终端 | `terminal` 要求 stdin/stderr 均为 TTY，隐藏接收账号、密码、动态码或回调；不接受认证参数、环境变量、管道或 MCP 转发 |
| HTTP 认证 | `auth_http/transport` 负责直连、TLS、主机范围、请求/响应/时间预算及私密日志；`cas/yuketang/webvpn` 各自拥有平台协议与正向 proof |
| 会话编排 | `auth_http.login_http` 核对来源版本、调用适配器、收窄状态，最后经 `Vault` 加密保存并清理该来源旧缓存 |
| 浏览器兼容 | `auth.interactive_login` 由 `login --browser` 或设置页明确选择；Playwright 是可选依赖，不自动回退，不是默认部署前提 |
| 设置页 | 默认登录操作返回宿主 CLI 指引，不在后台线程索取终端密码；仍提供传输配置、可选 WebVPN 自动重登和显式浏览器兼容 |
| MCP | 所有工具共用相同服务，不接收认证凭据，不因 stdio/HTTP 改变来源范围 |
| 对分易 | CLI、网页和 MCP 复用唯一 `stu_checkin` worker，不各建一套 Controller、会话或监听状态 |

Streamable HTTP 的 Bearer 授权客户端访问 MCP，学校账号授权 MCP 宿主访问学校，两者不互换。远程连接不会给宿主自动增加校园 DNS 或网络路径，见[服务器部署](server.md)。

## 各来源默认流程

以下描述实现能力，不代表所有账号和业务已实测通过。

用户选择配置时先看[登录配置→当前功能、学校服务→接入缺口总表](campus-services.md)。本页仅解释背后的认证、会话和兼容条件；同属学校账号组的业务当前仍分别登录，未接入的服务不会因账号配置而自动出现。

业务来源与登录名不是一一对应：受保护 `oa` 使用 `login webvpn`；`jw`、`mystu`、`yuketang`、`repair`、`duifene` 使用各自同名登录命令。MySTU 下的 ELC / Campus 使用学校账号，分别核实业务会话，不要求另外准备两套账号。公开 OA 不必先登录 WebVPN。

OA 引导先说明[能读的内容与访问条件](verification/2026-10-22-oa-entry-boundaries.md)：原站和目标内容可匿名访问时，列表、正文及支持格式的附件不需要登录；原站列表读取失败时，当前实现才尝试 WebVPN 路径。WebVPN 需要可达、有效会话和实际可用的 OA 路由，单独登录门户不证明正文/附件可读。正文与附件按缓存的来源路径读取，未实现每篇直读失败后自动换路径。

协议备注：`/login/Login.jsp` 的路径名不表示必须登录；`login webvpn` 认证的是访问通道。页面另有员工 CAS，回调 `office.stu.edu.cn`，这条办公业务未适配，不改变公告工具的可读范围。原站地址不能证明 Chrome 是否经过 Clash/TUN；本轮匿名样本也不能推广为所有通知/附件免登录。

同属学校 SSO 的入口仍有独立业务和会话。综合报修 `r`、一网通办、套餐管理等入口的认证证据及尚未接入范围见[校园入口映射](campus-services.md)；不能把目录里的每个站点当成已有 MCP 登录适配器。

| 来源 | 默认认证与成功证明 | 状态和人工步骤 |
| --- | --- | --- |
| 公开网站、狐友、充电、网络诊断 | 固定范围匿名 HTTP/DNS 或本地计算 | 无学生账号，各自保持独立的访问与缓存政策 |
| 教务 | HTTPS CAS 单次密码提交 → 官方回调及 `LoginToXk` 桥接 → 可识别的 HTTPS 学生主页 | SSO、教务分用 Cookie jar；当前 HTTP 回调需明确兼容，成绩/考试从 HTTPS 发起 |
| MySTU / Moodle | HTTPS CAS → 身份 `id/username` 正向校验并匹配输入账号 → 课程契约 → 按课程来源分别引导 ELC / Campus | 独立 `mystu` 会话；某个 Moodle 初始化失败不会否认已核实的身份和课程会话，结果注明实例与安全状态码；引导成功也不等于全部课程活动/作业读取 |
| 雨课堂 | 发放官方二维码 → 本人手机确认 → 一次等待/会话交换 → 绑定状态 → 学生课程成功标记与逐行契约 | 二维码只显示于本人终端；未绑定、冲突身份、未知挑战停止，不执行绑定 |
| WebVPN | 官方普通 Web 初始化及最新 nonce/RSA → 单次密码 → 必要时已绑定 TOTP → 真实配置和资源目录 | 密码/动态码仅 HTTPS；门户目录与 OA 正文分别证明 |
| 桑浦山宿舍报修 | 独立 HTTPS CAS → 本人未筛选列表及明确空态/表格契约 | `repair` 独立加密会话；WebForms 草稿、确认和单次提交见[报修流程](repair.md) |
| 对分易 | 原微信 OAuth 回调 → 固定 `P.aspx` 交换 → 实际课程验证 | 本人从微信复制回调到隐藏终端或宿主网页；不接入另一条官网 QR/SignalR 登录路线 |

## CLI 登录与兼容选择

在运行 MCP 的主机、同一运行账号和数据目录中执行；敏感输入不写在命令中：

```sh
stu-mcp login mystu
stu-mcp login yuketang
stu-mcp login repair
stu-mcp login webvpn
stu-mcp login duifene
stu-mcp login jw --allow-http-callback
```

普通来源的本次认证输入只在内存使用，会话加密保存。雨课堂手机授权不赋予读取微信消息的能力。对分易未获得可信后台回执时只读检查，不重发，也不拿旧登录态冒充本轮成功。

教务 `--allow-http-callback` 只授权本次已知 HTTP 票据回调，不更改持久设置。本人可分别开启持续兼容：

```sh
stu-mcp transport
stu-mcp transport --jw-http on
stu-mcp transport --oa-http on
```

两个开关默认关闭、互相独立，用 `off` 关闭。OA 兼容仅用于认证后目录核验到的固定官方路由，当前观察为 `http://oa-stu-edu-cn.webvpn.stu.edu.cn:8118`。启用意味着 OA 会话可能经明文 HTTP 传输，不能由 agent 默默开启，也不能借用教务的一次许可。它不关闭 HTTPS 校验，不改代理、DNS、路由或学校资源类型。

确需原浏览器兼容时，源码安装先准备可选依赖，再明确选择：

```sh
uv sync --extra browser
uv run stu-mcp browser install
uv run stu-mcp login mystu --browser
```

该方式需要本人可操作的显示环境，不启动虚拟桌面。安装包同样须安装相应版本的 `browser` extra；仅安装 Chromium 不能代替 Python 依赖。HTTP 遇到未知挑战会停止，不自动切换浏览器、猜验证码、绑定令牌或反复提交。

## 保存、退出与失败

各来源使用独立的新 HTTP 客户端及 Cookie jar，不因共用 SSO 就导入其他来源 cookies。雨课堂专用认证头只用于固定雨课堂 HTTPS 来源；WebVPN 路由元数据只留在对应加密会话。不能导入浏览器资料、导出明文 storage-state，或把 cookie 存在当作成功。

MySTU 存在已核验的 `_UT_` 业务桥接；实现仅允许将此必要父域令牌收窄给精确的 HTTPS MySTU/repair 目标，且各来源真实验收分别记录。不将 CASTGC 或 SSO host-only cookie 复制到业务 jar，不用于教务 HTTP 客户端。此显式契约不是批量共享 SSO 会话或跟随任意回调的许可。

报修站点会为不同页面重新申请 CAS 票据，因此仅此来源把独立 `repair_sso_state` 随报修会话一起加密保存。中央 Cookie 始终留在独立的 SSO jar，只 GET 学校固定认证地址；service 必须精确等于本次列表、表单或已核对 ID 的详情地址。回调只能回到同一页面，最多 8 跳，不重发密码，不把临时 ticket 作为稳定链接。正式 POST 不跟随此认证链。

适配器只返回内存 Candidate。编排层在协议检查点及保存前核对来源 `.generation` 与会话指纹，来源锁内再次检查后才清旧缓存和保存。退出或另一账号登录使旧在途结果失效。取消、拒绝、结构变化和未知结果不覆盖旧会话或清缓存。

密码提交不自动重发。CAS 票据、HTTP 200、主页 URL 或初始化 session 不能代替业务 proof。网络、TLS、权限、限流、结构改变与认证失效分别处理。`Vault.status` 只是本地加密会话及过期时间检查，不代表学校当前在线状态；实际查询仍校验来源响应。

`logout` 清指定来源会话和缓存；WebVPN 同时移除自动重登凭据，报修退出会使旧预览会话失效。对分易另有后台退出与独立加密 `state.enc`，普通 MCP 关闭不停止已授权 worker。

## WebVPN 按需重登

`login webvpn` 可隐藏输入账号、密码及当前动态码；长期自动重登另需本人明确启用：

```sh
stu-mcp webvpn-auto configure
stu-mcp webvpn-auto status
stu-mcp webvpn-auto remove
```

`configure` 接收已有绑定的 TOTP 密钥或完整 `otpauth://totp/`，支持明确编码。当前六位码不能代替长期密钥；配置本身不执行学校认证或绑定。凭据进入批准的安全后端，`status` 不读取凭据值。

受保护 OA 先复用会话，确需认证时才进行一轮纯 HTTP 密码/TOTP，每阶段一次，进程间串行并有失败冷却。拒绝、首次绑定、图片码和其他人工挑战暂停。新认证和实际 OA 内容分别验证；资源不可达或 TLS 故障不能变成重复重登的理由，不运行定时保活。

## 对分易既有授权

CLI 校验固定 HTTPS 回调及唯一 code，再发现并核验现有 worker，至多发送一次 `/api/connect`，不访问任意输入 URL。后台交换或课程验证失败沿用原回滚；`rejected` 不等于密码错误。CLI 未获可信回执为 `unknown`，不推断后台已经回滚。

登录不选课、不调用 start、不创建计划。此前已授权持续计划仍按账号、课程和启用状态恢复，并输出 `monitoring/resume_enabled`；换账号不继承旧计划。课程选择回显不是新增监听授权，登录成功也不是课堂签到成功。

## 验证范围

此前[真实 HTTP 实验](verification/2026-10-21-http-auth-live.md)与[WebVPN 后续复核](verification/2026-10-21-webvpn-http.md)记录特定账号、阶段、时间及失败。正式适配器、保存恢复和实际业务的新验收以[验证索引](verification.md)所链接记录为准，不能将旧实验自动改称本轮产品实测。

更多账号、自然会话到期、完整 ELC/考试/雨课堂业务、真实报修写入、Docker 及 Tailscale 跨机需分别取证。对分易旧失效通知竞态和新课堂真实提交也不因新增认证适配器而自动解决。
