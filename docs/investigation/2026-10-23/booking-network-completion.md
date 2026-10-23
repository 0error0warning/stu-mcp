# 预约、网络账户和一网通办：补齐真实读取

本轮请求时间为 **2026-10-23 16:00–16:21 UTC（北京时间 10 月 24 日 00:00–00:21）**。
这是开源 `stu-mcp` 的协议调查，没有接入 MCP、改认证白名单或运行时设置。
各来源使用独立的内存 HTTP 客户端，中央 SSO 另用一个客户端；普通密码仅提交一次到
HTTPS SSO，随后按各站已发布的精确 HTTPS service 取得新票据，没有复制中央 Cookie、
使用浏览器、改 DNS/代理/证书或执行预约、申请、签到、支付。

安全结构摘要位于忽略目录 `output/campus-protocol-survey/entry-completion/`。
认证后原始页面、令牌、Cookie 和身份字段值不随报告保存。临时认证进程已结束，返回
`COMPLETE_NO_SESSION_PERSISTED`。本文补充原 [学生及预约调查](student-booking.md)和
[网络及一网通办调查](service-network.md)，旧时间和旧失败不冒充当前结论。

## ehall：SSO、OIDC、资源和本人记录均取得业务证据

从 [预约首页](https://ehall.stu.edu.cn/yy-sys/pc/home)当次配置取得 OIDC 参数，使用学校
公布的 client、redirect URI、response type 和 scope；中央 CAS 与 ehall 的 Cookie 分开。

```text
GET /sso/oauth2/authorize
303 /sso/login
303 HTTPS 学校 SSO（service 来自该次 ehall 跳转）
GET 本次 ehall HTTPS CAS 回调
303 /sso/oauth2/authorize
303 /yy-sys/oidc-callback#...
```

回调取得 `access_token/id_token`，`state` 与本次发起值一致，令牌只在内存中使用。
这不是凭一个 303 判断成功：随后 `GET /sso/oauth2/userinfo` 返回 200，`email` 与本次
授权学校账号对应的邮箱精确一致。仅记录匹配字段名，不输出邮箱或其他身份值；本轮未
单独完成 JWT 签名、刷新、退出或失效合同验收，不将这份研究脚本当成成品认证适配器。

真实读取合同：`POST https://ehall.stu.edu.cn/bus/graphql/me`，JSON body 为
`operationName/query/variables`，header 为 `Authorization: Bearer ...`，查询参数
`id_token_hint` 携带本次 ID token。请求采用官方模板中已经声明的字段子集，未调用写入。

| Operation | 实测输入 | HTTP 200 的业务结果 |
| --- | --- | --- |
| `findResourcesTypeAllByAccountForDisplay` | `variables={}` | `data` 数组 5 项、无 `errors`；类别为校园活动、体质测试、新生预约、测试专用、运动场地预约 |
| `findResourcesAllByAccount` | `first=10, offset=0` | 数组 4 项、无 `errors`；含资源 ID/类型/名称/编号/状态/校区楼层字段。本轮未以一页证明全部筛选和分页 |
| `findAppointmentInformationAllForSelf` | `first=10, offset=0, updateAppointmentState="0"` | `edges=[], totalCount=0`，`pageInfo.endCursor/startCursor=null`，无 `errors`；是本人正常空列表 |
| `findResourcesTimeSlotByResourcesIdAndDate` | 资源 ID 取上一条真实可见列表；`date` 按官网传毫秒时间戳 | 返回 1 个时段、无 `errors`；含 `id/resources_id/kssj/jssj/order/canAppointmentNumberDesc/canAppointmentNumber` |

类别存在不代表当前开放预约；不能把“测试专用”当正式学生服务，也不能由时段记录证明
当下有名额、本人符合资格或可以提交。`resources_name_en/campus_name` 等在实际响应中
可能为 `null`；`state` 为数字，而 `open_captcha_verify` 为字符串，不能一律强转布尔。

本轮实际发现一个易错合同：GraphQL 声明 `Date!`，前端却以 `Date.getTime()` 或
`parseFloat(moment(...).format("x"))` 传**毫秒数**。先前以 `YYYY-MM-DD` 字符串发起的读取
得到 `data=null`、`errors` 中的非空 Date 参数错误；更正为官网的毫秒协议后成功。
这条错误的 `extensions=null`，解析器还必须能处理空扩展，不能只取 HTTP 状态或强取
`extensions.code`。成功时样本日期为北京时间 2026-10-24 当日零点，不硬编码主机时区。

`updateAppointmentState="0"` 是本人列表的显式只读条件，不能省略后自动采用可能改变
预约状态的默认值。预约、签到、取消、验证码和通知已读均未调用。匿名缺 token 的
`INVALID_REQUEST/access_token required` 样本继续见原报告。

## 旧 booking：与 ehall 分开，当前有可读业务及旧迁移提示

学校原页面给出的 SSO 链使用 HTTP SSO 地址；本轮将密码仅发往正常 HTTPS SSO，
沿同一已发布的 HTTPS service `https://booking.stu.edu.cn/Default.aspx` 完成回调，
302 到 `/MainFrame.aspx`，随后业务页面可读。没有改为明文登录或借其他业务 Cookie。

| GET 路径 | 当前实际读到的范围 |
| --- | --- |
| `/MainFrame.aspx` | 当前菜单含活动、图书馆/会议室、开放实验室、体育园、职业咨询、海洋所、门诊以及本人记录；菜单存在不证明全部可用 |
| `/Events/EventsSearch.aspx` | 服务器 HTML 活动列表：地点、类别、活动起止、预约起止、负责单位及详情链接；本轮展示含教职工活动，不能推断学生可报名 |
| `/Events/EventsView.aspx?hdKey={当次列表值}` | 200 活动详情，沿真实 `window.open` 目标读取，没有报名 |
| `/BookingArea/AllLibraryRoom.aspx` | 报告厅和 30A/30B/30C 四个房间，含容量、设备、地点及真实 `hdid` 链接；这是资源资料，不是实时可约结果 |
| `/BookingArea/Venue_Application_Form.aspx?hdid={列表值}` | 200，取得日期/时段/周切换查询控件及默认日历结构；只 GET，未进入下一步或提交 |
| `/BookingArea/AllOpenLab.aspx` | 仍列房间和技能项目，但正文明确部分技能训练室从 **2021-04-08** 改用新地址；不能把旧房间清单当现役可约资源 |
| `/SportsPark/BookingChart.aspx` | 200，取得图例、默认周表及三个周切换按钮；未将没有排班行解释为有空位，也未调用保存 |
| `/BookingArea/MyBookingArea.aspx` | 200，明确“暂无相关场地预约信息” |
| `/Events/MyBookingActivity.aspx` | 200，明确“暂无相关活动预约信息” |
| `/BookingArea/MyBookingOpenLab.aspx` | 200，明确“暂无相关场地预约信息” |

这些空记录是认证后的页面结果；本轮尚未找到该站独立的学校账号字段正向绑定判据，
也未取得非空本人记录、完整翻页/筛选和过期样本。没有读取本人门诊、工作人员审批
或他人的预约明细。

场馆页面采用 WebForms，同路径 POST 保留当次 `__VIEWSTATE/__VIEWSTATEGENERATOR/
__EVENTVALIDATION`。已观察的查询字段为 `venue_book_lib1$input_time`、`...$btn_choose`、
`...$ddl_start/ddl_end`、`...$btn_last_week/btn_current_week/btn_next_week`；`btn_next` 和
体育园 `btnSave` 属后续业务操作，未调用。本轮不把字段发现写成日期查询 POST 已验收。

### 新发现的技能训练室地址

旧开放实验室页正文实际公布 `http://10.11.163.1:8003`。按此**原发布地址**做匿名 GET，
302 `/CommonAdmin/Login.aspx`；该登录页 200，含 WebForms 状态、`txtUsername/txtPass/
CheckCode/btnLogin` 和图形验证码。没有猜其他地址、扫描端口、使用公告中的初始密码，
也没有将主校 SSO 密码发往 HTTP 登录页。其实际身份、资源和时段仍未核实。

## ELC/CILL：独立 Moodle 认证后 MRBS 日历可读

本轮以独立业务客户端完成 `https://my.stu.edu.cn/courses/elc/login/index.php` 的正常
HTTPS CAS、Moodle session test 和首页跳转，无需复制 `_UT_` 或 MySTU 已保存会话。
随后 MRBS `index.php` 303 到当日日历，`day.php?day=24&month=10&year=2026` 200、标题
`Booking system`，区别于匿名时跳回 ELC 登录的结果。

日期页真实发布了 All CILL Rooms、CILL Guided Tour、IELTS、口语/会话、中文、写作、
语音等分区，其中若干区分线上/线下。区域值必须从当次链接读取，不硬编码教师或房间。
日历 GET 的表单字段为 `day/month/year/area`；搜索 GET 为 `search_str/day/month/year/
area/lang`；房间定位 GET 为 `room/day/month/year`。周、月、区域和当前预约条件尚未
全量实测，没有查询他人预约详情、生成报表、搜索个人姓名或操作新增/修改/删除预约。
身份账号字段绑定、本人记录及正常空态仍缺；课程查询已经接入不代表 MRBS 已接入。

## NetMS：补上本人字段绑定，流量口径仍不冒进

本轮 HTTPS CAS 后 `/message/listMessage.aspx?flag=9` 200。本人信息 GET
`/info/displayYhInfo.aspx` 的 `ctl00_Main_Label_ldap` 与本次授权学校账号**精确一致**。
该页还含 `Label_name/vid/sex/csrq/sfz/ykt/lxdh/dbdw/yhtype/yhflg/cjrq/tc/proxy/vpn`
及 `lblOffice365` 等独立标签；报告只保存字段名。

`GET /wlfw/netpayOrderingAdditional.aspx` 200，页面有“使用赠送流量／已赠送的流量／
已使用的流量”区域；本轮样本没有可据以解释金额、配额或实时余额的数据表。
这不是“剩余流量为零”的证据，也没有找到可直接报告实时已用流量的合同。
套餐/当天包、单位批订、VPN/DNS/SIP、账户绑定、Eduroam/MAC 操作仍分别保留原边界，
没有因为共用 NetMS 菜单就将写入接口当查询。

## 一网通办：本人身份和首页空记录补证

业务 CAS 回调后的旧 `/fe` 路径仍 301 到 HTTP 尾斜杠页；本轮停在明文跳转前，
另读已知 HTTPS 路径，不发送业务 Cookie 到 HTTP。

- `GET /site/user/baseinfo`：200、`e=OK`；`d.email/users__email` 与本次账号邮箱精确一致。
- `GET /api/home-page/details`：200、`e=OK`；本人 `todo/inst/task_finished`、收藏等
  `data=[]`，`message_notify.data` 有 5 条结构记录；只取结构，没有读消息详情或标记已读。

首页结构还含 `share_task_finished/recently/payment/dsq/fill/feed_back/my_appraise` 等；
其存在不证明所有专门分页接口、办理表和申请权限。原 50 事项公开列表和详情已验证的
证据继续有效，**37 个内部事项的具体流程表仍未查询**，不能以首页空待办代替。

## 保留的当前阻碍

| 范围 | 本轮结果及边界 |
| --- | --- |
| classroom | 新 HTTPS CAS 票据回调 `/Index.aspx` 后仍 302 到 SSO，service 中又包含前票据参数；没有循环重试或宣称需要浏览器 |
| 既有教务会话的学期课表 | 本地加密会话缺严格 `jw_http_compat=True` 标记，本地显式偏好也未开启，固定读取因 `insecure_transport` 停止；没有改偏好或把旧一次性 HTTP 验证扩大为新来源许可，也没有取得课表数据 |
| SLC | 原解析失败记录保留，未由 booking 登录成功推断 SLC 恢复 |
| 校园卡本人业务 | 独立查询密码与图形验证码仍缺，不用学校密码替代；公开公告另外补证见下 |
| 科研、停车、访客、财务 | 当前认证结果分别见 [行政补查](administration-completion.md)，不因学校 SSO 续票成功推断业务授权成功 |
| CARSI | 已走到属性释放确认，未发送同意或 SAMLResponse；见 [图书馆补查](library-completion.md) |

## 校园卡的公开读取补证

`homeLogin.action` 的中文 HTML 实际需要 **GB18030** 解码。搜索表的 HTML 未写 action，
`onsubmit=doSummitst()` 才设为 `xxsearch.action`，不能只读静态 form.action 就误发登录表。
真实只读 POST 为表单 `searchnotices/searchtype/lmid`；`searchtype=1` 搜标题、`2` 搜正文，
`lmid` 从当次栏目选项读取。以无匹配词、`searchtype=1,lmid=all` 请求，返回 200 并明确
“共 1 页 0 条记录”，不是登录 HTML。每页显示 17 条是该样本界面配置，不是通用固定值。

业务指南栏目实际提供 `managerOneGgxxfb.action?fbxxid={栏目给出的ID}`，沿真实脚本
打开链接 GET 200，标题“一卡通常见问题及解答”。这只补齐公开栏目/检索/正文合同，
不代表校园卡余额、消费、挂失、充值或查询密码业务已经验证。
