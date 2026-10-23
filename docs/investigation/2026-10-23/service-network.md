# 一网通办、网络管理及网络登录：协议调查

这是 2026-10-23 的只读调查，源代码基线为 `c8db73ea5f4b6c54ae207b58cc41bd496a09df68`。没有添加 MCP 业务适配、修改配置或执行申请、订购、充值、改密、网络重新认证。主要观察时间为 UTC 12:10–12:49（北京时间 20:10–20:49）。

本机请求使用 `httpx`、`trust_env=False`、正常 TLS 校验和短超时；应用不继承环境代理，不代表绕过系统 TUN。连接配置显示 `stu.edu.cn`，不能据此推断所有用户、校外网络或服务器的访问条件。学校 SSO 与各业务分别使用内存中的 HTTP 客户端，不复制 Cookie；用户已授权使用此前提供的学校账号完成本轮验证。密码和临时会话不写入仓库，个人页面只提取字段名、菜单、结构和状态。

“响应实测”指实际 HTTP 返回；“客户端声明”指本轮官方脚本的代码；“未核实”不能当成已接入能力。浏览器实际打开的页面也不等于纯 HTTP 认证已跑通。

## 一网通办 `service`

入口：[一网通办](https://service.stu.edu.cn/fe/)。当前页面是 Nuxt 应用，前端配置 `apiBasePath` 为空，API 在同一业务域名下。页面中的“AI 办事大厅”是学校前端功能，不能据此理解为已经向本 MCP 开放 Agent API。

### 公开事项目录已完整分页读取

| 方法、路径与参数 | 实测结果 | 重要字段和限制 |
| --- | --- | --- |
| GET `/api/site/info` | HTTP 200、`e=OK` | `d` 为站点及登录显示配置；其中的可选登录/MFA 开关不是所有分支已完成实测的证据 |
| GET `/api/home-page/details` | HTTP 200、`e=OK` | `d` 含 `todo/inst/task_finished/recently/message/ztfw/hot_service/fwdt/collect` 等区域；匿名返回的空值/计数不能称为本人的待办 |
| GET `/api/app/get-items` | HTTP 200、`e=OK` | `d.departItem/categoryItem/identityItem`；项通常含 `name/value`，分类还含 `app_count`；本轮显示教职工、本科生、研究生筛选 |
| GET `/api/app/get-category-item-all` | HTTP 200、`e=OK` | `d` 数组，项含 `value/name/arrange_icon/app_list` |
| GET `/api/app/list`，`departItem=all&identityItem=all&categoryItem=all&sort_key=1&p=1&pageSize=10` | 第 1–5 页合计 **50 个不同事项 ID** | `d.total/list/page/perpage`；本轮 `total` 为数字，显式传参时 `page/perpage` 为字符串，解析时不能强假设全是整数 |
| 相同列表，第 `p=6` 页 | `e=OK`，`total=50`，`list=[]`，`page="6"` | 已核实正常空页；空页不是认证失败 |
| GET `/api/app/detail?app_id={列表实际ID}` | **50/50 个详情均 `e=OK`** | 公开说明、材料和跳转信息可读；不证明有申请资格、内部表单可读或流程可提交 |
| GET `/api/app/proc?app_id=240` | `e=OK`，`d={svg:""}` | 该项是外部跳转类型；空流程图不是接口错误，也不代表其他事项没有流程 |

以上 50 项逐项保存在 [service-matters.csv](service-matters.csv)，包含名称、部门、分类、事项类型、详情结果、跳转目标、核查时间及证据范围。实际类型为 37 项 `type=1`、13 项 `type=3`；本轮没有 `type=2` 事项。页面另有“上线数量 66”的展示计数，与当前列表的 50 项不是同一已核实口径，不能据此补造 16 个事项。

详情 `d` 实际包含：

```text
type, name, flags, times, onsite_times, views, persons,
comment, comment_star, description, depart_id, depart_ids,
identity, inst_submit_text, attribute, files, require_materials,
is_collection, svg, steps, customImg, appraise, app_detail,
start, modified, details_tips
```

`name` 为语言映射；`description` 是 HTML；`require_materials` 分 `self/other`；`app_detail.jump.url` 分 `pc/mobile`，另可能有小程序字段。不能把 PC 和手机目标、说明文本和业务记录、事项 ID 和外部业务 ID 混为一谈。

公开配置中发现两个手机目标夹带陈旧认证参数，已在 CSV 中替换为 `[omitted]`，没有重放。新生报到的手机目标还含多余引号和空格，按原配置缺陷记录，未猜测修复后声称可用。事项“住宿调退”和“假期留校”指向同一学工应用，不等于业务记录或流程相同。

### 认证与专题访问

实际链路：

```text
GET /api/login/main
302 https://sso.stu.edu.cn/login?service=业务自身CAS回调
HTTPS CAS service: https://service.stu.edu.cn/api/login/cas?redirect_url=%2Ffe%3Fplatform_id%3D33
业务回调 -> /fe?platform_id=33
```

业务站随后曾把 `/fe?platform_id=33` 301 到 HTTP 的尾斜杠地址。本次没有跟随该 HTTP 跳转，而是另取已知的 HTTPS `/fe/?platform_id=33`，返回 200。这个一次性的 HTTPS 路径恢复不能直接写成产品已实现的认证适配。

| 只读接口 | 匿名结果 | 本轮临时 HTTP 认证后 |
| --- | --- | --- |
| GET `/site/user/baseinfo` | 未以本条证明匿名身份 | HTTP 200、`e=OK`、`d` 为对象；没有输出个人字段值，未完成账户字段正向绑定验证 |
| GET `/site/matter-special-topic/detail?id=3` | HTTP 200、`e=UN_AUTH`、`m=未认证！`、`d=null` | HTTP 200、`e=OK`、`d` 为对象 |

专题页的外部浏览器路由参数叫 `topic_id`，后台详情参数叫 `id`，不能直接通传所有参数。学校网络服务专题与网络故障工单分开：前者列申请事项，后者见 [r 服务台](repair-r.md)。

### 客户端合同及未调用边界

官方通用请求封装使用 `e/m/d`，成功判据 `e=="OK"`；脚本声明 `ERROR/PARAM_ERROR/SYSTEM_ERROR/UN_AUTH/UN_BIND_IDCARD` 等错误。HTTP 200 本身不足以证明成功。本轮实际错误证明为上述 `UN_AUTH`，其余错误码仅来自客户端声明。

目录组件使用 `p/pageSize`，而不是猜测的 `page/page_size`；排序代码 1 为热门、2 为最新、3 为最近使用，最近使用依赖本人状态。其他筛选值应从 `get-items` 读取，不能硬编码学校部门 ID。

跳转包装器会先处理登录及 `/site/app/app-check?app_id=...`，再按事项类型进入内部申请或外部入口。本轮没有调用权限检查和任何启动/保存流程。收藏、评价、标记已读、增加浏览量、账户恢复、发送验证码、申请、支付等均不因名称里有 `query` 或请求方法为 GET 而认作只读。

框架 bundle 含大量后台管理和其他部署通用路径。本报告只保留用户入口与已观察接口，不把整份 API 字符串表当作汕大学生可用功能清单。

### 前端证据定位

| 本轮官方脚本 | 内容 SHA256 |
| --- | --- |
| `/fe/_nuxt/app-shell-core.cd237f07.js` | `04cf9a0e7b07443f65db708198cebdf63a7f93fdc797235dace3fdd983ade25f` |
| `/fe/_nuxt/matterDetails.82e373c4.js` | `1abbe368ae619c72bd7e90ae23341e0d4cd7359861da23fe4ca9871c3db93944` |
| `/fe/_nuxt/themeServiceDetails.49e4926a.js` | `2073ee2a780bd6ae7dc4d52104378e474f5f0cea93b759143e3b3a6bb3f0f596` |

散列用于确认这次读到的版本，文件名随前端发布变化；后续应从入口发现资源，不把散列 chunk 名固化为适配器常量。

## 网络账户及流量 `netms`

入口：[网络综合管理系统](https://netms.stu.edu.cn/)。匿名根页实际 302 到学校 SSO，service 为 **`https://netms.stu.edu.cn/default.aspx`**。本轮纯 HTTP CAS 回调后进入 `/message/listMessage.aspx?flag=9`，页面 200、标题 `NetMS`、无密码登录表单，随后本人信息及套餐页可读。未导出个人字段值，也未完成某一身份字段与预期账号的正向绑定，因此这是认证后页面访问证据，不是成品适配验收。

### 登录后实际菜单和读取

| 路径 | 页面用途/实测 | 尚未验证 |
| --- | --- | --- |
| `/info/displayYhInfo.aspx` | GET 200，我的个人信息；WebForms 页面 | 具体用户字段、身份判据、是否有实时已用流量字段 |
| `/message/listMessage.aspx` | 认证落地，给我的留言 | 消息分页/空态/详情；没有标记消息已读 |
| `/wlfw/netpayOrdering.aspx` | GET 200，个人定制上网套餐 | 订购写入与收费规则，不执行 |
| `/wlfw/netpayBuyOrder.aspx` | GET 200，当天流量包 | 购买/同步按钮行为，不执行 |
| `/wlfw/netpayDeptOrder.aspx` | 菜单列为单位批量套餐 | 单位权限及数据，不读取单位记录 |
| `/wlfw/netpayOrderingAdditional.aspx` | 菜单列为赠送流量 | 赠送余额、本人列表及使用规则 |
| `/wlfw/vpn3043.aspx`、`/wlfw/dns.aspx`、`/SIP/xxlm3095.aspx` | 菜单分别为 VPN、域名、信息服务栏目登记 | 申请表、受理及写入接口 |
| `/wlfw/netpay3131.aspx` | 公开事项目录指向科研流量包；认证后 GET 302 到 `error.aspx?flg=0&msg=3131&url=...` | 不能仅凭 302 区分身份无权限、未开放或系统错误，不能把它当本科生可用查询 |
| `/module/NotExistsPage.aspx` | 正式 IP、个人一卡通、访客一卡通菜单实际指向同一占位页 | 这些菜单不是三个已验证申请功能 |

套餐页表头为“操作、年月、套餐、交费方式、交费状态”；套餐说明区有“套餐类型、费用、流量限制、代号”。这是套餐/缴费状态，**没有据此确认实时已用流量或网络余额接口**。

页面采用同路径 WebForms POST，除 `__VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION` 外，重复行控件含 `ctl00$Main$gvList$ctlXX$ddlPackage` 和 `...$ddlPayment`；另有保存/编辑按钮、`hfFee/hfNy`。动态行序号和隐藏值必须来自当次表单，不能固定。没有读取隐藏值或发送 POST。

当天流量包页面表头为“日期、流量、金额”；控件含 `rblAmount` 单选项、`btnNewAccount`、`btnSynchronous`。按钮名不能证明是查询；本次没有点击或调用。

### 改密是另一条流程

`GET /ModifyPassword.aspx` 匿名可读 200，字段名为 `txtID/txtPassOld/btnMob/txtPassNew/txtPassRepeat/btnOK`，另有 WebForms 状态和 NoBot 字段。没有发短信、提交旧密码或修改密码。可读登录/改密表不等于认证成功，也不能将该表当 CAS service。

## 网络登录、旧引用及连通阻碍

| 原入口 | 本轮实际结果 | 后续边界 |
| --- | --- | --- |
| `http://its.stu.edu.cn/` | 连接失败；HTTPS 根连接超时 | 没有取得报修 API，不能称已永久下线或已由 `r` 替代 |
| `http://internet.stu.edu.cn/` | 200 `Internet Login`，页面脚本指向 `http://a.stu.edu.cn` | 网络登录别名，不是 NetMS 流量管理 |
| `http://a.stu.edu.cn/` | 302 到 HTTP `:80/index.htm`，其脚本指向 `/ac_portal/needauth.html` | GET 沿页面实际路径继续检查，未重新认证当前网络 |
| `http://a.stu.edu.cn/ac_portal/needauth.html` | 302 到 HTTPS `:443/ac_portal/proxy.html`，带模板、密码 tab、VLAN 等参数 | 后续 HTTPS 因缺少签发者链而失败；没有关闭校验或补猜认证接口 |
| `http://campusaccount.stu.edu.cn/campusAccount` | 本机名称解析失败 | 旧入口，不推断与 NetMS 同一后台或已迁移 |
| `http://netpay.stu.edu.cn/` | 本机名称解析失败 | 同上，未取得充值/缴费接口 |
| `http://uptime.stu.edu.cn/` | 301 到同主机 HTTPS | 只核实入口跳转，未验证状态数据接口 |

网络连接诊断、批量入口检测是工具的诊断能力，不是学校认证业务。可达、登录成功、业务可读、功能已经接入是四个不同状态。

## 尚缺的证明与证据保留

公开事项目录已核实分页、详情和正常空页；实际事项办理、本人待办列表、内部流程字段、申请权限与结果未核实。NetMS 仍需只读身份绑定、个人流量/赠送流量具体字段和错误/过期样本。旧 ITS、网络认证的证书问题、旧账务域名解析问题均保留为本次阻碍，不写成学校停服结论。

被忽略的 `output/campus-protocol-survey/primary/` 留有匿名响应回执、脚本 SHA256、字段摘要及调查脚本。认证后的完整 HTML、Cookie 和会话密钥没有保留。一次读取既有教务会话时返回 `AppError`，未由此猜测新课表/选课接口，也未刷新或改动现有会话。调查进程结束即释放其临时登录态；这些记录不改变运行时能力目录的 `not_integrated` 状态。
