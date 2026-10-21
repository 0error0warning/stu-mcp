# WebVPN 纯 HTTP 认证与资源访问复核 · 2026-10-21

本记录接续[首次 HTTP 账号验证](2026-10-21-http-auth-live.md)，保留此前 20113 拒绝事实，不把后续成功回填到旧实验。
时间均为 UTC，日期为 2026-10-21。本轮没有启动浏览器、操作系统网络设置或修改原 School Hub。

## 密码与已绑定 TOTP 已通过

| 本轮 | 实际结果 | 证明范围 |
| --- | --- | --- |
| 07:23:47–07:35:05 | 对齐普通 Web 请求后，一次密码 POST 返回 `ErrorCode=1`，要求已绑定 TOTP；等待中的认证上下文在一次 TOTP POST 后返回 `20014` | 密码阶段通过；官方定义为用户已超时或已注销，不能当作动态码错误 |
| 07:37:41–07:38:21 | 全新 HTTP 会话，一次密码 POST 返回 `1`、已绑定 TOTP；在该步骤即时调用本人授权的现有本机令牌工具，一次 TOTP POST 返回 `1`、无后续认证项 | **两阶段认证通过**；后续 OA HTTPS 请求在取得 HTTP 响应前连接失败，尚无 OA 正文证明 |
| 07:54:03–07:54:31 | 再次全新会话，密码与即时生成 TOTP 各一次、均返回 `1`；同一客户端读取 `conf.csp` 和 `rclist.csp`，解析为真实 `Conf`／`Resource` | **认证后配置及资源目录读取通过**；唯一 OA 条目为 `webapp:http`，外层配置为 HTTP、8118 端口。保留其真实类型，没有改走其他资源分支或发送 OA HTTP 请求 |

本机令牌生成沿用原工具的 URI／编码／位数／周期处理，先在内存核对配置账号，再生成当前码。
确认本机已有工具后，后续两轮无需打开图形窗口或请用户手动抄码；没有输出密钥或动态码，亦没有迁移配置到开源项目、产品 Vault 或实验回执。
原始密钥只从本人指定的原配置在进程内使用；本人账号匹配及服务器接受 TOTP 的证据与后续 OA 可达性分开。
旧工具与开源 `parse_totp(auto)` 的编码识别优先级不同；未来迁移应保留明确的编码／URI 参数，不能凭自动识别顺序重新解释既有种子。

## 找到的协议差异

官方普通 Web 登录顺序是：

1. 门户初始化 `login_auth.csp`，密码组件读取 `psw_config`。
2. 用户输入后，`business/auth.js:authPsw` 默认再次调用 `getInitConfig`。
3. `api/init.js` 更新全局 nonce／RSA 参数；`api/auth_psw.js` 读取最新参数，加密并提交密码。

此前实验没有第 2 步，直接使用 `psw_config` 副本。07:20:59 的两组全新匿名会话对照确认，最后一次初始化会改变 nonce，公钥／指数和会话当轮未变。
后续受控实验同时使用普通 Web User-Agent、门户入口和完整初始化顺序后，密码阶段不再返回 20113。
这证明该纯 HTTP 路径可用，**不能单独把此前 20113 归因于 nonce、User-Agent 或某项学校账号策略**。
没有冒充 EasyConnect、改变账号权限、跳过 MFA、求解图形挑战或修改令牌绑定。

官方请求使用自写 XMLHttpRequest，未默认添加 `X-Requested-With`；不按其他库惯例补不存在的请求头。
密码后的 TOTP 优先使用响应新 `TwfID`，未返回则保留当前会话；提交字段为 `twfid`、`svpn_inputtoken`，与官方链一致。
普通 Web 的后续链为 `common/auth → service_init → SF.res.init → conf/rclist`；未发现必须补 `update_session` 的步骤，不能把原生客户端的会话切换分支当作 Web 登录补丁。
`20014=ERRCODE_EAUTH_TIMEOUT`，官方提示“用户已超时或已注销，请重新登录”；它与动态口令错误码不同。

## 官网 OA 路由与先前 HTTPS 候选的差异

07:42:13 的匿名严格 TLS 检查显示：

- `webvpn.stu.edu.cn:443` 验证通过，证书 DNS SAN 为 `*.stu.edu.cn`、`stu.edu.cn`。
- `oa-stu-edu-cn.webvpn.stu.edu.cn:443` 与另行匿名检查的 `oa-stu-edu-cn-s.webvpn.stu.edu.cn:443` 均返回证书校验码 `62`，主机名不匹配。
- `*.stu.edu.cn` 不覆盖上述多一级子域。DNS 解析成功和认证成功不能消除这个 HTTPS 证书错误。

不能通过关闭 TLS 校验、固定旧 IP 或自动改走明文 HTTP 掩盖该问题。
资源地址应从认证后当前门户配置与目录确定；原始 OA 目标、WebVPN 重写模式、外层协议／端口及 SSO 处理分别核对，不能由 `-s` 后缀推断外层 HTTPS。

07:54 的真实认证后目录进一步确定：唯一匹配 `oa.stu.edu.cn` 的资源是 `type=0`、`svc=webapp:http`，
原目标 HTTP 80；`Conf/WebVpn` 配置外层 `scheme=http:`、`port=8118`，该条目没有 SSO 或 EasyLink 映射。
按官网 `res_opener.js` 当前分支，它使用 `http://oa-stu-edu-cn.webvpn.stu.edu.cn:8118` 转发。
这解释了为何不能把预先固定的 HTTPS 443 地址当作实际已配置入口；TLS 检查只证明这些 HTTPS 候选主机名不匹配，不能笼统称学校 OA 服务不可用。

官方 SDK 另有主门户 HTTPS 路径分支，但该分支不适用于这条实际 `webapp:http` 资源；本轮没有改资源类型来强行切换。
因此停在已验证的目录结果，没有发送明文 Cookie、关闭证书检查或取得 OA 正文。
后续如要支持这一校方现有路由，应单独设计显式的 OA HTTP 兼容选择，密码和动态口令仍只发送至 HTTPS WebVPN；不能把它混入教务的一次性 HTTP 回调许可。

## 证据与接入边界

官方来源：[密码业务编排](https://webvpn.stu.edu.cn/portal/jssdk/business/auth.js)、
[初始化](https://webvpn.stu.edu.cn/portal/jssdk/api/init.js)、
[密码接口](https://webvpn.stu.edu.cn/portal/jssdk/api/auth_psw.js)、
[TOTP 接口](https://webvpn.stu.edu.cn/portal/jssdk/api/auth_totp.js)、
[资源目录接口](https://webvpn.stu.edu.cn/portal/jssdk/api/res.js)、
[资源打开规则](https://webvpn.stu.edu.cn/portal/jssdk/business/res_opener.js)、
[错误码](https://webvpn.stu.edu.cn/portal/jssdk/common/errcode.js)、
[提示映射](https://webvpn.stu.edu.cn/portal/common/map.js)。

脱敏回执保留在被 Git 忽略的 `output/http-auth-review/webvpn/`：
`human-summary-20261021T073505778078Z.json`、`human-summary-20261021T073821871709Z.json`、
`human-summary-20261021T075431557142Z.json`、
`startup-order-summary.json`、`startup-source-summary.json`、`totp-source-summary.json`、`strict-tls-summary.json`。
回执仅有阶段、固定错误码、字段存在／匹配布尔和数量，没有种子、动态码、Cookie、票据或私人 OA 内容。
目录还保留 XML 字段／属性名及所选资源的最小协议元数据，未保存字段值、资源名称／编号、SSO 参数或原始 XML。
另有一次检查脚本完成前取消的匿名运行，密码／TOTP 均为 0 次；不计为登录失败。

实验不等于正式适配器已接入。当前产品仍沿用原有认证实现，38 项 MCP 工具接口没有改变，未发布或部署。
后续接入应优先纯 HTTP，并保留会话存储、退出代次屏障、一次发送限制、来源隔离及真实业务 proof。
资源网络／TLS 故障应与凭据拒绝分别分类，先检查已知资源入口，避免因同一资源连接错误反复重登。
