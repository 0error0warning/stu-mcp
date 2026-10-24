# 第二轮末项：ehall 办事大厅、NetMS 菜单与入口纠偏

日期：2026-10-23，以下均为 UTC。继续按已发布的精确入口纯 HTTP 只读调查，没有启动浏览器或接入 MCP。密码没有发送到这些业务页；正常 HTTPS CAS/OIDC 票据只在临时独立客户端中交接，未持久保存。17:57 左右统一关闭临时认证进程，返回 `COMPLETE_NO_SESSION_PERSISTED`。

## 1. ehall 办事大厅与预约使用不同客户端

17:52:33 GET `https://ehall.stu.edu.cn/taskcenter-v4/`，200、1054 字节，标题“办事大厅”。17:53:15 沿实际脚本链接读取 `manifest.js` 和 `app.js`；不是把预约认证直接继承为办事大厅认证。

| 公开配置／代码 | 实际声明 |
| --- | --- |
| `INFOPLUS_URL` | `https://ehall.stu.edu.cn/infoplus/apis/v2` |
| `SSO_URL` | `https://ehall.stu.edu.cn/sso` |
| `SSO_SCOPE` | `profile task process app openid data` |
| `SSO_KEY` | 办事大厅自己的公开 OAuth client ID，与预约前端不同；不是密码或密钥 |
| `PATH` | `/taskcenter-v4` |
| callback | 当前 `app.js` 声明 `origin + PATH + /workflow/oidcCallback` |
| response type | `id_token token` |

17:55:24，按这些实际配置新建独立客户端，通过 `/sso/oauth2/authorize`、学校 HTTPS CAS 与 `/sso/login` 返回 callback。随机 state 精确匹配；令牌只留内存。没有借用预约 access token，也没有复制中央 Cookie。随后用本客户端 Bearer 读取：

| GET 路径 | 条件 | 实际结果 |
| --- | --- | --- |
| `/sso/oauth2/userinfo` | 无查询参数 | 200；`email` 精确匹配预期本人学校邮箱，私人值不输出 |
| `/infoplus/apis/v2/me/profile` | 无查询参数 | 200、`errno=0`；`entities` 1 项，含 account/userName/email/phone/title/enterprise 等字段 |
| `/infoplus/apis/v2/me/tasks/todo` | 无查询参数 | 200、`errno=0,total=0,entities=[]` |
| `/infoplus/apis/v2/me/processes/doing` | `limit=10,start=0,keyword=` | 同上，正常空态 |
| `/infoplus/apis/v2/me/processes/done` | 同上 | 同上，正常空态 |
| `/infoplus/apis/v2/me/apps` | 无查询参数 | 200、`errno=0,total=4,entities` 4 项 |

响应包装为 `errno/ecode/error/entities`，部分列表另有 `total`。空列表没有可用流程 ID，未猜 ID 获取详情。没有把 `total=0` 推广成所有用户或所有历史都无记录。

17:56:41 对 `/me/apps` 再次只读核对目录：

| 当前可见应用名 | 目录发布的 URI（仅记录，没有访问） |
| --- | --- |
| 预约中心 | `https://ehall.stu.edu.cn/infoplus/form/YYZX/start` |
| 问卷系统 | `https://ehall.stu.edu.cn/infoplus/form/WJXT/start` |
| 检索证明申请 | `https://ehall.stu.edu.cn/infoplus/form/JSZMSQ/start` |
| 离校申请 | `https://ehall.stu.edu.cn/infoplus/form/LXSQ/start` |

四项均 `kind=workflow,visible/ready/release=true`，字段还包括 `code,department,id,tags`。这些是该身份当前可见应用配置，不是四次申请已验收，也不表示它们与一网通办 50 事项共用业务会话。所有 `/form/*/start`、任务操作、收藏修改、抄送标记和流程提交均未执行。

## 2. NetMS 剩余菜单

17:52:33 留言页先 302 学校 SSO；17:53:15 按该响应发布的同来源 HTTPS service 正常续票，仍使用隔离 NetMS 客户端，不重新提交密码。留言页随后 200。此处不是无限重登或旧浏览器前提。

| UTC | GET 实际路径 | 页面／字段证据及边界 |
| --- | --- | --- |
| 17:53:15.169510 | `/message/listMessage.aspx`，正常 CAS callback | 表 `ctl00_Main_dgMessages` 共 3 个渲染 `tr`；没有已识别的 `th` 或 pager。未确认表头/数据分行，不将 3 直接称作 3 条消息；未跟消息详情、未执行标记已读 |
| 17:53:15.528892 | `/wlfw/netpay3131.aspx` | 登录后仍 302 `error.aspx?flg=0&msg=3131&url=…`，实际错误页 404；不把它称作可用科研流量包查询，不据此确定权限、停用或服务端错误根因 |
| 17:56:41.940076 | `/wlfw/vpn3043.aspx` | 200，WebForms 状态与 `ctl00$Main$btnSubmit/btnBindSJ`；未开通、绑定手机或发送验证码 |
| 17:56:42.139689 | `/wlfw/dns.aspx` | 200，域名登记表；责任人/联系/单位/邮箱/电话/证件/域名/IP/类型/使用期限/说明控件已见；没有提交、取消或导出私人值 |
| 17:56:42.286680 | `/SIP/xxlm3095.aspx` | 200，列表 1 个渲染 `tr`；`TextBox_look,btn_search,btn_add,btn_export`，没有执行搜索、添加或导出；不能称已读取具体登记记录 |

这些路径均在当次 NetMS 菜单实际发布；没有尝试单位批量订购记录或访问工作人员名单。域名页具体控件除 WebForms 状态外为：`ctl00$Main$txtZrr/txtContact/txtDept/txtDept2/txtMail/txtMail2/txtPhone/txtPhone2/txtSfz/txtDomain/txtIp/rblType/UCInputDatePeriod$TB_date/UCInputDatePeriod$LB_avail/txtDesc/btnDone/btnCancel`，斜线后是同一前缀下各自独立的控件名。

申请表可见只证明字段合同，不证明申请资格或执行成功。NetMS 实时用量仍未发现可靠合同，不能由套餐、留言、VPN 登记状态推算流量余额。

## 3. 入口名称与独立身份的纠偏

| UTC | 实际请求 | 结论 |
| --- | --- | --- |
| 17:52:32、17:54:19 | `http://uptime.stu.edu.cn/` 301，跟进其同主机 HTTPS 后 200 | 当前响应是“汕头大学网络与信息中心”网站：`Info.aspx/NewsList.aspx/News.aspx/Links.aspx` 类型 CMS 导航；本页没有识别到网络状态、监测、测速链接。不能按 `uptime` 名称编造实时监测 API，也不能断定该主机所有历史路径都无状态服务 |
| 17:52:33.106054 | `https://gdc.stu.edu.cn/Login/StudentLogin` | 本轮精确学生登录入口 403、590 字节，没有取得登录表。保留前轮独立表单脚本证据与当前拒绝分别的时间，未发送密码或尝试验证码；没有证明校园 SSO 能直登个人就业功能 |
| 17:52:33.311253 | `http://project.stu.edu.cn/` | 200；页面自己说明二级单位账号由平台管理员提供、填报负责人账号由单位提供、评审专家账号与任务由管理员提供。不是学校统一密码已足够；未尝试主校凭据或职工项目资料 |

`project` 的公开列表/手册入口与个人填报、评审另分，公开页面的成功不能证明本人有业务角色；`gdc` 公开职位检索成功同样不能继承为学生简历/手续认证成功。

## 4. 可复核材料

忽略目录 `output/campus-protocol-survey/round2/observations.jsonl` 的 `last-sweep/workflow-read` 保留上述时刻、状态、字段和计数；`contracts` 明确为 `network_request_performed=false` 的本地解析。

| 公共脚本 | SHA256 |
| --- | --- |
| `https://ehall.stu.edu.cn/taskcenter-v4/static/js/manifest.js` | `423395e69d5aa636c9b7c120edb1b7ed8cdf559ba4e5a1b7f78005663a484d55` |
| `https://ehall.stu.edu.cn/taskcenter-v4/static/js/app.js` | `55b580f588fa8b60b46f939965abf066f9e84040d466974052445475f1eba323` |

没有把状态摘要或公用前端代码等同于产品实现；这些临时调查脚本没有进入运行时、正式认证配置或 MCP 工具接口。
