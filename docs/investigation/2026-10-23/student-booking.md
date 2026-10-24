# 学生事务、宿舍、水电、校园卡与预约入口协议调查

调查日期：2026-10-23，北京时间约 20:00 起；20:30 补查公开事项路由，20:38 后补查 root 授权认证所得页面的脚本；xg 本轮最新核查为 **22:13:38（14:13:38 UTC）**。本轮在本机当前网络路径上使用直接 HTTP 客户端，`trust_env=False`、TLS 正常校验、单次连接 5 秒/请求 10 秒量级；未改代理、DNS 或证书。入口逐一请求，依据页面实际链接、脚本声明和学校指南跟进；连接配置名不能证明物理网络位置。

本文件是协议调查记录，**未实现 MCP 功能**。初轮匿名调查不提交账号密码；后续 root 按用户重新明确授权，在独立研究客户端做了学校认证，业务会话仅留在该进程内存。本文作者只分析脱敏结果和学校脚本，未读取或导出已保存凭据、Cookie、CAS 票据，未预约、缴费、挂失、发验证码、变更资料或取消申请。没有用他人的标识查询个人记录。

证据分为：**响应实测**（本轮实际响应，匿名和授权本人请求分别标注）、**客户端声明**（本轮官方 HTML/JS 中的路由/字段，尚未验证业务成功）、**官方说明**（发布的指南/通知，不能代替当前账号权限）、**未核实**（需要后续只读验证）。脚本中包含某项功能或管理员页面，不证明学校已启用或学生有权使用。

## 入口总表

| 入口 | 响应实测与认证边界 | 本轮查明的业务 | 尚缺证据 |
| --- | --- | --- | --- |
| `https://xg.stu.edu.cn/` | 302 到 `/xsfw/sys/emaphome/portal/index.do`，该路径再 302 到学校 HTTPS SSO | 学生事务平台；官方迎新手册明确迎新事项、报到单、住宿安排 | 常规学生菜单、各事项真实请求和字段、当前开放范围 |
| `https://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/pages/funauth-login.do` | 200，另一个自定义账号认证页，公开声明验证码/登录/密码找回接口 | 官方新生预报到入口；回到 `/xsfw/sys/xggzptapp/index.do?min=1` | 与现有学生 CAS 的账号覆盖关系、首次登录和表单响应 |
| `http://dorm.stu.edu.cn/` | 302 到 HTTPS SSO，`service=http://dorm.stu.edu.cn/default.aspx` | 导航标宿舍管理、宿舍查询；2025 官方指南将学生事务及宿舍管理列到 xg | 旧 dorm 当前实际菜单、与 xg 的分工、住宿费/住宿信息查询字段 |
| `http://power.stu.edu.cn/` | 302 到 HTTPS SSO，`service=http://power.stu.edu.cn/default.aspx` | 官方通知确认水电自助缴费、设置代理缴费，账号为校园网账号 | 本人账单、历史、水电读数/余额字段和分页；未进入付款步骤 |
| `http://smartcard.stu.edu.cn/homeLogin.action` | 200，校园卡本地账号/6 位查询密码/图片验证码，当前页面未声明 CAS | 公告、指南、失卡/寻卡名单；官方 FAQ 确认本人余额、消费流水、自助挂失、查询密码维护 | 本人登录后菜单、交易流水字段、日期范围/分页；独立密码不可替换成学校统一密码 |
| `https://ehall.stu.edu.cn/yy-sys/pc/home` | 200 SPA；OIDC 加 Bearer GraphQL；匿名业务查询收到 HTTP 200 的 `INVALID_REQUEST/access_token required` | 客户端完整声明预约资源、时段、限制、本人预约和审批信息；有写入/签到/取消流程 | 当前启用的资源类别、本人权限、真实成功/空集响应、SSO→OIDC 完整证明 |
| `https://ehall.stu.edu.cn/` | 302 到 `/taskcenter-v4/`，后者 200 办事大厅 SPA | 办事大厅和 `yy-sys` 预约是同域不同应用路径 | 本轮没有把根页面成功视作预约登录或业务成功 |
| `https://booking.stu.edu.cn/` | 200 旧预约导航，1 秒 meta refresh 到 `/Default.aspx`，后者 302 到 **HTTP SSO 地址**，回调为 HTTPS `/Default.aspx` | 页面同时列活动、场馆、SLC、海洋生物研究所及若干管理事项 | 当前菜单/实际开通对象、活动/场馆 API、旧导航项目是否仍可用；未跟进 HTTP SSO 登录 |
| `http(s)://slc.stu.edu.cn/` | 两个已发布协议入口均为名称解析失败 | 导航分别标互助学习中心、SLC 预约 | 仅本轮解析失败，不能证明永久停用或已迁移 |
| `http://192.168.12.151/slc/` | booking 官方页面发布的旧地址，GET 返回 400 `Bad Request (Invalid Hostname)` | 页面将 SLC 与海洋生物研究所都指向该地址，明显不能直接按标签确认业务 | 没有猜 Host、改 hosts、换内网 IP 或宣称真实迁移目标 |
| `https://classroom.stu.edu.cn/` | 302 到 HTTPS SSO，`service=https://classroom.stu.edu.cn/Index.aspx` | 教室预约入口；认证前没有业务脚本或菜单 | 可预约校区/教室、课表冲突/规则、本人预约、实际表单接口 |
| `http://my.stu.edu.cn/courses/elc/blocks/mrbs/web/index.php` | HTTP 301 HTTPS；HTTPS index 303 当日 `day.php`；day 303 ELC 登录；登录 302 HTTPS CAS，`gateway=true` | ELC/CILL MRBS 预约；官方 CILL 指南说明语言学习辅导、写作/演讲/语音等预约及教师空间预约 | 实际当前区域/房间、可约时段/课程要求、个人预约、真实成功数据；不能算 MySTU 课程查询已覆盖 |

## 1. xg：常规 CAS 门户与自定义迎新认证分别记录

### 常规入口

实际链路：

```text
GET https://xg.stu.edu.cn/
302 /xsfw/sys/emaphome/portal/index.do
GET https://xg.stu.edu.cn/xsfw/sys/emaphome/portal/index.do
302 https://sso.stu.edu.cn/login?service=https://xg.stu.edu.cn/xsfw/sys/emaphome/portal/index.do
```

初轮匿名查询停在认证边界，没有业务列表；后续授权 HTTP 读取的结果见本节补充记录。不能由学工平台的名字推断当前综测、奖助、请假、学籍等都在里面。

### 官方迎新手册给出的另一路径

[研究生院《新生预报到系统操作手册》](https://www.gs.stu.edu.cn/accessories/2024/08/fj5.pdf)给出 `/xsfwnew/sys/emapfunauth/pages/funauth-login.do#/`。本轮实际 200。
该手册描述校园网账号登录、迎新服务查找、预报到事项、报到单/二维码及住宿安排；其时间和适用新生群体是历史指南，不能替代当前登录权限。

页面配置与 `./funauth-login/api.js` 是本轮客户端证据：

| 声明接口 | 参数/用途 | 方法和验证程度 |
| --- | --- | --- |
| `/xsfwnew/sys/emapfunauth/loginValidate.do` | 验证登录；实际 Impl 声明 `userName/password` 均经 `getCryptoPwd` 的 AES-ECB、Pkcs7 加密，另有 `isWeekLogin` 和条件 `verifyCode` | **URL 编码表单 POST**；Turing 初始化改写 Axios 默认序列化，不能按其一般默认发 JSON，详见下文运行时补证 |
| `/xsfwnew/sys/emapfunauth/getVerifyCode.do`、`getRefreshVerifyCode.do` | 图片验证码/刷新 | 静态 URL，未调用；不能自动识别或绕过 |
| `/xsfwnew/sys/emapfunauth/getVerifyReciever.do` | 可用邮件/SMS 接收方式 | `getAvailableReciverService` 明确 POST；未调用 |
| `/xsfwnew/sys/emapfunauth/sendVerifyCodeService.do` | 发送验证码 | 静态声明，未调用，不因名字有 query/read 就当只读 |
| `/xsfwnew/sys/emapfunauth/modifyPassword.do`、`modifyPasswordByUser.do` | 密码维护 | 写入，未调用 |
| `/xsfwnew/sys/emapfunauth/getNoLoginApp.do` | 未登录应用初始化 | 静态声明，未调用，真实响应未核实 |
| `/xsfwnew/sys/emapfunauth/pages/funauth-login/dlyz.do` | 页面模型 `ACCOUNTID`、`PASSWORD`；声明返回 `WID/ACCOUNTID/ACCOUNTNAME/CELLPHONE/EMAIL/USERTYPE/USERSTATE/EXPIREDATE` | 页面元数据 type=list，不是匿名可读证明；未调用 |
| 同目录 `query_user_match.do` | `ACCOUNTID/USERID`，声明 `result:int` | 未调用，不能任取账号查匹配关系 |
| 同目录 `save_verifyCode.do/query_verifyCode.do/delete_verifyCode.do` | `ACCOUNTID/VERIFYCODE/FSSJ` 或 `ACCOUNTID` | 只记录模型声明，不查询、不发送、不清除任何验证码 |

页面配置的 `defaultForwardPath/refererPath` 指向 `/xsfw/sys/xggzptapp/index.do?min=1`；**实际前端跳转还做 context 检查，并不无条件使用这条配置**，后续 Impl 分析见下。`api.js` 识别 `success` 和 `reset_pwd` 状态，HTTP 辅助超时 40000ms、`X-Requested-With: XMLHttpRequest`。实际业务失败/空集合同、验证码触发条件和认证后独立会话仍需验证。

### 补充：一网通办公开事项给出的 xg 业务路由

2026-10-23 20:30，北京时间，依据本轮一网通办匿名详情生成的 [`service-matters.csv`](service-matters.csv)逐一 GET 发布的 xg PC/mobile 地址。下表路径的主机均为 `https://xg.stu.edu.cn`；`*default` 是发布 URL 的字面路径组成，**不是遍历通配符**。应用 ID 是公开事项的目标应用标识，未使用任何学生个人 ID。

| 公开事项（事项ID） | PC 精确路径（含前端 fragment） | Mobile 精确路径 | 本轮匿名响应 |
| --- | --- | --- | --- |
| 勤工助学（239） | `/xsfw/sys/emaphome/appShow.do?id=2db8258911db45cda04db5ea358869c6` | `/xsfw/sys/swmqgzxapp/*default/index.do` | 两者 302 到学校 HTTPS SSO，service 为对应被请求路径 |
| 本科生综测（240） | `/xsfwnew/sys/zhcptybbapp/*default/index.do` | `/xsfwnew/sys/swmzhcptybbapp/*default/index.do` | 两者 302 HTTPS SSO，空响应体 |
| 学生请假（249） | `/xsfwnew/sys/xsqjapp/*default/index.do#/qjsh` | `/xsfwnew/sys/swmxsqjapp/*default/index.do` | 两者 302 HTTPS SSO，空响应体；fragment 不发给服务器 |
| 新生报到（245） | `/xsfwnew/sys/yxapp/*default/index.do#/ywdh` | 目录原值有额外转义引号/空白，未作为有效 URL 请求 | PC 302 HTTPS SSO；未自行修好 mobile 原值并冒充目录原始配置有效 |
| 奖助学金评选（241） | `/xsfw/sys/jxjapp/*default/index.do?EMAP_LANG=zh#/scolarship_manage` | `/xsfw/sys/swmjxjapp/*default/index.do` | 两者 302 HTTPS SSO；PC service 保留语言参数 |
| 住宿调退（242）、假期留校（243） | `/xsfw/sys/emaphome/appShow.do?id=c9dd64e687db46acbddf8a4e7a37f544` | 原地址带已删认证票据；仅对移除全部票据后的 `/xsfw/sys/swmxszsapp/*default/index.do` 基路径做匿名 GET | PC 与无票据基路径均 302 HTTPS SSO；两事项共用发布目标，不证明它们业务功能相同 |
| 优秀导生（238）、文明宿舍（237） | `/xsfwnew/sys/rychapp/*default/index.do#/ywdh` | `/xsfwnew/sys/swmrychapp/*default/index.do` | 两者 302 HTTPS SSO；同一荣誉应用入口，实际项目权限未知 |
| 签到助手（244） | `/xsfwnew/sys/qdzsapp/*default/index.do#/qdgl` | `/xsfwnew/sys/swmqdzsapp/*default/index.do?wxType=1` | 两者 302 HTTPS SSO；mobile 返回的 service 没有 `wxType=1`，回调后参数保留尚未验证 |
| 心理咨询预约（248） | `/xsfw/sys/xlzxapp/*default/index.do?THEME=indigo&EMAP_LANG=zh#/mh_reservation_xs` | 目录与 PC 相同 | 302 HTTPS SSO；只查入口跳转，未访问本人/他人的心理预约、健康记录或量表 |

这些路由共实际请求 **16 个去重后的安全匿名目标**；没有跟认证后的业务动作或调用签到接口。重用同一个发布 URL 的事项分别保留语义，不额外反复请求。旧 mobile ticket 已从原站采集资料中删除，本轮未读取、发送、复用，也没有把脱敏占位符拼成 URL；“无票据基路径可达”不等于原 mobile 登录链接可用。

所有目标返回认证跳转，页面没有业务 HTML/JS/表单，因此本轮没有公开 `.do` 读取模型、查询参数或真实业务字段可继续抽取。不能从 `xsqjapp/rychapp/qdzsapp` 名称猜测提交/审批/签到 action。后续取得 root 的本人已认证只读页面后，应从它实际加载的 `pageMeta/models/api.js` 继续登记，优先列表/项目/时间窗/本人记录；申请、奖项提交、签到、住宿变更和心理预约全部另列写入边界。

另一个目录事项“心理普查测评”（247）发布目标是第三方 Credamo 问卷，与 xg 心理咨询预约不是同系统。本轮未请求问卷、填写量表或读取答卷，不将公开表单 URL 解释为学校统一账号已配置能力。

### 补充：root 独立 HTTP 认证后门户脚本

root 本轮使用来源独立、仅内存保留的 HTTP 会话请求新的学校 CAS 认证与 xg 回调，`/xsfw/sys/emaphome/portal/index.do` 返回 200“学生工作平台”；2026-10-23 20:38:06 又读取该页面实际引用的以下脚本。这个后续落地证据替代“xg 只走到匿名 SSO”的限定；**HTTP 200 门户还不是本人身份和业务会话的正向证明，各业务事项没有因此全部读取成功，也没有接入产品 adapter**。

| 资源 | SHA256 |
| --- | --- |
| `https://xg.stu.edu.cn/xsfw/sys/emaphome/public/js/portal.js` | `9e1313b69e9556a5352f474ba1fd6d6b8c2c2648ead17e635eb9d6646c80a65a` |
| `https://xg.stu.edu.cn/xsfw/sys/emaphome/templates/template2/index.js` | `a878279d54044cba6b5aa6c64bab7a09a5a38bfcaf378e6a41af94251eb57421` |

这两份门户脚本没有声明综测/奖助/住宿等业务模型，只提供门户目录与模块框架。精确接口与静态请求模板如下；`basePath/contextPath/APPNAME/LANG` 需从当前页面配置读取，不能凭脚本目录给缺失变量编造值：

| 方法/路径 | 参数和编码 | 声明结果、用途及是否可继续只读验证 |
| --- | --- | --- |
| `GET {basePath}/portal/search.do` | `keyword=encodeURIComponent($.base64_enc(输入词))`；`base64_enc` 使用 `$.base64.encode(str,true)` | 另开门户搜索 HTML，可搜应用名称；未验证它是全文学校内容搜索，不能替代业务 API |
| `GET {contextPath}/i18n.do` | `appName=APPNAME&EMAP_LANG=LANG` | 字典 JSON；脚本按 `resp.code=='0'` 读取 `resp.datas || {}`，只是界面翻译，不是业务数据 |
| `POST {basePath}/portal/grid.do` | `mapper=<实际table的mapper属性>` 加 DataTables 分页参数和 `$table.data('queryParams')` | 服务端表格数据；`serverSide:true/searching:false`。当前尚无合法 mapper 值，未猜测/调用，更不能从无表格推断空记录 |
| `POST {basePath}/portal/render.do` | 表单字段 `name=<页面实际data-mod>` | HTML 模块渲染，返回 HTML 写入目标容器；需要原页存在的模块名，未枚举/猜测 |
| `POST {basePath}/portal/changeTheme.do` | `theme=<选择值>` | 保存主题偏好，**写入，未调用** |
| `POST {basePath}/portal/changeUserType.do` | `type=<选择角色>` | 更改当前角色并重载门户，**写入，未调用**；成功条件 `resp.code===0`、失败读 `resp.msg` |

门户 `data-url` 链接若以 `/sys/` 开头，客户端前置 `contextPath`；其他发布地址直接打开。后续应沿当前获准菜单的实际业务链接 GET index 页面，再从其中的 `pageMeta.models` 或实际脚本定位业务读取接口。门户表格/目录框架不是奖助、请假、签到 API 的成功证据。

### 补充：20:43–20:44 真实业务页与通用动作协议

root 保留同一个 xg 来源独立研究会话，从公开事项地址继续只读 GET，结果为：

| 原发布目标/本轮实际路径 | 响应及验证范围 |
| --- | --- |
| `/xsfw/sys/emaphome/portal/search.do?keyword=57u85rWL` | 200“学生工作平台”，说明门户搜索路径可请求；记录没有可核实业务菜单结果，不能冒充已找到综测内容 |
| `/xsfw/sys/jxjapp/*default/index.do?EMAP_LANG=zh` | 200，实际加载奖助申请公共组件与本模块 callJs；尚未读取申请或奖项列表 |
| 勤工公开 appShow ID `2db8258911db45cda04db5ea358869c6` | 认证后实际 302 到 `http://xg.stu.edu.cn/xsfw/sys/qgzxapp/*default/index.do?THEME=indigo&EMAP_LANG=zh`；root 另以 **HTTPS 同路径** GET，200，未跟明文跳转携带认证 |
| 住宿公开 appShow ID `c9dd64e687db46acbddf8a4e7a37f544` | 实际 302 到 `http://xg.stu.edu.cn/xsfw/sys/xszsapp/*default/index.do?THEME=indigo&EMAP_LANG=zh`；另以 **HTTPS 同路径** GET，200，未发住宿变更 |
| `/xsfwnew/sys/zhcptybbapp/*default/index.do` | 当前会话仍 302 到学校 SSO。**统一账号不等于 `/xsfw` 与 `/xsfwnew` 当前业务会话可互换**；未将其判为密码错误或系统停用 |

这些页面的 title 可能为空；仅 HTTP 200 和脚本加载证明到达页面，不代表模型已返回本人业务数据。奖助页加载的公共申请组件涉及家庭成员/经济情况、论文、专利、经历和附件，存在不代表本轮读取了这些资料；没有批量抓取这些个人数据。

实际页面引用并由 root 取得的通用动作脚本：

| 官方路径（xg 主机） | SHA256 |
| --- | --- |
| `/xsfw/sys/jxjapp/*default/callJs.js` | `5d78315cee3522fc5f2bf46856cfb7d0e6be482e8a31a9463c24fef3de7b3b7c` |
| `/xsfw/sys/qgzxapp/callJs.js` | `94622985de5e21d38970510b199dd58fd34658507b65bed31bc0ccaa3670685d` |
| `/xsfw/sys/xszsapp/callJs.js` | `55c93c6c54f31c12e8b81ea3d9ab43b368b704b126fca3fffa9eb64f407d0328` |

三份脚本分别按各模块 `WIS_CONFIG.ROOT_PATH` 定位，提供相同通用动作框架，**没有给出具体奖项/岗位/宿舍查询的合法 action 列表**。明确的读取协议为：

```text
POST {WIS_CONFIG.ROOT_PATH}/commoncall/callQuery/{action}-DATAMODEL-QUERY.do
Content-Type: application/x-www-form-urlencoded

requestParams=<JSON字符串，再按表单编码>
actionType=DATAMODEL
actionName=<来自实际页面模型的action>
dataModelAction=QUERY
```

自定义查询 `mineQuery/mineQueryCallBack` 的路径为 `.../commoncall/callQuery/{action}-MINE-QUERY.do`，表单 `actionType=MINE`，其余相同。这是**语义读取但方法 POST**；本轮没有把它强行改 GET，也没有猜 action 或发出模型调用。脚本注释要求 action 已引用到 EPG 页面模型，不能把通用示例动作当现役业务接口。

声明的查询结果是 `resultCode/msg/data`（`data` 数组示例），`resultCode=00000` 成功、`10001` 参数错误、`19999` 数据库异常、`99999` 未知异常；transport handler 另检查 `data.code`（0 或缺省可向上传递，`500` 提示无权限），HTTP 401/403 则刷新或提示角色不足。**缺少 transport code 不是查询成功证明**，具体空集/分页和真实字段仍须实际只读模型验证。

写入框架 `dataModelAdd/Modify/Save/Delete`、批量操作和 `mineExcute` 使用 `.../commoncall/call...` 或 `callBatch...`，action 和参数可能修改状态；本轮只登记，未调用。下一步应从实际业务 index 的非个人配置/require 路由，沿已声明模块脚本找到具体 `pageMeta.models` 或 `mineQuery/dataModelQuery` 调用，再确定合法动作及必要的项目/学年参数。不能从模块名推导或暴力试模型路径。

### 补充：20:47 的第二轮认证与配置定位边界

root 为 `/xsfwnew` 新发 CAS 后，本轮目标仍跳回学校 SSO；这比“尚未复用 jar”更强，说明**该路径完整认证/授权尚未跑通**。未把它当网站停用、账号密码错误，也未循环重试。`/xsfw` 门户仍仅记 `landing_observed_not_identity_proven`，不得用页面脚本成功加载替代本人业务查询。

三个 200 业务 index 的公开配置给出：`APPNAME=jxjapp/qgzxapp/xszsapp`、`contextPath=/xsfw`、`RES_SERVER=https://res.stu.edu.cn`；`WIS_CONFIG.ROOT_PATH` 却是各模块的 **`http://xg.stu.edu.cn:80/xsfw/sys/{app}`**。因此不能把代码原值直接跟随为认证 HTTP 请求；本轮读到的是 root 另做的、TLS 验证的 HTTPS 同路径页面。

原页出现 `config.do/getAppConfig.do` 字符串的粗略 urljoin 结果并非完整运行请求。实际引用的 `appcore.js` 与 `appcore-min.js` 中，配置加载是 **GET `window.APP_CONFIG.SERVER_CONFIG_API`**，默认 JSON、无额外参数，解析后合并 `MODULES`；它们没有写死 `/config.do` 或 `getAppConfig.do`。故必须取得 index 中真正的 `SERVER_CONFIG_API` 拼接表达式/配置值，尤其真实 `appId`，再登记请求，不对主机根误拼接地址发请求。

| 2026-10-23 匿名 GET 的实际页面依赖 | SHA256 |
| --- | --- |
| `https://res.stu.edu.cn/fe_components/appcore.js` | `0823806a9df4803db019cee69c93717e4e74beedbc9153606562b66726231f2d` |
| `https://res.stu.edu.cn/fe_components/appcore-min.js` | `1a40ea935cf145f9670137a2b3a9e755fdc89f905eb52f33f67bbdd43dfce9e7` |
| `https://res.stu.edu.cn/fe_components/commonlib.js` | `c934a01dc7c639701a1f2f4b7bcc6da8883838801b29c0712c047ae9d91762f8` |

### 综测/xg 后续只读复核步骤：先取得配置，再取模型

本段是由上述已读取 appcore 推导的调查操作顺序，**不是尚未发生的验证结果**。由 root 统一完成一次正常 SSO 交互，研究客户端按来源隔离并仅保留内存会话；这里不接收登录凭据、Cookie、票据或完整个人页面。

1. **仅请求已发布的综测业务页**：`https://xg.stu.edu.cn/xsfwnew/sys/zhcptybbapp/*default/index.do`。当前新会话若仍返回 SSO，应记录有限跳转中的主机/路径和是否重复回到同一服务，不继续无限刷新或把另一路径会话复制进来。不能改用任何猜测的综测应用名称。
2. 如果实际返回业务 HTML，提取非个人配置白名单：`WIS_CONFIG.ROOT_PATH/APPNAME/contextPath`；`APP_CONFIG.SERVER_CONFIG_API` 的**完整值或原始拼接表达式**；`MODULES` 的 `title/route/url/hide/children/isOpenNewPage`；`APP_ENTRY/INNER_INDEX_MODE/APP_VERSION/STATIC_TIMESTAMP/RELEASE_MODE/RESOURCE_SERVER`；`THIRD_PARTY_PLUGIN` 的依赖路径；实际 `script.src/data-main/require([...])`、`require.config` 的 `baseUrl/paths/map`。不输出整份 `APP_CONFIG.HEADER`、用户配置、认证 callback 或个人信息。
3. `SERVER_CONFIG_API` 若只剩截断字符串，先列缺失变量，**不请求猜测 URL**。若能由已观察常量严格还原，按 appcore 的 GET 方式请求；记录 status/content-type、是否登录页、JSON 外层类型及菜单 `MODULES`，不把 code 缺省/HTTP 200 解释为本人身份已证实。原配置若引用 HTTP:80，只能分别记录它与已验证的 HTTPS 同路径，不能默默把会话送到明文地址。
4. appcore 的 `getModules()` 会将普通 `route` 保留首段用于路由模块；`getCurrentAppViews()` 再按真实配置构造 `(INNER_INDEX_MODE ? '../' : '') + 'modules/' + route + '/' + route`，由 RequireJS 的实际 `baseUrl/paths` 解析 `.js`。因此**模块 JS 路径可在真实 route、模式和 baseUrl 都已取得后确定**，无需枚举文件名。`url/isOpenNewPage` 模块是外部跳转分支，不能硬套此公式。
5. 只下载这些实际声明/可严格解析的模块 JS 或原页公开 `pageMeta`；登记 `models[].name/url/type`、`params/controls` 的字段名/类型/必填/分页元数据，及实际 `mineQuery/dataModelQuery` 的 action 与参数表达式。若存在 `CONFIG_READY` 动态修改菜单，先分析修改依赖，不运行所有回调或执行应用初始化动作。
6. 只挑已经确认语义只读的项目、学年、规则、本人列表模型验证；查询经 POST 发送也必须按实际语义辨别。缺失的业务项目 ID 从本人获准列表或发布配置取得，**不猜项目、不填其他学生 ID、不把空筛选扩成全校查询**。申请保存/提交、审批、签到、综测自评或加分变更、角色切换均只记录，不执行。

每个后续结果分别记录：入口落地、认证正向证明、菜单/模型声明、真正只读数据/空集及失败合同。`xsfw` 与 `xsfwnew` 的历史结果不相互覆盖，当前没有综测业务读取成功的证据。

### 补充：21:14 HTTP/HTTPS canonical 与迎新登录实现

2026-10-23 21:14:47 使用无认证客户端比较同一个已发布综测路径：

| GET 目标 | 本轮实际结果 |
| --- | --- |
| `http://xg.stu.edu.cn/xsfwnew/sys/zhcptybbapp/*default/index.do` | **301 到完全同路径 HTTPS**，未在 HTTP 收到或发送任何认证材料 |
| `https://xg.stu.edu.cn/xsfwnew/sys/zhcptybbapp/*default/index.do` | 302 到 HTTPS SSO；其 service 为 HTTPS 同路径，没有额外端口或语言参数 |
| `http://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/pages/funauth-login.do` | 301 到 HTTPS 同路径 |
| `https://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/pages/funauth-login.do` | 200“登录”，内容 SHA256 与前轮一致 |
| `https://xg.stu.edu.cn/xsfw/sys/xggzptapp/index.do?min=1` | 匿名 302 到 HTTPS SSO，service 为该旧 context 路径 |

综测 HTTPS 302 的匿名会话 cookie 作用域是 `JSESSIONID`、`Path=/xsfwnew`、host `xg.stu.edu.cn`，仅记录名称/作用域，没有记录值。因此没有证据支持“改成 HTTP CAS 回调即可”或“把旧 `/xsfw` 会话当新 context 会话”。root 后续报告：综测新票据回调仍回同 SSO；一次把 SSO 实际下发的父域 `_UT_` 收窄至 xg HTTPS 后仍相同。**这次失败不能简单归因于漏带一个 token**，也不应重复复制或尝试认证 cookie。

继续排查只比较这些非敏感元数据：同一新 context 研究 jar 是否先保留初始化产生的会话、CAS service 与回调的 scheme/host/path/查询参数名是否一致、回调前后会话是否保持/旋转、是否原样重复回到同一服务；不输出 cookie/票据值、不将凭据发 HTTP、不猜未发布服务端校验接口。不凭 302 循环认定学校不支持 HTTP 认证；当前只是该完整链路尚未跑通。

为核实迎新入口实际行为，本轮沿**已发布 HTML 和真实 loader 拼接规则**读取，而非猜脚本：

- 原页 `TG_CONFIG.pageName='funauth-login'`、`router:{'/':'funauth-login'}`、`inject:false`。
- 实际 `turing_loader_v2.js` 拼接 `pageName + path + module_name + 'Impl.js'`，带原页版本参数；`inject:false` 跳过基础同名 JS，仍加载 Impl。
- `GET https://res.stu.edu.cn/1.8.1_TR36/fe_components/turing-form/turing_loader_v2.js?v=1789792952058`：200，SHA256 `c5054520a04deb61a94dd2430ee46a54153cb025415f6856fdf7a30d83f431ed`。
- 严格解析所得 `GET https://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/pages/funauth-login/funauth-loginImpl.js?rel=1789792952058`：200，SHA256 `d2a844a296150acb671f23c49d3590339c6577653f06fafc51bf159ead4075c1`。

Impl 的静态认证/初始化合同（以下未由本调查作者发送 POST）：

| 方法与路径（xg HTTPS 主机） | 真实代码声明的输入 | 结果与边界 |
| --- | --- | --- |
| `POST /xsfwnew/sys/emapfunauth/welcomeAutoIndex.do` | 页面 mounted 时无参数 | 非空 `res.data` 会转 `refererPath` 或返回 URL；不是本人业务数据查询，不输出含认证参数的返回地址 |
| `POST /xsfwnew/sys/emapfunauth/loginValidate.do` | 自动登录传 JS 空对象，经 transform 得空表单；手工登录对象字段 `userName/password/isWeekLogin` 和条件 `verifyCode` 最终编码为表单 | `result.data.validate==='success'` 进入跳转，`reset_pwd` 进入改密界面，其他结果显示 msg/刷新图片码。**不跟随改密流程**；不能把大写 `ACCOUNTID/PASSWORD` 的页面模型字段误当此接口输入 |
| `POST /xsfwnew/sys/emapfunauth/getRefreshVerifyCode.do` | JS 空对象经 transform 得空表单 body | `result.data` 赋给图片路径；是否非空决定 `showVerifyCode`，实际是否出现挑战未验证；不是读取固定图片 URL 猜验证码 |
| `POST /xsfwnew/sys/emapfunauth/getNoLoginApp.do` | JS 空对象经 transform 得空表单 body | `result.data.code=='0'` 时读 `result.data.data`，数组项 `ENTRY/APPNAME/ICON`；只声明公开应用初始化，不遍历个人资料 |

`enterRefererPath()` 在 `forceForwardPath` 为空时，先把目标设为 `/xsfwnew/sys/emapfunauth/pages/emap-userinfo.do`；只有 `refererPath` 不是跨 context 的绝对 URL 才采用它。现页配置的旧 `/xsfw/...` 地址不含 `/xsfwnew`，因此该普通成功分支**会留在新 context 的 userinfo fallback，而非直接跳旧门户**。mounted 的 welcomeAutoIndex 又是另一个先行跳转分支；二者必须分别验证，不能只看 `defaultForwardPath` 就判断当前认证归属。

这是一条官方公开的自定义认证机制，不证明它就是综测 CAS 循环的替代方案，也未验证它接受当前校园账号或可访问综测。后续若业务页实际采用 Turing，按原页 `TG_CONFIG` 和上述 loader 解析资产；只有实际引用 appcore 的页面才按 `APP_CONFIG/RequireJS` 路由规则解析，不能跨框架套路径。

### 后续补证：奖助原页配置表达式已完整取得

root 对原 200 奖助 index 的非个人配置进行静态提取，取得：`WIS_CONFIG.PATH='/xsfw'`、`APPID='4592429014624916'`、`APPNAME='jxjapp'`，实际 `SERVER_CONFIG_API` 表达式为：

```js
WIS_CONFIG.PATH + '/sys/swpubapp/indexmenu/getAppConfig.do?appId=' +
WIS_CONFIG.APPID + '&appName=' + WIS_CONFIG.APPNAME + roleIdparam
```

本页当前解析到的目标为：

```text
GET https://xg.stu.edu.cn/xsfw/sys/swpubapp/indexmenu/getAppConfig.do?appId=4592429014624916&appName=jxjapp
```

这是从原配置严格还原的**奖助菜单配置**，不是猜根路径，也不是综测查询。`appId` 是应用标识，不是个人编号；有 `roleIdparam` 分支时必须按实际页面解析，不猜角色。后续 root 已对该精确目标 GET 得到 200、`MODULES` 三条：奖学金申请 `route=apply`、GPA（截至每年 9 月 1 日）`route=gpaxxglxg`、GPA（实时）`route=gpaxxgl`。它用 `PATH` 相对路径，不能与旧配置的 HTTP:80 `ROOT_PATH` 混淆；这三个菜单均不是综测，也不证明 GPA/申请业务数据已读到。

自定义新 context 认证研究按真实前端顺序有界进行：先读原登录页并保持当前 context 会话；`welcomeAutoIndex` 空 body 和 `loginValidate({})` 只判断现有认证状态；未成功才取得验证码图片路径，存在挑战就停止自动凭据尝试；公开应用配置可单独读取。若没有挑战且用户已明确授权，最多一次按当前页的公开 AES 参数走 HTTPS 新登录；`reset_pwd`、拒绝或发送结果未知均停止，不自动改密、不自动勾选一周免登录。实际用户名/密码不写调查脚本、日志或本文；AES 公共常量从当前官方页解析，不固定复制成产品配置。

### 更正与补证：Turing 改写了 Axios 序列化，实际是表单

root 按初次分析发出 JSON 格式的空对象初始化及一次 AES 凭据验证后，`loginValidate` 都只返回 HTTP 200 `{"msg":""}`、没有 `validate`。其余初始化的实际结果为 welcome 200 零字节、公开应用 `code=0/data=[]`、刷新图片码 200 零字节。**这些结果不证明登录成功，也不能认定密码错误或明确认证拒绝；空的验证码响应尚不足以证明完整认证协议已正确实现。**

随后补查原 loader 实际加载的完整运行时，查明初次“Axios 对象按 JSON 发”的建议遗漏了初始化改写，需要更正：

- 原 HTML **没有 `<base href>`**。
- `turing_init_v2.js` 第 16–22 行设置 `exports.axios.defaults.headers.post['Content-Type']='application/x-www-form-urlencoded'`，并将 `transformRequest` 覆盖为逐键 `encodeURIComponent(key)+'='+encodeURIComponent(value)` 后用 `&` 连接。
- `api.js:getCommonAxios()` 从同一 `exports.axios` 调用 `.create`；实际打包库 `.create` 会合并该默认配置，因此也继承表单变换。
- 该 init/boot 中没有 `baseURL` 改写，运行库只是普通 Axios 可选 baseURL 合并逻辑。JS 相对 URL 由**页面地址**而非 `api.js` 文件地址解析：`../loginValidate.do` 相对 `/xsfwnew/sys/emapfunauth/pages/funauth-login.do` 仍是 `/xsfwnew/sys/emapfunauth/loginValidate.do`。目前没有证据支持改成 `/pages/loginValidate.do`。

严格对应客户端的线请求模板为：

```text
POST https://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/loginValidate.do
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

userName=<URL编码的AES密文Base64>&password=<URL编码的AES密文Base64>&isWeekLogin=false
```

只有页面确实显示验证码时再加 `verifyCode`。Base64 中 `+ / =` 也必须正确表单编码，不能手工直接拼接。空 JS 对象经过该 transform 后是零长度表单 body，不是字面 `{}`；`welcomeAutoIndex` 原本就是未传 data 的 POST。此前 JSON 结果作为**错误编码的历史探测**保留，不能用它判断当前账号有效性。此处只完成静态诊断，没有据此自动再次发送凭据。

| 实际运行时依赖（2026-10-23 匿名 GET，`?rel=1789792952058`） | SHA256 |
| --- | --- |
| `https://res.stu.edu.cn/1.8.1_TR36/fe_components/turing-form/turing_init_v2.js` | `ba131a44d4621ef0708e2b4557d44670b4bd0669590d02e551c96bf8cdc9cd7c` |
| `https://res.stu.edu.cn/1.8.1_TR36/fe_components/turing-form/turing_boot_v2.js` | `0b862b7943a882f84e12234a74df97790b665b5ab5071c93eeb4cecba69aa2e1` |
| `https://res.stu.edu.cn/1.8.1_TR36/fe_components/turing-form/wisedu-vue/wisedu-vue.pc.min.js` | `59b1a52bb4f6dd922158a714ebe683d94c7b2d15d4b4e6a40739df6061f38df9` |

### 后续实测：正确表单得到独立认证拒绝，停止凭据尝试

2026-10-23 **13:24:57 UTC（北京时间 21:24:57）**，root 在发现完整 transform 前的一次 JSON 凭据请求仍只得到 `{"msg":""}`。这条历史结果继续归为错误输入编码，不能算成功或明确密码拒绝。

**13:27:57 UTC（北京时间 21:27:57）**，root 按刚核实的官方 transform 更正为 URL 编码表单，由 HTTP 库正确编码 AES Base64，`isWeekLogin=false`，对同一个官方 HTTPS `loginValidate.do` 做了一次凭据验证。返回明确：

```json
{"msg":"用户名或者密码错误"}
```

因此该**自定义认证入口拒绝了这次凭据验证**；研究客户端的一次性表单尝试额度已经用完，已停止所有凭据重试。**不能说用户的学校 SSO 密码错误**：相同用户授权的账号密码此前已通过中央 SSO，而这个独立入口返回了不同结果。没有对身份类型、账号同步、入口适用群体或迁移原因作未经证实的结论，也没有触发改密、注册、短信或验证码自动处理。

**13:49:17 UTC（北京时间 21:49:17）**，本地编码审计确认实际使用的 AES key 与当前页面解析值相同（仅记录布尔判据），请求确为 `application/x-www-form-urlencoded`，字段为 `userName/password/isWeekLogin`；两个密文均可正确 Base64 解码，`isWeekLogin=false`。**13:49:41 UTC** 取得页面引用的官方 `crypto-js.js`（SHA256 `c6826494432163d74fd27e78ad011a13d55e4670441cd49fc9f1e52a4afd28d9`），用纯合成 ASCII/中文输入及 16/32 字节合成 key 对照官方 CryptoJS 与 Python AES-ECB/PKCS7，**4/4 结果一致**。合成对照未使用真实凭据或服务器 key，没有再次发送真实凭据；脱敏判据存于忽略目录 `output/campus-protocol-survey/followup/crypto-fixture.json`。这只补强本地编码实现的证据，**不证明认证服务可用，也未完全排除账户、策略或其他协议差异**。

综测 CAS 回环的追加元数据已确认：初始化得到的 `JSESSIONID` 实际随回调请求发送，回调没有将它旋转，原路径中的字面 `*` 保留；一次 SSO 父域 `_UT_` 收窄到精确 xg HTTPS 主机后仍无改观。这排除了“研究客户端完全漏发初始化会话”这一简单描述，但**不证明学校端根因或账号无权使用**。不记录任何会话值或票据，也不据此继续复制认证材料。

另对 13:15 UTC 的成功门户缓存页做脱敏结构解析，得到 **19 个 `main_tab` 应用卡**及 **5 个与之重复的常用入口**，本页没有综测卡片；以“综测”关键词请求门户 search 页面虽 200，未显示应用结果。不能将它们相加成 24 个不同业务，也不能从当前账号可见菜单和一次搜索就认定综测废弃。一网通办仍发布官方综测目标；用户“可能废弃”的印象只是一种猜测，没有替代实际退役或迁移通知。

上述探测后主机曾切到 OPPO 手机热点；这个临时网络条件按其发生时间保留。用户随后明确切回校园网，恢复后的复核见下一段，不能继续把旧热点条件当当前事实。

### 校园网恢复后的综测复核与官方入口查找

用户明确切回校园网后，2026-10-23 **13:40 UTC** 记录到网络配置名 `stu.edu.cn`，**13:41 UTC** 宿舍/水电的 SSO GET 续票均恢复。这里结合用户的接入说明与业务实测，不单凭配置名推断物理网络。

**13:43:33 UTC（北京时间 21:43:33）**，root 在恢复后的路径给官方综测 service 再发一次新的 SSO 票据，**没有重新提交账号密码**；回调仍为 302 到同一个 SSO。因此综测的当前调查结论仍是完整认证链路未跑通，不能再仅以手机热点解释；没有突破此前自定义认证表单的一次尝试限制，也没有把旧消息当新的密码拒绝。

为查找是否有另一个正式入口，本轮只检索校方公开来源（`stu.edu.cn` 及学校部门子域），关键词覆盖“综测/综测系统/综合测评系统/综合素质测评/综合素质评价”“操作/登录/评价工作/2025/2026/2025-2026学年”，再匿名读取能核实的原文。未登录 OA、未查个人名单或任何私人会话。**截至本轮，没有找到能证明替代当前一网通办综测 URL 的新官方操作入口，也没有找到该系统退役通知。**

| 可引用的校方公开来源 | 日期与实测 | 对入口问题能证明什么 |
| --- | --- | --- |
| [一网通办“本科生综测”事项](https://service.stu.edu.cn/fe/site/matterDetails?app_id=240) | 本轮匿名详情已取得，目标见 `service-matters.csv` | 仍发布 `/xsfwnew/sys/zhcptybbapp/*default/index.do` 和 mobile 版本。发布链接不等于当前业务可用，仍是应优先核实的正式来源 |
| [学生处《关于开展2024-2025学年本科生奖学金评选工作的通知》](https://xsc.stu.edu.cn/News.aspx?ID=13852) | 原文发布日期 **2025-10-13**；本轮本机匿名 GET 200 | 指向 xg 的“奖惩服务→奖学金”，并引用综合素质评价结果。这与已读 jxj 菜单相符，**不是 2026 综测操作指南，也不是综测替代系统** |
| [学生处《全日制本科学生综合素质评价办法》PDF](https://xsc.stu.edu.cn/ckeditor/userfiles/file/20251225/20251225164334_8747.pdf) | 本轮 GET 200，9 页，SHA256 `68ed9de9edc10382353b9030df8993874bb828ae4832d0861b13db287ae074b0`；URL 路径为 2025-12-25，PDF正文未标明确切发布日期 | 规定秋季评价上一学年、学院组织审查评议/公示/上报，全文无系统 URL。**上传目录日期不能冒充 2026 新版政策或新登录指南** |
| [工学院、敬一书院“破局校招・赋能职场”工作坊通知](https://eng.stu.edu.cn/info/1081/13761.htm) | 原文署名日期 **2026-05-13**、活动 2026-05-18；本轮匿名 GET 200 | 当期仍表述综测活动加分，未给综测系统 URL。只证明评价用途仍被使用，不证明特定应用当前可登录 |
| [工学院、敬一书院2025-2026学年“五色双院”第二课堂立项通知](https://eng.stu.edu.cn/info/1081/10791.htm) | 原文署名日期 **2025-11-06**；本轮匿名 GET 200 | 活动在“到梦空间”登记并按综合素质评价办法加分。**活动登记来源与年度综合评价系统分开**，不能据此用到梦空间替代综测接口 |

学生处首页本轮可匿名读取，含 2026 年通知，但首页出现近期通知不意味着旧奖学金通知已更新成 2026 内容；没有把网页抓取日期、搜索引擎抓取时间、附件目录时间当发布日期。一次公开列表读取超时后未无限重试。仍缺少的是当前学年正式综测办理通知/操作手册中的明确入口或学校发布的迁移/退役依据，而非更多密码试探。

### 第二轮只读深查：登录类型、迎新用途与正式中间入口

本轮没有再发送用户密码。先核对公开脚本，再仅沿已声明的模板、字典及跳转路径做有界匿名 GET；root 仍单独管理中央 SSO 和各业务的内存会话。

`turing_boot_v2.js` 实际按 `pageName + path + module_name + '.html?' + module_name` 加载视图。因此由当前 `TG_CONFIG` 严格解析得到的模板为 `GET https://xg.stu.edu.cn/xsfwnew/sys/emapfunauth/pages/funauth-login/funauth-login.html?funauth-login`，2026-10-23 **14:06:57 UTC（北京时间 22:06:57）** 返回 200、21761 字节，SHA256 `fc22eea1aa28b73a42c4a4eaaba6b51db0d9f11bfe138f041a515a103d2f2757`。模板与 Impl 合起来明确了：

- `loginType=1` 显示账号密码表单，`loginType=2` 显示“游客服务”；仅在 `noLoginApps.length>0` 时显示这两个标签。它是界面区块切换，**不是学生/教师或本科/研究生身份选择**。
- `handleSubmit` 没有把 `loginType/USERTYPE` 作为认证参数发送，输入仍是既有的 `userName/password/isWeekLogin` 及条件验证码。没有发现由这个切换触发的 CAS 前置/中间跳转，不能凭变量名补一个身份参数。
- 公开 `pageMeta` 的 `User_validate_info` 模型虽声明 `USERTYPE/USERSTATE` 字段，但没有内嵌枚举。仅匿名 GET 它实际声明的 `/xsfwnew/code/91c0d3ea-7efc-4b5c-b021-f3d211f5291c/userType.do`、同目录 `userState.do`，**14:08:59 UTC** 均返回 200、零字节、非 JSON；未取得类型含义，未调用 `dlyz/query_user_match` 等账号模型。字段存在不证明当前账户属于某类型，更不授权账号枚举或身份值试探。

`enterRefererPath()` 实际声明的 fallback `/xsfwnew/sys/emapfunauth/pages/emap-userinfo.do` 于 **14:08:04 UTC** 匿名 GET 仍返回 302 到 HTTPS SSO，service 是这个精确路径、没有其他查询参数；`funauth-login.do` 则仍 200。**公开登录页可读取不等于新 context 已认证，也未发现可据此替代综测 CAS 的桥接步骤。**模板和字典的脱敏证据留在忽略目录 `funauth-template-receipt.json`、`funauth-dictionaries-anonymous.json`、`xg-context-public-followup.json`。

官方用途方面，[研究生院2025年新生报到指南](https://www.gs.stu.edu.cn/list/61/post/5bf0f08b-9380-444f-85a7-60fcf9d5c0a3)（发布日期 **2025-08-28**，本轮经网页读取）说明新生使用随录取通知书寄送的校园网账号密码登录新生预报到系统，并链接附件5操作手册；与前文 2024 手册给出的 funauth 入口形成**迎新用途证据**。本机尝试正常 TLS 读取这篇指南时遇到 `CERTIFICATE_VERIFY_FAILED: certificate has expired`，未绕过验证；2025 docx 附件未提取，不能声称其仍采用同一精确 URL。上述公开来源**不证明 funauth 专供新生，也不证明它是当前在校本科生综测的认证入口**；当前模板没有综测业务名称或导向该应用的配置。

现有授权门户缓存还提供了可核实的正式中间链接，而非猜测新路径。**13:36:48 UTC** 的 `application_card_context` 把“迎新服务”关联到 `/xsfw/sys/emaphome/appShow.do?id=a35adda51bef472f9eeb9f5110a1fedc`，“学生请假”关联到 `id=cb53e8ad4b1d4b5fb2130998717806fc`，“第二课堂”关联到 `id=dd86fdaa3b434776be7c2cf610061fda`，这些是应用标识，不是人员标识；第二课堂标签不能当成综测替代品。root 随后在来源隔离的研究会话中得到以下只读结果，均未再提交密码：

| 2026-10-23 UTC 时间 | 精确目标或动作 | 实测结果与边界 |
| --- | --- | --- |
| 14:09:56 | 旧 `/xsfw/sys/emaphome/portal/index.do` 续票 | 200 学生工作平台，仍为 19 个应用；没有因此证明新 context 已认证 |
| 14:10:44 | GET 上述已发布“迎新服务” `appShow.do?id=a35adda51bef472f9eeb9f5110a1fedc` | 302 到 `https://xg.stu.edu.cn/xsfwnew/sys/yxapp/*default/index.do`，无 query。**正式存在旧门户到新迎新应用的链接**，但未证明交接后认证成功；响应 `_ht` cookie 元数据为 host `.xg.stu.edu.cn`、Path `/xsfw/sys/null`，仅记录名称和作用域，不记录值，不把 `null` 路径定为根因 |
| 14:11:10 | 官方综测目标再次使用新 SSO 票据 GET 回调 | 仍 302 回同一 SSO service；没有重新发密码 |
| 14:11:11 | 分别以实际初始化 302 的 service 为学生请假 `/xsfwnew/sys/xsqjapp/*default/index.do`、userinfo fallback 续票 | 两者均在新票据回调后 302 回各自相同 SSO service；详情见忽略目录 `followup/observations.jsonl` 的 `context_comparison` |
| 14:13:37–38 | 同一个已登录旧 xg 客户端实际跟随“迎新服务” `appShow` 的官方 302，再为 `/xsfwnew/sys/yxapp/*default/index.do` 取得新 SSO 票据并 GET 回调 | 初始化使用不带票据的旧 portal Referer，回调 Referer 为 `https://sso.stu.edu.cn/`，仍 302 回 yxapp 对应的同一 SSO service。旧/新 context 的 `JSESSIONID` 按原 cookie 作用域自然保留；未复制中央 cookie、未强行搬用旧会话、未重发密码 |

所以当前失败范围**至少涉及新 context 的综测、学生请假、userinfo 和迎新四个精确路径**，不能继续描述成“只有综测这一个应用不接受票据”；仍不能据此确认学校端根因、权限不足或新系统停用。最后一次实际跟随正式门户 appShow 的对照排除了“完全没跟正式中间入口”这个简单遗漏，不能由此宣称完整浏览器请求头等价或查明服务器根因。

为核对 HTTP 请求是否遗漏官方点击步骤，复查两份实际门户脚本：`template2/index.js` 第 45–61 行的 `[data-url]` 点击只取 `data-url`，仅在以 `/sys/` 开头时前置 `contextPath`，再按 `data-target` 选择 `location.href` 或 `window.open(url)`；读取但未使用的 `data-apptype` 不参与 URL。该处理器**没有附加参数、认证 AJAX、cookie 写入或先走 HTTP**，`portal.js` 也未声明这些 appShow 导航步骤。因此对现有 `data-url` 做 GET 与该处理器的**目标和方法**一致；Referer 已做上述有限对照，浏览器其他请求头、原生事件和完整会话上下文是否相同仍未知，不能仅凭静态脚本宣称两者完全等价。未执行角色切换、猜测认证参数或改写 `_ht`。

## 2. dorm 与 power：同用学校 SSO，不是同一个业务

初轮两个 HTTP 根入口均返回 302，业务 service 为各自 HTTP `default.aspx`。
后续对照确认 **dorm 的 HTTPS 原入口会生成 HTTPS service，且已认证读取成功**；power 的
HTTPS 端口拒绝连接，本次经用户单独允许官方 HTTP 回调后读取成功。没有沿用 JW 的
HTTP 兼容权限，也没有借用宿舍报修 `repair` 或其他业务的会话。完整时序与协议见
[宿舍与水电补查](dorm-utilities-followup.md)。

[2025 智慧校园简介](https://zs.med.stu.edu.cn/upload_files/file/20250801/1754016918198845.pdf)把“学生事务及宿舍管理系统”列到 `xg`，把水电管理列到 `power`；因此旧 `dorm` 虽仍跳 SSO，不足以证明它仍承办所有宿舍事项或已经迁移。

[东海岸校区 2024-01-15 水电通知](https://stuecc.stu.edu.cn/info/1027/1395.htm)确认 `power` 可用校园网账号自助缴费，允许设置代理缴费，涉及欠费、扣款、恢复供电。历史通知的校区规则不能直接当作当前桑浦山规则。本次已取得读数、历史账单的实际数组结构，以及原 WebForms 表单的未缴费筛选和有效空结果；没有打开自助缴费页、设置代理或进行支付/退款。

宿舍已读三个实际导航及表头，并在内存完成一份本人姓名关联核对；已观察 302 回 SSO 后续票恢复。水电已验证正常查询、筛选与空数组；14:06:06 UTC 新 GET 后的本地 AST 复核确认历史 25 行各有 12 个位置，2/3/4 为省略元素，14:09:55 未缴费新查询的 4 行亦如此。早先“9 列与 12 字段冲突”是临时调查器过滤稀疏空槽的误计，现已撤回；缺失位置不能补 0、当作显式 `null` 或使后续字段左移。14:12:40 公开脚本复读再次确认字段及列头，未更新本人账单时间；最终对应表与网络/本地时序见[补查报告](dorm-utilities-followup.md)。仍需补完整身份绑定、金额/单位/分摊语义、分页与完整范围，以及更全面的失效判据。只登记结构，不保存隐藏状态值、个人页面或账单。

## 3. smartcard：独立查询密码与图片验证码

公开 200 页面 title 为“校园卡查询系统”。登录表单 `method=post`，JS 校验成功后把 action 设为 **`loginstudent.action`**：

- `name`：登录标识。
- `loginType`：`2` 学工号、`1` 账号、`3` 手机号。
- `passwd`：6 位查询密码；页面 JS 只检查长度，不证明服务端密码策略。
- `rand`：图片验证码，最大 4 字符；图片由脚本声明 **`getCheckpic.action?rand=<random>`**。
- 另有隐藏 `userType` 和图片提交按钮；未记录隐藏值，未发送表单。
- 账号类型 `1` 在客户端限定数字；不能据此自行生成/试探账号。

同一页面还有查询通知表单：`method=post`、JS action=`xxsearch.action`，字段 `searchnotices/searchtype/lmid`；`searchtype=1` 标题、`2` 内容。栏目链接使用 `GET xxsearch.action?lmid=...`。二者是**同一路径，不同方法和参数**；本轮仅观察声明，尚未提交搜索表单或核实两种调用的返回合同。

| 公开入口/声明 | 用途和当前证据 |
| --- | --- |
| `homeLogin.action` | 本轮 200：首页、栏目、查询登录、失卡/寻卡公开片段；未保留名单作为业务证据 |
| `xxsearch.action?lmid=<栏目ID>` | 页面链接：通知/指南/制度/表单，列表分页尚未核实 |
| `ggxxfb.action?lmid=<栏目ID>` | 页面“更多”链接，未逐页遍历 |
| `managerOneGgxxfb.action?fbxxid=<页面给定公告ID>` | 本轮抽查两篇官方公告正文均 200，HTML 标题/发布时间/正文/附件链接可读 |
| `getfjnr.action?fjid=<公告中给定附件ID>` | 正文给出的附件下载；未遍历下载或猜 ID |
| `browscm.action?id=1/2/3` | 首页图片导航声明；具体业务未核实，未猜更大 ID |
| `accountlossList.action`、`nFixcardAllList.action` | 首页公开失卡/寻卡列表导航，不是本人挂失提交 API，未进一步采集个人名单 |
| `indexmercLogin.action` | 商户入口，未登录，不能套学生认证 |

抽查原站[《一卡通常见问题及解答》](http://smartcard.stu.edu.cn/managerOneGgxxfb.action?fbxxid=4a401f3d363cedfa01363d08581d0001)确认：本人余额/消费流水、自助挂失、查询密码维护分别存在；当前页面登录流程包含验证码。**它的查询密码是独立凭据，不应拿学校统一密码尝试。**未调用任何挂失/改密/充值。

另一篇当前官网[《关于启用汕头大学微校码的通知》](http://smartcard.stu.edu.cn/managerOneGgxxfb.action?fbxxid=40288d299cc6df0d019dfaa6775d0001)介绍微信领取虚拟校园卡和校园支付。它说明另有微信产品入口，不证明旧网页能取得微信授权或支付接口。首页和正文显示日期存在差别，应保留原始来源，不用猜发布日期替换。

响应错误/分页/本人读取范围仍需用户私密完成该独立登录后验证。公开 HTTP 首页可读也不等于密码应通过 HTTP 自动提交。

## 4. ehall/yy-sys：OIDC + GraphQL 预约系统

### 路径与认证

`/yy-sys/pc/home` 和根 `/taskcenter-v4/` 是不同前端应用。预约页内联 `window.__env` 的声明：

| 项目 | 官方客户端声明 |
| --- | --- |
| OIDC authority | `/sso/oauth2` |
| authorization/userinfo/JWKS | `/sso/oauth2/authorize`、`/userinfo`、`/jwks.json` |
| response type | `id_token token`；不是本轮实测授权码登录 |
| callback | `/yy-sys/oidc-callback?retUrl=<当前页面>` |
| silent renew | `/yy-sys/silent-renew-oidc` |
| scopes | `data openid process task app submit process_edit start profile` |
| 主业务 GraphQL | `/bus/graphql/me` |
| 其他网关 | `/bus/graphql/builtin`、`/bus/graphql/iam`；`/yy-sys/graphql_public` |
| REST 配置 | `/yy-sys/api`，Axios 10 秒超时 |
| 上传 | `/yy-sys/upload_file`，写入入口，仅静态记录 |

客户端在 GraphQL/REST 请求带 `Authorization: Bearer <access_token>`；此部署声明 `id_token_hint='parameter'`，GraphQL fetch 会在 URL 添加 `id_token_hint`。后续实现不得把完整请求 URL、令牌、回调 fragment 写日志。

脚本还包含按系统配置 `encrypt_api` 启用的应用载荷 AES-CBC 包装：从公开 OIDC client ID 派生参数，用动态对象键包裹请求，收到响应再解包。这是**客户端可选分支**，匿名配置没有返回实体，未证明当前启用，不应预先硬编码成必要条件。

### 本轮实际只读合同

1. `GET /yy-sys/api?api_type=get_sys_settings` 返回 HTTP 200 JSON：

   ```json
   {"success":true,"errno":0,"error":"执行成功","total":0,"page_number":0,"total_page":0,"next_token":null,"entities":null,"type":null}
   ```

   `entities:null` 不是“学校未配置预约平台”的证据。
2. 发送客户端原有 `findResourcesTypeAllByAccountForDisplay` query 到 **POST `/bus/graphql/me`**，不带身份、无 mutation，返回 HTTP 200：

   ```json
   {"errors":[{"message":"无效的请求，错误的请求格式或参数。","extensions":{"code":"INVALID_REQUEST","detail":"access_token required","prompt":"无效的请求，错误的请求格式或参数。"}}]}
   ```

   响应中另有一次性关联编号，未记录其值。没有 `data`，不能按 HTTP 200 当成功或空列表。

### 已查到的读取功能与请求字段

以下均来自本轮下载的官方主 bundle/首页与本人预约 chunk，**业务成功响应未验证**。GraphQL body 按 Apollo 模式 `operationName/query/variables`；URL 仍需认证材料。不要把“声明返回字段”当本轮已读到个人数据。

| 操作 | 参数 | 客户端声明结果/含义 |
| --- | --- | --- |
| `findResourcesTypeAllByAccountForDisplay` | `filter:ResourcesTypeFilterMap` 可选 | 分类数组：`id/resources_name/resources_tag/state`，预约限次/时长/取消限制/签到规则/验证码开关等 |
| `findResourcesTypeAllByAccount`、`findResourcesTypeAllWithResourcesByAccount` | 可选 filter | 本人可见类别/类别带资源，与管理员全部类别不可替换 |
| `findResourcesAllByAccount` | `first/offset/typeId/typeName/resourceName/bookDate/bookStartTime/bookEndTime/item_name/order_by/cur_language/filter`，另有周期预约条件 | 首页按当前账号权限筛选资源；实际调用传 `typeId/bookDate/...`；组件把完整返回数组再做前端分页，不能一律套 connection |
| `findResourcesAll` | `first:Int/offset:Int/filter:ResourcesFilterMap` | connection：`edges[].node/cursor`、`pageInfo.startCursor/endCursor`、`totalCount`；资源名、校区/楼/层、容量、管理单位、开放规则、时段、禁约配置、审批要求、图片 |
| `findResources`、`findResourcesWithAuth` | `id:ID!`、可选 filter | 单资源详情；需要先从本账号资源列表取得 ID，未任取 ID 测试 |
| `findResourcesTimeSlotByResourcesIdAndDate` | `resourcesId:String!`、`date:Date!` | `id/resources_id/kssj/jssj/canAppointmentNumber/canAppointmentNumberDesc`；不由总容量推测剩余数 |
| `findResourcesNoReservationTimeSlotByResourcesIdAndDate` | `resourcesId:String!`、`date:String!` | `book_date/start_time/end_time/is_allday/reason_cn/reason_en`，禁约时段 |
| `findResourcesBookingDetails` | `id/yearMonth/filter` | 月预订详情；未实测 |
| `findResourcesListBookingDetails` | `resourceIdList:[ID]!/startDate:String!/endDate:String!/filter` | 多资源日期范围详情；范围上限未实测 |
| `findResourcesFieldSettingForAppointment` | `resources_id:String!` | 每个资源的动态申请字段；不能只凭固定演示表写死 |
| `findAppointmentInformationAllForAccount`、`findAppointmentInformationAllForSelf` | `first/offset/after/filter/appointmentDate/only_flow/updateAppointmentState` | 本人预约 connection；PC chunk 有 first=10、offset=10*(page-1)，处理中请求显式 `updateAppointmentState:"0"` |
| `findAppointmentInformation` | `id:ID!/filter` | 本人获准记录详情；字段含 `state/appointment_state/audit_status`、资源、日期、起止时间、审批流、取消/退回原因、签到状态；几个状态不可混成一个 |
| `findFiveNotice/findNoticeAll/findNotice` | 全部列表有 first/offset/after/filter；详情 id | 预约平台内公告，不是学校 OA；正文/时间/类别等静态可见字段 |
| `findMyCollectionByAccount` | 当前账号、keyword | 本人收藏，仅静态调用证据；添加/删除收藏另属写入 |

客户端在若干列表里用 `result || []`，connection 里常检查 `result` 后取 `edges[].node`。这些是页面容错写法，**未实测空集究竟为 `[]/null/edges:[]` 或是否 partial data+errors**。分页须按实际操作分别处理，不能看到名称都用 first/after。

### 方法、请求体与可继续复核的模板

所有上表 GraphQL 请求均为客户端 Apollo **POST** 到 `https://ehall.stu.edu.cn/bus/graphql/me`（`Content-Type: application/json`）；鉴权位置来自页面配置及 fetch 包装，不能把令牌放进 MCP 参数。常规正文为 `{"operationName":"<声明名称>","query":"<原模板>","variables":{...}}`。

下例时段请求体的 operation、变量类型和 selection 来自主 bundle，**只是静态模板，没有向学校发送这份带资源 ID 的请求**；占位符必须由本人获准的资源读取结果填入：

```json
{
  "operationName": "findResourcesTimeSlotByResourcesIdAndDate",
  "query": "query findResourcesTimeSlotByResourcesIdAndDate($resourcesId: String!, $date: Date!) { findResourcesTimeSlotByResourcesIdAndDate(resourcesId: $resourcesId, date: $date) { id resources_id kssj jssj order del create_time canAppointmentNumberDesc canAppointmentNumberDesc_en canAppointmentNumber } }",
  "variables": {"resourcesId": "<本人列表给出的资源ID>", "date": "<YYYY-MM-DD>"}
}
```

本人预约 chunk 的实际调用变量模板另有：

```json
{
  "operationName": "findAppointmentInformationAllForAccount",
  "variables": {
    "first": 10,
    "offset": "10 * (page - 1)，实际发数字",
    "only_flow": "1",
    "filter": {
      "state": {"eq": "0"},
      "audit_status": {"in": ["1", "9"]},
      "resources_name": null,
      "appointment_date": {"order": "<组件当前排序>"}
    },
    "updateAppointmentState": "0"
  },
  "query": "<主bundle中同名完整query，按表中字段和类型>"
}
```

这是“进行中”的一个客户端分支，不是所有状态的固定筛选；主 bundle 同名 schema 参数为 `first:Int, offset:Int, after:String, filter:AppointmentInformationFilterMap, appointmentDate:[String], only_flow:String, updateAppointmentState:String`。最后三种状态字段不能凭数字外观自行解释；后续先核实页面标签与真实返回对应。

2026-10-23 唯一实际发送的 GraphQL 请求为匿名 `findResourcesTypeAllByAccountForDisplay`、`variables={}`，用主 bundle 中该名称的完整 query；响应如上（缺 access_token），没有 ID 参数或个人查询。原有公开 JSON 错误已保存在忽略输出的脱敏记录中。

### 只记录、不执行的写入和挑战

- `saveAppointmentInformation(captchaId,captchaCode,model:InputAppointmentInformation!)`，以及 `saveAppointmentInformationAll`（时段 ID/多日）、`...ForCyclicity`、`...ForBatch`：预订/审批提交。声明返回 `errcode/msg/msg_en/ids/appointmentId/processURL/auditStatus`。
- `updateAppointmentInformationState(id,state,reason,dataSource)` 及批量/管理变体：状态更改/取消；实际合法枚举和影响尚未核实。
- `selfSignInOrSignOut/updateAppointmentStateForSelfSign/updateSignOutStatusForSelfSign`：签到/签退。
- `saveAppointmentRemark`、收藏变更、上传、资源/权限/访客管理：都可能改变数据，不属于本次只读调查调用。
- **不能仅按 GraphQL `query` 判断只读**：脚本另有 `query signIn(id)`、`sendMessengeVerificationCode(resourceId,bookDateList)`、`generateCaptcha`；前两者明显可能产生状态或发送消息。预约列表还带 `updateAppointmentState` 控制字段，本轮未进行认证后列表调用。
- 老图片码和新挑战组件均存在；资源有 `open_captcha_verify/open_frequency_verify`。未用真实预约触发，不能断言所有资源必有或必无图形挑战。
- 处理脚本错误：REST 拦截器区分 HTTP 400/401/403/404/405/408/5xx；GraphQL 另识别 `OIDC_BC_LOGOUT`（触发重新认证）和 `PERMISSION_DENIED`。还需识别本轮实际的 HTTP 200 + `INVALID_REQUEST`。

主 bundle 抽取到 256 个 query/mutation 字符串，去重后 255 段，含大量厂商访客/管理员/其他学校主题代码。**这不是 255 项汕大学生功能。**本文件列出与学生查询相关的实际声明；未把管理路由加入待接 MCP 清单，未进行 schema introspection。

## 5. booking、SLC 与 classroom

`booking` HTTP 根先 302 HTTPS，HTTPS 返回旧导航 HTML，并声明 1 秒后转 HTTPS `/Default.aspx`；后者 302 的 Location 是 `http://sso.stu.edu.cn/login?service=https://booking.stu.edu.cn/Default.aspx`。
这只是服务端发布链路。本轮没有自动跟 HTTP SSO，也没有输入密码；后续应明确验证官方 HTTPS SSO 入口能否承接该 service，而不是把明文 SSO 当默认登录。

首页栏目：SLC 预约、海洋生物研究所、校内活动、校内场馆（页面例举图书馆演讲厅/研讨室、科学楼/行政中心会议室）以及户外装备、教工食堂/劳务补助等管理项目。除了两个 SLC/IP 链接，其余都指向 `Default.aspx`。**它是多业务旧导航，不能把 `booking` 简写为 SLC，也不能把页面上的教职工业务当学生可用。**

导航公开的 `slc` 主机当前解析失败；旧 `192.168.12.151/slc/` 当前 400 Invalid Hostname。不能据此替换域名、猜 Host 头或宣称新 ehall 已全量承接。

`classroom` 则直接声明自己的 CAS service `https://classroom.stu.edu.cn/Index.aspx`。认证前只有跳转 HTML，无 AJAX/API 线索。与 ehall 的资源、课程教务课表、SLC 学业互助都分别记录；当前尚无教室资源或申请接口实证。

## 6. ELC/CILL MRBS 预约

实际只读跳转链：

```text
GET http://my.stu.edu.cn/courses/elc/blocks/mrbs/web/index.php
301 https://my.stu.edu.cn/courses/elc/blocks/mrbs/web/index.php
303 .../day.php?day=23&month=10&year=2026
303 https://my.stu.edu.cn/courses/elc/login/index.php
302 https://sso.stu.edu.cn/login?service=https://my.stu.edu.cn/courses/elc/login/index.php&gateway=true
```

`day/month/year` 是本轮跳转中的真实参数，不能提前猜测上游还提供哪些 `week/month/report/edit` API。登录页声明 phpCAS 1.3.3/CAS 2.0；未将既有 MySTU 加密会话读出或复制到这里。

[ELC 官方 CILL 指南](https://elc.stu.edu.cn/PDF/CILL.pdf)描述个人语言学习规划、语音、写作、演讲、雅思等辅导预约及教师空间预订；这些说明用途，未证明当前时段/名额/教师安排。指南还涉及资料借阅和活动，不代表它们都走 MRBS。需要登录后读取实际区域/房间、日期切换和本人记录，记录预约资格和取消规则；本次没打开编辑/删除/确认按钮。

## 证据文件与复查起点

### 补充导航历史入口：sao、dy、qipu、sgren

来源为维护的 `docs/verification/2026-10-22-campus-entries.csv` 中明确发布的 URL，本轮逐个请求其原路径；不是按主机字典猜接口。

| 发布 URL/旧标签 | 本轮响应 | 功能/API 证据与边界 |
| --- | --- | --- |
| `http://sao.stu.edu.cn/`（学生事务/新生入学） | 301 HTTPS 同路径，HTTPS 404 `HTTP Error 404. The requested resource is not found.` | 未提供可继续跟进的菜单/脚本；不推断已搬到 xg |
| `http://sao.stu.edu.cn/index_rxzn.aspx`（新生入学指南） | 301 HTTPS 同路径，HTTPS 原路径亦为 404 | 本轮核查到具体路径，不沿用旧 CSV 只检查根路径的证据；没有恢复出旧指南接口 |
| `http://dy.stu.edu.cn/`（德育网） | 名称解析失败 `getaddrinfo failed` | 当前网络无法进一步看页面；不称永久下线/迁移 |
| `http://sgren.stu.edu.cn/`（曙光助学工程） | 名称解析失败 `getaddrinfo failed` | 同上，未猜新域名或入口 |
| `http://qipu.stu.edu.cn/`（导航旧称“启璞计划”） | 200，**实际 title 为“汕头大学商学院 EE 项目部”** | 当前内容为公开/定制课程、师资、新闻、管理新知、证书查询和试听报名，不能继续将它归类为启璞助学申请系统 |

qipu 已按首页给定链接验证的接口：

- `GET /sd_course.php`：200 HTML 公开课程；部分课程详情直接发布到 `http://biz.stu.edu.cn/edp/sd_news_detail.php?id=...`，本轮未跨站调用。
- `GET /sd_news.php` 与其原页给定 `?page=2`：200 HTML 新闻列表，标题/日期/摘要/详情链接；前页给出 10 条、页码与尾页 `?page=30`。这不是 JSON API；未分页全站抓取。
- `GET /sd_news_detail.php?id=334`：用原列表明确给出的公开新闻 ID 抽查，200 HTML 正文。不能用此证明任意 ID/草稿均可读。
- `GET /sd_query.php`：200 证书查询空表，声明 `POST /sd_query.php`、字段 **`sn`**，列头“姓名/班级/授课日期/证书编号”。未输入任何证书号、不查他人资料，查询成功/未命中/错误合同未核实。
- “试听报名”链接直接到两个已发布 `mikecrm.com` 第三方表单地址；**不是学校 CAS，也没有发报名**。未将第三方表单当统一账号可配置业务。
- 当前首页所见新闻最新条目标 2022-11-15；只描述本页内容，不证明学校项目永久停办。主页/栏目匿名可读不代表证书私密数据可任意查询。

临时匿名页面结构和官方 JS 放在被 Git 忽略的 `output/campus-protocol-survey/student-booking/`。输出 HTML 的 hidden/password 值已删，URL 中认证参数脱敏；不把原站公开失卡名单写进文档，不保留认证票据。本文件记录可复查的官方路径与重要脚本 SHA256，文件名不应长期硬编码为产品接口。

| 官方脚本 | 本轮原始内容 SHA256 |
| --- | --- |
| `/yy-sys/static/js/app.318b6257.js` | `cb9312d4fe755e4474444f09fca6be41e74f8b6e836a96fe78f04d00c698cd0b` |
| `/yy-sys/static/js/chunk-2d0c91e5.b6ea83e5.js`（首页主题路由） | `8cb6ea5d2cb0b3520790fa48f8d01f5f247921c444759d7d56d96caaeebcb55d` |
| `/yy-sys/static/js/chunk-93e9da0a.dda1f120.js`（Basic 首页/资源） | `b3cdf4168d35e4f5e5111998df4cba28277b0b205efc4e9afe30141e90993ace` |
| `/yy-sys/static/js/chunk-2cb6d238.5b553d89.js`（本人预约） | `1c438b6d319e36c0c11c16687b29aa4c311e2a2a5582ecbbaa5fb04d1a5fde2e` |
| `/xsfwnew/sys/emapfunauth/pages/funauth-login/api.js` | `fdd1a88bc90a0d45d6eea0d7bd063ab88bc5a3876019a0e535ab355559693bfb` |

另取 `/taskcenter-v4/static/js/app.js?V=null` 得 SHA256 `55b580f588fa8b60b46f939965abf066f9e84040d466974052445475f1eba323`，仅用于区分根办事大厅应用。动态 chunk 地址按主 bundle 的 webpack 映射读取；不存在的资产响应不用于判断功能停用。

未核实项仍明确保留：dorm/power/classroom/xg 常规门户认证后业务 API，smartcard 独立登录成功，ehall OIDC 完整回调/真实资源权限与返回合同，booking 当前启用业务，ELC MRBS 登录后的只读日历。**本轮已完成各入口的匿名与静态协议摸查，但没有“全部接口已跑通”的结论。**
