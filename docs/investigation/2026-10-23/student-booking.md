# 学生事务、宿舍、水电、校园卡与预约入口协议调查

调查日期：2026-10-23，北京时间约 20:00 起；20:30 补查公开事项路由，20:38 后补查 root 授权认证所得页面的脚本。本轮在本机当前网络路径上使用直接 HTTP 客户端，`trust_env=False`、TLS 正常校验、单次连接 5 秒/请求 10 秒量级；未改代理、DNS 或证书。入口逐一请求，依据页面实际链接、脚本声明和学校指南跟进；连接配置名不能证明物理网络位置。

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
| `/xsfwnew/sys/emapfunauth/loginValidate.do` | 验证登录；`getCryptoPwd` 将密码做 AES-ECB、Pkcs7 后返回字符串 | 公共辅助方法使用 POST；实际参数对象和成功凭据交换未核实，没有调用 |
| `/xsfwnew/sys/emapfunauth/getVerifyCode.do`、`getRefreshVerifyCode.do` | 图片验证码/刷新 | 静态 URL，未调用；不能自动识别或绕过 |
| `/xsfwnew/sys/emapfunauth/getVerifyReciever.do` | 可用邮件/SMS 接收方式 | `getAvailableReciverService` 明确 POST；未调用 |
| `/xsfwnew/sys/emapfunauth/sendVerifyCodeService.do` | 发送验证码 | 静态声明，未调用，不因名字有 query/read 就当只读 |
| `/xsfwnew/sys/emapfunauth/modifyPassword.do`、`modifyPasswordByUser.do` | 密码维护 | 写入，未调用 |
| `/xsfwnew/sys/emapfunauth/getNoLoginApp.do` | 未登录应用初始化 | 静态声明，未调用，真实响应未核实 |
| `/xsfwnew/sys/emapfunauth/pages/funauth-login/dlyz.do` | 页面模型 `ACCOUNTID`、`PASSWORD`；声明返回 `WID/ACCOUNTID/ACCOUNTNAME/CELLPHONE/EMAIL/USERTYPE/USERSTATE/EXPIREDATE` | 页面元数据 type=list，不是匿名可读证明；未调用 |
| 同目录 `query_user_match.do` | `ACCOUNTID/USERID`，声明 `result:int` | 未调用，不能任取账号查匹配关系 |
| 同目录 `save_verifyCode.do/query_verifyCode.do/delete_verifyCode.do` | `ACCOUNTID/VERIFYCODE/FSSJ` 或 `ACCOUNTID` | 只记录模型声明，不查询、不发送、不清除任何验证码 |

客户端还声明固定成功转向 `/xsfw/sys/xggzptapp/index.do?min=1`；`api.js` 识别 `success` 和 `reset_pwd` 状态，HTTP 辅助超时 40000ms、`X-Requested-With: XMLHttpRequest`。实际业务失败/空集合同、验证码触发条件和认证后独立会话均未验证。

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

## 2. dorm 与 power：同用学校 SSO，不是同一个业务

两者匿名根路径均返回 302，SSO 地址 HTTPS，但业务服务回调为各自 **HTTP `default.aspx`**。
本轮没有用 JW 兼容权限自动允许这些回调，也没有把宿舍报修 `repair` 的会话借给它们。

[2025 智慧校园简介](https://zs.med.stu.edu.cn/upload_files/file/20250801/1754016918198845.pdf)把“学生事务及宿舍管理系统”列到 `xg`，把水电管理列到 `power`；因此旧 `dorm` 虽仍跳 SSO，不足以证明它仍承办所有宿舍事项或已经迁移。

[东海岸校区 2024-01-15 水电通知](https://stuecc.stu.edu.cn/info/1027/1395.htm)确认 `power` 可用校园网账号自助缴费，允许设置代理缴费，涉及欠费、扣款、恢复供电。后续协议调查需要先看本人只读账单与操作链接，把查询、代理授权与缴费分开；本轮没有真实数据字段或支付接口证据。

认证后待查：页面 title/菜单、本人宿舍关联、计费周期/币种/单位、历史分页和空记录、WebForms 隐藏状态/事件名、会话过期时是否跳 CAS。只登记字段名，不保存隐藏状态、个人账单或付款凭据。

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
