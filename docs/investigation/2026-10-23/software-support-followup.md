# 正版软件、Office 365 支持与补充入口

日期：2026-10-23；本轮本机取证约 **15:05–15:14:34 UTC**。仅调查，不接入 MCP。
按用户要求，`r` 和综测的失败记录保留，本轮没有再访问它们。

本机使用纯 HTTP 客户端、`trust_env=False`、正常 TLS 校验和短超时，没有运行浏览器、
更改代理/DNS/证书或切换网络。学校密码只发送至 HTTPS SSO；两个业务各用独立内存 jar，
不复制中央 Cookie。临时客户端已关闭，密码、Cookie、票据及个人页面没有持久保存。

## 1. 新入口与原目录的关系

重新读取[导航首页](https://d.stulip.org/)、其实际链接的“一键即达”和“软件下载”分类、
[学校快速通道](https://www.stu.edu.cn/kstd.htm)及信息中心用户/单位服务页。
这些页面本轮未发现原 620 URL 清单之外的新学校主机；这是有限页面对照，不能推出全部学校入口已穷尽。

另外经公开搜索发现[正版软件平台](https://ms.stu.edu.cn/)，本机 HTTPS 实读确认其标题和内容。
按解析后的完整 hostname 比较，**`ms.stu.edu.cn` 不在原 620 URL 清单中**；不能用字符串
后缀命中 `netms/efms/mms` 代替这个主机比较。它是新的文档候选，没有注册运行时来源或认证范围。

信息中心[校园网概况](https://info.stu.edu.cn/its/xyw_/xywgk.htm)另由 Firecrawl 远端实时读取，
仅用于核对教学、学习、资产、档案等业务类别；其历史建设数字没有用作 2026 年系统总数。
远端检索/读取不携带账号，不代表本机路径或业务认证成功。

## 2. ms：公开目录、详情与搜索已可读取

下列实际 GET 均返回 200、服务端 HTML，无需浏览器渲染：

| 方法/路径 | 精确合同及本轮样本 |
| --- | --- |
| `GET /` | 公开首页、软件详情和帮助链接；不是个人授权证明 |
| `GET /soft` | 15:08:18 UTC，7 个去重软件详情目标，覆盖 WPS Windows/Linux/Mac/ARM 与数科 PDF 工具；是本次可见目录，不推广成永不分页的完整资源库 |
| `GET /soft/detail/45` | 首页实际发布的 WPS 详情，200；没有下载或运行安装程序 |
| `GET /soft/search?search=WPS` | 表单明确 `method=GET/action=/soft/search`，字段 `search`；返回 5 个去重详情目标 |
| `GET /soft/search?search=stu-mcp-no-match-20261023` | 15:08:23 UTC，正常 HTML、0 个软件详情目标；与登录跳转、连接错误分别记录 |
| `GET /help/detail/821` | 官方 WPS 使用指南，原文更新于 2024-08-29；不能把此旧指南当当前认证实测 |

详情目标来自 `/soft/detail/<id>` 实际锚点，并按 ID 去重；首页、导航和重复“查看详情”
不能重复算作软件条目。分类链接还实际发布 `GET /soft/?categoryid=7` 与 `categoryid=13`，
本轮未另发分类请求，不把它们写成筛选已验收。未核实正常分页或所有软件详情元数据。

公开内联脚本还声明 `GET /change_token`、`gp4://` 客户端调用及安装包路径。
这些涉及客户端激活材料或下载，本轮未请求、未调用协议处理器、未下载/激活软件。
“立即下载”标签本身也不是下载授权成功证明。

## 3. ms：登录与 WPS 在线空间仍是独立证据

`15:08:23 UTC` 匿名 `GET /login` 返回 302，真实 CAS service 为
`https://ms.stu.edu.cn/login`。`15:11:12 UTC`，学校 SSO 已发出新票据，
ms 独立客户端处理该回调后却 302 回相同 SSO；本轮没有获得 ms 的正向业务身份。
没有重试密码、复制其他业务 Cookie 或转用本地登录。页面声明的 `login?logintype=2`
仅作为另一路径记录，未尝试。

`15:06:53 UTC` 匿名 `GET /wps` 的当前实际第一跳是
`https://open.wps.cn/oauth/v1/auth`，参数名为 `app_id/cb`，回调指向金山文档。
这与旧指南概述的“进入学校认证”不能直接等同；本轮没有继续外部授权、读取文档、绑定
手机号/微信或申请新权限。因此只能确认学校发布的 WPS 在线空间入口及第一跳，不能宣称
学校登录会话已经配置 WPS 文档访问。

## 4. support：当前项目是 Office 365

[support 首页](https://support.stu.edu.cn/)本轮发布一个支持项目 ID 和三种联系形式：
亲自送修（类型 1）、稍后致电（3）、电邮（4）。ID 取自当前 DOM，不是枚举。
认证后项目查询返回 `Support_Name_CN/EN=Office 365`；不能把这个站写成所有校园网络、
宿舍设施或校园综合报修的统一后台。

`15:06:53 UTC`，匿名 `GET /Default.aspx` 返回学校 SSO，精确 service 为
`https://support.stu.edu.cn/Default.aspx`。`15:11:13 UTC` 新票据回调后进入
`/index.html` 200；这个首页本身可匿名读，**单凭首页 200 不算认证成功**。

真正的身份与读取证明如下，均使用本业务独立 jar：

| UTC | 方法/路径 | 实际结果与证据边界 |
| --- | --- | --- |
| 15:11:26 | `POST /GetSupportItem.ashx?method=UserInfo`，零长度表单体 | 200、JSON `data` 数组 1 项。15:12:28 仅在内存将 `ldap_id` 与用户授权账号精确比较，唯一匹配；不输出身份值 |
| 15:11:27 | `GET /GetSupportItem.ashx?method=GetItemID&ID=<首页项目ID>` | 200，`data[0]` 字段为 `Support_ID/Support_Name_EN/Support_Name_CN/icon_url/Page_url` |
| 15:11:28 | `GET /GetSupportItem.ashx?method=GetItemTypeID&ID=1` | 200，`data[0]` 有 `SupportType_ID/SupportType_Name_CN/SupportType_Name_EN/icon_url/Page_url/is_stop` |
| 15:11:29 | `GET /order.html` | 200，只读到 15 列表头及脚本；HTML 只有表头，不据此判预约为空 |
| 15:12:29 | `POST /GetSupportItem.ashx?method=MyBooking&SPID=-1&SPTID=-1&BFLG=-1`，零长度表单体 | 原页 `tb.js` 的初始化查询；200，实际 `{"data":[]}`。这是本人已认证查询的正常空结果，没有创建预约 |

`UserInfo` 上游返回了比核实身份更多的个人字段，本轮只保存字段结构和本地匹配布尔。
未来若适配，必须限制返回的身份信息，不能把上游完整用户对象原样暴露给 Agent。

### 未登录、空结果与分页

`15:08:23 UTC` 匿名项目/类型查询均 HTTP 200，但正文是
`{"Result":false,"Message":"NO"}`，没有 `data`。`15:13:48 UTC` 使用新的匿名 jar，按原方法
分别 POST `UserInfo` 和初始化 `MyBooking`，均再次得到这个拒绝结构。
它与已认证的 `{"data":[]}` **不是同一种空结果**，不能只按 HTTP 200 判断成功。

`tb.js` 将 `MyBooking` 的数组整体读入，再按 `base-paging.js` 的默认每页 10 条在客户端切片。
筛选使用当前选择的 `SPID/SPTID/BFLG` query 参数，仍为 POST；本轮只验证官方初始化的
三个 `-1` 值，没有实测非空历史、其他筛选、会话过期时长或所有服务端数据范围。

客户端消费的记录字段包括 `Booking_ID/Booking_Flag/Booking_Flag_Name/Submit_Date/Accept_Date/
Update_Time/Support_ID/SupportType_ID/Booking_Time_ks` 及联系/处理人字段。
这些字段来自公开脚本声明，本轮空数组没有提供非空记录的实际类型/可空合同。

### 写入边界

脚本声明 `POST ?method=Add` 和 `POST ?method=CancelMyBooking&ID=...`，本轮均未执行。
送修/致电分支与电邮分支的必填校验不完全相同；不能照搬当前 JS 的“保存成功”提示作为
服务器已受理证明，也不能将联系动作当只读查询。

## 5. 其他补充入口与访问条件

| 业务 | 本轮新证据 | 未验证部分 |
| --- | --- | --- |
| 教学质量 `quality` | 原 HTTP `getLoginType` 仍返回 CAS 配置；HTTP 用户信息和菜单接口均 401。两个已发布 HTTPS 目标本机 `ConnectError` | 未登录、未换 HTTP 票据、未改证书；连接失败阶段没有完整分类，不能说必然证书过期或系统停用。通用 bundle 路由不等于学生权限 |
| 图书馆学位论文提交 | [图书馆正式说明](https://www.lib.stu.edu.cn/article-554.html)发布 `http://app.lib.stu.edu.cn/tasi/paper_post`；15:14:34 UTC 本机匿名 GET 得到 502 | 身份核验、本人提交状态及接口未知；没有输入学号/证件信息或上传论文。这个提交子业务不能由馆藏查询、MySTU 或毕业论文检测代替 |

quality 的公开配置同时含其他学校 OAuth 和本地开发 URL；仅以实测 `loginType=CAS` 与
本校 service 为证据，没有访问那些通用发行遗留目标。

## 6. 证据与剩余工作

安全摘要和公开脚本位于忽略目录 `output/campus-protocol-survey/service-discovery/`：
`observations.jsonl/public-page-controls.json/public-contract-summary.json/auth-observations.jsonl`。
认证后仅保存结构、数量、公开项目名及本地身份匹配判据，没有保存个人 HTML/JSON 内容或会话。

本轮可继续评估的是 ms 公开目录/搜索/帮助，以及 support 独立账号下的本人支持记录查询。
ms 认证、WPS 外部授权、quality 学生权限和学位论文提交仍需单独取证。
这些都是协议调查结论，不意味着当前 47 个 MCP 工具已经增加功能。
