# 学校 Outlook 邮箱：入口、云环境与只读 API

调查时间：2026-10-24 01:25–01:28 UTC（北京时间 09:25–09:28）。本文件补充在前一日建立的调查目录中。

本轮只做匿名 HTTP、操作系统 DNS 查询和微软官方文档核对，没有登录邮箱、读取邮件、注册应用或同意授权。
HTTP 客户端忽略环境代理，验证 TLS，连接超时 5 秒、请求超时 12 秒；没有改变网络设置。
该客户端配置不证明机器位于校园网，也不能排除系统级网络转发。

## 1. 已确认的学校入口

| 请求开始时间 UTC | 匿名请求 | 实际结果 |
| --- | --- | --- |
| 2026-10-24T01:25:49.031686+00:00 | `GET http://m.stu.edu.cn/` | 302，目标 `https://partner.outlook.cn` |
| 2026-10-24T01:25:49.032691+00:00 | `GET https://www.stu.edu.cn/kstd.htm` | 200；学校快速通道仍发布 `partner.outlook.cn` 邮箱入口和 `support.stu.edu.cn` Office 365 支持入口 |
| 2026-10-24T01:25:49.939731+00:00 | `GET https://partner.outlook.cn/` | 301，目标为同站 `/mail/` |
| 2026-10-24T01:27:01.285357+00:00 | `GET https://partner.outlook.cn/mail/` | 200，Outlook 网页外壳；不是本人邮箱内容 |
| 2026-10-24T01:27:01.198362+00:00 | `GET https://support.stu.edu.cn/office365/help.html` | 200；公开 FAQ 仍写中国云登录域及 IMAP/SMTP 配置 |
| 2026-10-24T01:27:01.221296+00:00 | `GET https://support.stu.edu.cn/` | 200；发布账号激活、Office 下载和 FAQ 导航；没有执行密码修改或支持申请 |

学校来源：[快速通道](https://www.stu.edu.cn/kstd.htm)、[邮箱短入口](http://m.stu.edu.cn/)、
[Office 365 FAQ](https://support.stu.edu.cn/office365/help.html)。旧学校 FAQ 是现存指南文字，不能充当当前认证协议实测。

2026-10-24T01:27:40.5606375Z 开始的本机 DNS 查询返回：

| 查询 | 本机解析器返回 |
| --- | --- |
| `stu.edu.cn MX` | 优先级 5，`stu-edu-cn.mail.protection.partner.outlook.cn` |
| `autodiscover.stu.edu.cn CNAME` | `autodiscover.partner.outlook.cn` |

这是本机解析结果，不是权威 DNS 审计。学校入口、收信投递和自动发现结果一致指向中国版 Microsoft 365，
因此邮箱 API 调查不能从全球版 `graph.microsoft.com` 起步后便假定可用。

## 2. 同一学校域名在两个云都有发现结果

两个请求都没有账号、Cookie、客户端 ID或授权输入：

| 请求开始时间 UTC | 公开 OpenID 元数据 | 结果与关键字段 |
| --- | --- | --- |
| 2026-10-24T01:25:50.204799+00:00 | `https://login.partner.microsoftonline.cn/stu.edu.cn/v2.0/.well-known/openid-configuration` | 200；`cloud_instance_name=partner.microsoftonline.cn`，`msgraph_host=microsoftgraph.chinacloudapi.cn` |
| 2026-10-24T01:25:50.232384+00:00 | `https://login.microsoftonline.com/stu.edu.cn/v2.0/.well-known/openid-configuration` | 200；`cloud_instance_name=microsoftonline.com`，`msgraph_host=graph.microsoft.com` |

两份响应均包含 `issuer`、`authorization_endpoint`、`token_endpoint`、`device_authorization_endpoint`、
`jwks_uri`，但绑定的是不同租户标识。公开租户发现成功只证明该云能解析这个域名，不能证明某个学生账号
在该云有邮箱、同意自建应用访问，或能跨云使用令牌。当前邮箱入口和 DNS 的证据支持优先验证中国云；
实际本人授权及邮箱资源仍未验证。

微软官方区分各云的应用注册、身份和 Graph 端点，令牌不能跨云混用。
中国云 Graph 根地址为 `https://microsoftgraph.chinacloudapi.cn`；身份文档列
`https://login.partner.microsoftonline.cn`，Graph 部署文档另列中国云身份服务别名
`https://login.chinacloudapi.cn`。应使用经过校验的目标云与租户配置，不能用登录页外观选云。
来源：[Graph 云环境](https://learn.microsoft.com/en-us/graph/deployments)、
[身份服务云环境](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud)。

## 3. Graph 接口与最小功能边界

2026-10-24T01:27:02.102531+00:00，未带任何认证信息请求：

```http
GET https://microsoftgraph.chinacloudapi.cn/v1.0/me/messages?$top=1&$select=id
```

实际返回 401，`error.code=InvalidAuthenticationToken`，提示缺少访问令牌，认证方案为 Bearer。
这只确认所访问的中国云 API 返回认证边界；没有取得本人邮件、验证权限、分页或搜索。

| 未来只读能力 | 官方路径 | 权限与边界 |
| --- | --- | --- |
| 邮件列表、发件人、主题、时间等基本信息 | `GET /v1.0/me/messages`；或指定本人文件夹的 `/messages` | 委托权限 `Mail.ReadBasic` 是列表的最低权限；不包含正文、正文预览、附件和扩展字段 |
| 指定邮件详情 | `GET /v1.0/me/messages/{id}` | 只读基本属性可用 `Mail.ReadBasic`；读取正文需要 `Mail.Read` |
| 附件列表、指定附件 | `GET /v1.0/me/messages/{id}/attachments` | 附件列表要求 `Mail.Read`；下载需另行限制类型、体积和保存位置 |
| 邮件检索 | 消息集合的 `$search`；另有 `POST /v1.0/search/query` | 两者协议和结果形状不同；消息 `$search` 最多返回 1,000 个结果，不等于扫描完整邮箱 |

这些是官方协议能力，尚不是 STU MCP 已有功能，也不是学校已批准接入的证明。
`Mail.ReadBasic` 和 `Mail.Read` 的委托权限在权限表中均不要求默认管理员同意，
但学校租户仍可能限制用户同意、自建应用、客户端或认证方式；本轮没有验证学校实际策略。
不应申请全租户应用权限，也不需要 `Mail.Send`、`Mail.ReadWrite` 或共享邮箱权限。
来源：[消息列表](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)、
[指定消息](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0)、
[附件列表](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0)、
[权限表](https://learn.microsoft.com/en-us/graph/permissions-reference#mailreadbasic)、
[消息检索](https://learn.microsoft.com/en-us/graph/search-query-parameter)、
[Search API](https://learn.microsoft.com/en-us/graph/api/search-query?view=graph-rest-1.0)。

消息列表、消息详情、附件列表和 Search API 的当前官方国别云表都列中国云可用。
但 **`message: delta` 当前官方表明确列中国云不支持**，因此不能把全球版的消息增量同步直接作为
汕大邮箱实现前提，也不能把普通分页称为完整同步。
来源：[消息增量接口](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)。

## 4. 登录方式与尚未满足的条件

邮箱需要独立的微软 OAuth 授权。学校 CAS 成功、Office 365 支持站登录成功、Outlook 网页已登录，
都不代表自建 MCP 已经取得 Graph 权限。不能借用 Outlook 官方客户端 ID、网页 Cookie 或其他工具的令牌。

需要先明确由谁提供中国云的应用注册，以及学校租户是否允许该应用和所需委托权限。
应用 ID 是合法发起 OAuth 的前提；本轮没有注册应用、试用其他程序的 ID 或发起用户同意。

| 交互入口 | 官方可选流程 | 需要验证 |
| --- | --- | --- |
| 本机设置页、用户自己的浏览器 | 授权码加 PKCE，登记对应原生应用回调；验证 `state`、回调、租户和令牌身份 | 注册是否允许、官方回调配置、用户同意、实际 Graph 资源和独立账号关联 |
| 无桌面的 CLI / 服务器 | 公共客户端 device code；由用户在自己的设备完成微软登录与授权，服务端 HTTP 轮询 | 中国云应用的公共客户端设置、设备码流程是否被租户策略允许、验证码/MFA/同意要求 |

设备码返回的官方 `verification_uri`、有效期和轮询间隔必须按响应使用；不能硬编码全球云页面，
也不能在遇到过期、拒绝或需要管理员批准后无限轮询。授权码路线在用户自己的浏览器进行交互，
不要求 MCP 启动 Playwright、Chromium 或虚拟桌面。
来源：[设备码协议](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)、
[授权码与 PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)、
[认证流程支持](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows)。

学校旧 FAQ 仍列 IMAP `partner.outlook.cn:993`、SMTP `smtp.partner.outlook.cn:587` 和校园邮箱密码。
这不是已验证的当前账密 API。微软现行说明记载中国世纪互联自 2023-03-31 开始关闭 Basic Auth，
因此不能据旧指南实现或承诺 IMAP 密码登录。IMAP OAuth 又有独立权限与协议，不能拿 Graph 令牌直接替换。
当前应先验证 Graph 的合法委托授权，避免同时引入第二套邮件协议。
来源：[Exchange Basic Auth 退役说明](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online)、
[IMAP/POP/SMTP OAuth](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth)。

## 5. 接入时保持实现小而可靠

邮箱适合作为独立来源，复用现有 HTTP 传输、加密存储、状态和设置页基础设施，不增加通用办公套件或
邮件同步平台。第一阶段可限定为“最近邮件基本信息、指定邮件阅读、字面查询”，附件下载独立评估。
Microsoft 授权不是学校统一账号适配器的一个 CAS 子分支，配置状态也不能因学校账号已保存便变为可用。

- 按云、租户、账号和权限隔离加密授权；退出、账号切换、刷新失败沿用已有生命周期约束。
- 请求只选必要字段；分页使用完整 `@odata.nextLink`，校验云域、协议和允许路径，不自行拼改 `$skip`。
  明确本次页数、条数上限和是否仍有下一页，不把截断结果标成完整。
- 搜索、正文和附件各按已授予的实际权限提供；权限不足不能退回抓取网页内部接口。
- 429 遵守 `Retry-After`，设置总时限与有界重试；授权失效或用户拒绝不作网络故障反复重试。
- HTML 邮件作为不可信内容处理，不执行脚本、加载远程图片或跟随正文链接；纯读取不更改已读状态。

官方列表文档说明默认每页 10 条、`$top` 范围 1–1,000，但大页可能超时；实际默认应远低于上限。
Outlook 当前公布每个应用与邮箱组合最多四个并发请求，不能把服务上限当作客户端推荐并发。
来源：[列表分页](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)、
[限流处理](https://learn.microsoft.com/en-us/graph/throttling)、
[Outlook 服务限制](https://learn.microsoft.com/en-us/graph/throttling-limits#outlook-service-limits)。

截至本轮结束，已核实学校入口、DNS、双云租户发现和中国 Graph 匿名认证边界；
**应用注册、学校同意策略、本人 OAuth、消息读取、搜索、附件和刷新/退出均未实测**。
这些是接入前的具体待验证条件，不应写成“学校邮箱接口已跑通”或“邮箱无法接入”。
