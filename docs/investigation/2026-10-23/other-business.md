# 其他教学、行政、科研、邮箱和医学院业务：入口与协议调查

本文件是 2026-10-23 的只读调查记录，不是已实现能力清单。原始候选来自
[2026-10-22 入口 CSV](../../verification/2026-10-22-campus-entries.csv)、
[当天学校快速通道](https://www.stu.edu.cn/kstd.htm)、页面直接链接和公开静态脚本。
没有向任何登录、申请、修改、发送验证码、预约或退出接口发送 POST；没有使用账号、
密码、已有业务会话、浏览器、SSO 票据。没有更改系统代理、DNS、证书或产品代码。

各次请求为本机 `httpx`、`trust_env=False`、TLS 正常校验、新匿名 cookie jar，顺序 GET，
连接超时 5 秒、读超时 8 秒、重定向最多 8 跳、普通正文最多 700 KB、选取的脚本最多 2 MB。
这排除了应用对环境代理的使用，不能证明系统 TUN 的实际转发路径，也不能代表校外网络。
本轮原始证据在被 Git 忽略的 `output/campus-protocol-survey/other-business/`；只保留必要的
无凭据调查摘要。表单值和会话标识已从本地证据中去掉，不能据此重放认证。

## 证据等级

- **实测 GET**：指定 URL 实际收到的状态、页面、公开 JSON 或重定向；不等于认证成功。
- **静态声明**：公开 HTML/JS 中的方法、参数、路径或功能文字；该业务请求没有执行。
- **来源标签**：官网/导航对入口的命名；不是当前功能、迁移或停用证明。
- **未核实**：需要业务权限、真实身份确认、页面恢复或后续只读验证。

首次种子逐条覆盖表和补充请求表在文末。别名按业务及路径保留，不能仅按主机合并。
根入口返回 200 可能只是一张空壳，根入口失败也不代表该主机所有公开路径都失败。

## 教学与学生资助

### 本科教学质量保障 `quality`

来源：[学校快速通道](https://www.stu.edu.cn/kstd.htm)。
[HTTP 首页](http://quality.stu.edu.cn/) 是强智前端 SPA，公开脚本
`/js/config.js`、`/js/common~app.c4c4bd85.js`、`/js/app.f5dcde45.js` 均实际 GET 200。
配置标题“教学质量保障平台”，页面需要 JS 不说明服务端必须启动浏览器。

| 路径 | 方法与参数 | 已证实范围 |
| --- | --- | --- |
| `/api/AuthenticationController/getLoginType` | GET | 实测 200 JSON；`loginType=CAS`，`casServerUrl=https://sso.stu.edu.cn/login`，`serviceUrl=https://quality.stu.edu.cn/caslogin` |
| `/api/AuthenticationController/getTitle` | GET | 实测 401，消息包含相同学校 CAS/HTTPS 回调配置；未登录不可读 |
| `/api/cas_ticket_verify` | GET，`ticket` | 静态 CAS 回调页接受 `ticket` 或 `st`，换取本业务认证结果；未调用 |
| `/api/AuthenticationController/user/info` | GET | 静态用户信息接口；未调用 |
| `/api/qsmart/common/menu/getTopMenu`、`userRouterTree` | 静态路由/菜单接口 | 登录后实际权限和返回结构未验证 |
| `/api/AuthenticationController/user/login`、`Logout` | POST | 另有本地登录/退出声明；未执行，不能据代码分支推断本校启用 |

前端模块包括听评课、学生评教、教师评价分析、问卷任务、整改和数据中心等路由。
通用发行包含其他学校的 OAuth 和模拟登录代码；这些不是汕大已启用功能。
当前 `getLoginType` 才是本校 CAS 配置的实测证据。没有登录学生/教师身份，不能列出用户
实际获授的任务、读写权限或完整业务 API。首页默认 `home` 的登录组件仅占位，不能据它
判断 CAS 不可行；实际 `/caslogin` 组件使用上述票据校验接口。

### 学分制旧站与交流生 `credit`

来源：[郁金香导航](https://d.stulip.org/)、[数学系常用网站](https://math.stu.edu.cn/xgwz/cywz.htm)。
根页面只引向 `/web`，但以下业务并不相同：

| 页面 | 实测及功能 | 协议/字段 |
| --- | --- | --- |
| `/web/` | 匿名 200，学业指南、管理规定、课程计划、常见问题、公开查询；主页新闻最新样本为 2022 年且链接新教务 | ASP.NET HTML；内容页 `/web/Detail.aspx?id=...`、栏目 `/web/LatestNews.aspx` |
| `/Course/DispCourseList.aspx` | 匿名 200，实际课程表含课程编号、名称、大纲、学分、总学时、是否通识 | 部门选择 `UCjxdw1$jxdw`，表单 POST 自身，WebForms 隐藏状态；未 POST |
| `/Elective/DispClassList.aspx` | 匿名 200，开课查询表单，学年选项包含 2026–2027，不能笼统当成已废弃 | `Xnxq$XN$Text`、`Xnxq$XN$List`、`Xnxq$XQ`、`Xnxq$hfXN`、`ddlJxdw`、`btnSearch`；未发查询 POST |
| `/TrainPlan/DisplayKcPlan.aspx` | 匿名 200，年度/课程计划筛选；页面明示以教务处颁布计划为准 | `ddlXn`、`ddlJh`、`btnSearch`；未 POST，不保证最新培养方案 |
| `/ClassRoom/ViewAll.aspx` | 官网链接出的教室使用情况页面；状态见请求表 | 与个人课表、教室申请不是同一功能 |
| `/Info/DisplayDeptStat.aspx` | 官网链接出的专业学生分布页面；状态见请求表 | 仅公开统计，不查询任何个人 |
| `/esms` | 实际跳 `/ESMS/login.aspx?ReturnUrl=%2fesms%2fIndex.aspx`，200 登录表单 | 独立交流生管理；`txtID`、`txtPwd`、`btnLogin` + WebForms 状态，POST 原页；没有 CAS 证据 |

“旧站”是页面历史和新教务链接关系，不等于其中所有公开数据停更；每一类数据仍须校验
学期/年度。交流生登录不能复用已有 `jw` 会话当作成功，也不能把课程目录当个人课表。

### 奖助学金、勤工、经费和新生旧入口

- [奖助学金](https://scholarship.stu.edu.cn/)：HTTP 自动 HTTPS，匿名首页 200；奖种、规则、
  通知、捐赠者和历史获奖信息由 ASP.NET `List.aspx?id=...`、
  `Detail.aspx?type=channel|content&id=...` 提供。首页通知样本止于 2020 年，是否仍受理不可推断。
  点击首页真实链接 `/ListExtendSQLB.aspx`，实测跳学校 SSO，service 为
  `https://scholarship.stu.edu.cn/admin.aspx`。申请列表/资格/材料/本人结果尚未登录核实。
- `www.scholarship.stu.edu.cn/chinese` 与 `/chinese/scholarList.aspx`：本机名称解析失败，
  而无 `www` 的新页面可达。二者只是旧标签/别名候选，不据此声称所有历史申请已迁移。
- `qgjx.stu.edu.cn`（勤工助学）、`outlay.stu.edu.cn`（学生经费）：HTTP 精确入口分别 403；
  未得到登录表单、JSON 或业务菜单，因此申请字段、查询接口、认证关系均未知。
- `reg.stu.edu.cn`（旧新生管理）：名称解析失败；不能据导航标签宣称当前入口有效或已迁移。
  `sao`/`xg` 的关系由学生事务调查单独核实。
- 学校当前官网明确发布的 `http://192.168.48.143/`（研究生管理）：匿名 GET 302 到学校 SSO，
  固定回调 `http://192.168.48.143/Caslogin.aspx`。没有登录，不知道实际菜单/查询接口。
- 学校当前官网明确发布的 `http://192.168.48.201/bursary/`：匿名 200，研究生国家奖助学金；
  页面公开学生、教师、院管理员、高级管理员四个 `stunic.aspx?role=...` 链接。
  未打开管理员路径或尝试身份切换；首页角色选择不是角色授权证明。

## 项目、科研、人事、财务和资产

### 教学项目 `project` 与项目管理 `action`

郁金香导航把教学项目写成 `http://http://project.stu.edu.cn`，这是无效 URL。
本轮明确记录“去掉重复协议头”的规范化候选 [project 根页](http://project.stu.edu.cn/)，
实际匿名 200，并非假装原错误 URL 已通。

主页给出通知文件、资料文件、二级单位负责人/填报负责人/评审专家三个使用手册；文字明确
账号由平台管理员或单位负责人分发，没有本校 CAS 关系证据。公开 JS 声明：

| 路径 | 静态用途/参数 | 实测边界 |
| --- | --- | --- |
| `/CCenter/MoreFileMan?id=21|22` | 通知/资料列表 | 主页真实链接，未继续翻页 |
| `/User/LoginFrm` | 加载登录窗 | JS 声明，未提交 |
| `/User/CheckCode?ID=<time>` | 图形验证码 | JS 声明，未请求挑战 |
| `/User/Logining` | 表单登录；`userid`、密码经 `siteencodetxt`、`yzm` | JS 声明；没有发送凭据 |
| `/CCenter/Index`、`ZlgcMenuMan`、`ZlgcNoteMenuMan` | 登录后的项目/栏目工作区 | JS 声明，不证明匿名可用 |

另一个 `action.stu.edu.cn` 只是导航标注“Action(项目管理)”，本机名称解析失败。
不能把它与教学项目、科研 `sro`、本科质量保障 `quality` 自动合并。

### 科研 `sro`、人事 `hr`、资源 `lrmo`

三者匿名入口都实际引向学校 SSO，各有自己的服务地址：

| 业务 | 实测固定 service | 未核实 |
| --- | --- | --- |
| `sro` 科研管理 | `https://sro.stu.edu.cn/default.aspx`；其中一次跳转先指向 HTTP SSO，本轮在认证边界停止 | 项目、成果、经费等实际菜单和学生权限 |
| `hr` 人事管理 | `http://hr.stu.edu.cn/base/frame/main_stdx.jsp?FM_SYS_ID=stdx` | 真实身份、人员信息和薪酬/审批接口；不得用学生身份探职工业务 |
| `lrmo` 资源事务 | `https://lrmo.stu.edu.cn/Home.aspx` | 资产、设备、房产等具体对象/角色；标签“固定资产”不足以与 lrao/equip 合并 |

### 固定资产 `equip`、`lrao` 与官网裸 IP 平台

- `http://equip.stu.edu.cn/` 返回 200 但正文近空，只含 `https://equip.stu.edu.cn/default.htm`、
  `https://lrao.stu.edu.cn/lrao/`（本部）和 `/med/`（医学院）链接。`default.htm` 又是旧页面，
  本部和医学院 `lrao` 精确入口各自实际跳学校 SSO，相应 service 保留对应路径。
  因此不是“equip 根 200 = 资产系统可用”。
- 当前学校快速通道发布 `http://192.168.48.148:8083/gdczsam`，本轮只按该明确地址匿名 GET，
  自动补尾斜线后 200“资产综合管理信息系统”。没有扫描 IP 或端口。
- 此平台公开 JS `index.js` 和 `core/js/tools/ajax.js` 指向 RPC `/service.do`，以
  `Ajax.service(classID, methodID, ...)` 包装。静态 `idUserLogin` 支持 `login`、`phoneLogin`、
  `getVerifyCode`、`genVerifyCode`、`SendCodeForPhoneLogin`、`loginByScanWorkwechatCode`；
  另有 `WorkWechatSettingBO` 企业微信配置。用户名、密码、图形码或手机码是不同分支。
  没有执行 RPC、发送短信、绑定扫码或登录，不能保证每个分支已在本校启用。
- `ogs.stu.edu.cn` 固资查询旧别名名称解析失败；与上面可达平台的迁移关系未知。

### 财务 `cwc`、旧平台与新版 `wpay`

[财务处 HTTP 官网](http://cwc.stu.edu.cn/) 匿名 200，是通知/办事说明站；HTTPS 根本轮读取超时。
它与个人财务平台是不同路径，不把主页信息当个人查询已接入。

学校快速通道当前同时发布旧 `http://192.168.48.249/dlpt/login.aspx` 和新版
`https://wpay.stu.edu.cn/api/logcas/checkTicket`，后者与历史 CSV 的 `/login` 不同。
旧页匿名 200 的说明明确让用户改从新版登录，且仍显示旧表单 `Txt_UserName`、`Txt_PassWord`、
`Txt_Yzm`、`Btn_login`，WebForms 状态及客户端 AES；没有提交，旧页面存在不是继续受理证据。

新版 `/login` 匿名 200 SPA；当前官网 `/api/logcas/checkTicket` 实测 302 到 `/logCas` 再 200 SPA。
公开 `chunk-common.20772bb8.js` 的协议声明包括：

| 路径 | 方法/用途（静态，均未执行业务调用） |
| --- | --- |
| `/api/logcas/caslogintoken?cas=...` | GET，CAS 路线将结果换成业务 token |
| `/api/login`、`/api/user/pubkey` | POST 登录、GET 公钥；另一个密码分支，不能据此假定配置与学校 SSO 相同 |
| `/api/qrlogin/qrcodeimg`、`qrcodestate?uuid=...` | GET，二维码与轮询分支 |
| `/api/user/createImgValidate`、`verifyimgx` 等 | GET，图形挑战分支，未获取/解决挑战 |
| `/api/getUserInfo`、`/api/getMenuTree` | POST，用户/权限菜单；必须独立业务认证 |
| `/api/menu/mymenu`、`/api/menu/getZsxtList` | 静态菜单/关联系统；实际可用业务未知 |
| `/api/dbtz/dbsxlu`、`/api/dbtz/tzgg` | GET 待办入口、POST 通知（具体字段/权限未验证） |
| `/api/xtQueryConfig/getXtQueryConfig`、`xtTableConfig/getXtTableConfig` | 配置驱动的查询/表格；不是已验证的个人财务查询 API |

前端在请求上带 `Authorization: Bearer ...`，不能拿本校 CAS cookie 直接替代财务 token。
脚本也包含修改密码、账户信息、卡信息、授权等写接口，本轮没有调用。
`appconfig.js` 含其他学校/演示联系方式，不能把这些模板文字当成汕大财务的联系方式。
个人报销、缴费、工资、项目余额、账单等菜单与数据均需合法对应身份再验证，当前没有全图。

## 通知、档案和会务

- `eventcalendar` 根及 `/WebForms/Index.aspx`：本机名称解析失败；只有活动安排的来源标签，
  没有任何当前接口/数据证据。不能把它与已有官网活动或预约平台直接视作一个源。
- `gongwen`：HTTP 跳 HTTPS 后 200，正文、表单、script 都为空。没有返回公文列表，
  不能说“可读取公文”；与 OA 公告的关系尚未取得页面证据。
- `infor/index.aspx`：HTTP 跳 HTTPS 同路径后 502“50X”；`information` 另一个历史名字名称解析失败。
  不将二者自动当成已迁移，也未证明信息报送业务受理方式。
- [综合档案室 `efms/index.aspx`](http://efms.stu.edu.cn/index.aspx)：匿名可读 2026 年通知、
  归档说明、展厅，服务指南 `/guide.aspx` 实测 200。`/login.aspx` 200 的档案服务表单为
  POST 自身，`ctl00$main$txtUserID`、`ctl00$main$txtUserPwd`、`ctl00$main$btnLogin` 加 WebForms 状态。
  公开指南说明证明材料/非本人档案有审批要求；没有认证成功，不知道在线查询与申请对象。
  `guestbook.aspx` 在线咨询入口仅记录，未发留言。此站不是 `efms` 名称看起来像的财务业务。
- `mms` 会务根 404；`mrp` 物料根返回 301，但 `Location=https:///` 无有效主机，停止。
  没有构造替代地址或猜测 API。二者功能目前仅有导航标签。
- `security` 安防旧入口名称解析失败；不能和下述校门审批混为一个已验证系统。

## 车队、校门和仪器预约

### 车队的两个来源

旧 `carfleet` 根实际去 SSO，service `http://carfleet.stu.edu.cn/default.aspx`。
导航精确 `/index.htm` 又返回 200 frameset，分别引用 `Top.aspx`、`System_Menu.aspx`、
`left.htm`、`Page/Car_Application_Add.aspx`。本轮只读菜单和左框；没有打开申请表或提交。
frame 名字说明有用车申请，不证明匿名可申请或旧系统仍受理。

当前[学校快速通道](https://www.stu.edu.cn/kstd.htm)“车队管理系统”实际改指
[广东省公务用车管理平台](https://jgsw.gd.gov.cn/gcglpt/Home/Login#carTask)，该精确页匿名 200。
它显示单位账号、独立统一身份认证、图形验证码，静态表单 POST `/gcglpt/Login`，字段
`UserName`、`Passwordshow`/派生 `Password`、`ValidateCode`、`TokenCode`、`UserID`、`UserType`、`UserToken`。
另有省 OAuth `/ythpt/auth/connect/oauth2/authorize` 路线。没有登录/验证码/单位注册调用。
这不是学校 SSO 已适配的证据；旧校园车队与省平台是否数据互通、面向哪些身份，仍待办事说明核实。

### 校门审批 `parking` / `wechat`

[官网明确审批页](https://parking.stu.edu.cn/parking/approval.html) 匿名 200，列三种业务。
逐一跟随已发布路径，均在学校 SSO 前停止：

| 业务 | 精确入口及 CAS service |
| --- | --- |
| 汽车进校审批 | `https://parking.stu.edu.cn/parking/management/` |
| 摩托及非机动车 | `https://parking.stu.edu.cn/motorcycle/management/` |
| 访客进校审批 | `https://wechat.stu.edu.cn/health-report/management/` |

三个 service 与表中对应完整 URL 一致。没有认证，不知道用户是否可申请/只能审批、申请字段、
本人历史列表及状态 API。`health-report` 路径文字不能据此改称当前健康填报或全员疫情业务。

### 大型仪器共享 `zxsys`

学校官网根及 `/genee/` 实际转 HTTPS 同平台，匿名首页和 `/genee/category/equipment` 均 200。
公开内容为平台/仪器目录、中心实验室通知、仪器运行情况、收费信用额度说明、资料下载。
仪器页搜索表单 GET `/genee/search`，字段 `search_type`、`keywords` 以及页面自身 token（未取值）。
校内入口是官网直接给出的 `/gateway/?from=stu&redirect=.../cf/main/!people/docking/login`，
校外入口 `/cf/main/`；这与现有课程/图书馆预约不是同一会话。

公开首页 JS 声明以下 **POST 读数接口，未发送**：
`/genee/ajax/index/equipment/GetSummaryInfo`（`res_type=json`，回调使用 totalCount/controlCount/
usingCount/unUsingCount/outServiceCount）、`userStatus`（outer/inner/incharge）、
`GetDisplayEquipments`（id）、`getrecords`、`GetTopEquipments`、`GetTopUsers`、`TimeRank`，
另有 `/genee/ajax/stu/platform`（start）。它们输出 HTML 或 JSON 的分支不能互相混同。
实际登录、仪器详情、可约时段、资质/培训、课题组计费和预约事务尚未验证。

## 就业招聘、校友和邮件

### 学生就业 `gdc`

[首页](https://gdc.stu.edu.cn/) HTTP 自动 HTTPS，匿名可读最新通知、招聘岗位、企业信息、
宣讲会/双选会、就业日历、政策及手续指南。不是 `job` 的学校招聘工作人员系统。

| 接口/页面 | 本轮结果与字段 |
| --- | --- |
| GET `/JobFair/GetDiaryJobFair?month=2026.10` | 实测 200 JSON，顶层 `Code,Msg,ExtMsg,Total,PageIndex,PageSize,PageCount,Data`；本次 28 项；条目 `JobFairId,Day,Date,Title,Place,ShowDate,Type,IsOuter,SchoolArea` |
| GET `/Home/get_event_data?month=2026.10&day=23` | 实测 200 JSON，相同包装，返回当天宣讲会标题/地点；月份接口的 `Title/Place` 可为 null，不能由字段空推断没有活动 |
| GET `/JobFair/InnerTalk`、`/Search/SearchJob` | 实测 200 HTML；宣讲会列表、职位搜索 |
| `/JobFair/CareerTalk?id=...`、`/Job/ID`、`/Ent/ID`、`/Article/ArticleDetail/ID` | 当前首页真实公开详情链接；未遍历所有详情 |
| GET `/Home/get_index_job?edu=...`、`get_index_jobfair?type=...` | 公开 JS 定义，未请求；岗位返回回调含 Id/Name/EntId/EntName，活动含 JobFairId/Title/Address |

公开脚本另有学生登录和用人单位账号路线、反伪造支持；未发凭据。页面列出职业测评、
简历、就业手续，不代表匿名可操作或可复用学校统一登录；还需分别确认，尤其不能把
用人单位注册/职位发布权限当学生能力。返回日期 `/Date(milliseconds)/` 需保留时区，
`Type` 的数字只按页面实际使用分支理解，不能擅自把全部枚举含义补齐。

### 学校招聘 `job`

根实际到 HTTPS `/product/recruit/website/RecruitIndex.jsp?FM_SYS_ID=stdx`，匿名 200；
招聘公告、招聘岗位、指南、联系我们分别 `RecruitNoticeNew.jsp`、`RecruitPostNew.jsp`、
`RecruitGuideNew.jsp`、`RecruitContactNew.jsp`。岗位列表本次表格实际 0 条，表头为岗位名称、
招聘单位、类型、人数、截止日期；这不是接口错误，也不能推断永不招聘。
指南明示独立邮箱注册、简历填报、每次只能报一岗以及提交后的修改限制。
JS 登录/注册页面 `RecruitLoginNew.jsp`、`RecruitRegisterNew.jsp` 与验证码
`/product/recruit/pages/verfication.jsp` 仅静态发现，未注册、登录或应聘。

### 校友 `xyh` / `alumni`

`xyh` 根实际到 HTTPS `/alumni/front/account/index.jsp`，匿名 200，当前校友新闻/公告可读，
站内搜索表单 POST `/alumni/front/account/search.jsp`（keyword），没有执行。
旧 `AlumniLogin.aspx`、`class.asp`、`details.aspx?...`、`AlumniIntro.aspx?...` 精确路径均 404。
因此应按新 JSP 页面调查，不能继续把旧校友数据库/申请校友卡路径视作有效 API。
`alumni.stu.edu.cn` 根及旧 Extmail URL 本机名称解析失败；新站存在不能证明历史邮箱迁入。

### 邮件与 Office 支持

- 官方当前入口为 [partner.outlook.cn](https://partner.outlook.cn/)；`m.stu.edu.cn` 实测只重定向到它。
  对微软精确已发布地址匿名 GET，返回 `/mail/` 的 Outlook 外壳。没有登录、邮箱列表、收发或 OAuth
  授权，不能称邮箱读接口已验证，更不能认为它自动使用学校 CAS。
- `webmail.stu.edu.cn` 名称解析失败，为旧标签而非当前可用路径。
- [support 首页](https://support.stu.edu.cn/) 匿名 200，支持工单/送修预约、电话、电邮请求、
  修改密码激活账号、[Office 下载](https://support.stu.edu.cn/office365/download.html)、
  [FAQ](https://support.stu.edu.cn/office365/help.html)；不只是“客户端安装包”站。
- FAQ 的现存旧说明列 IMAP `partner.outlook.cn:993` SSL、SMTP
  `smtp.partner.outlook.cn:587` STARTTLS，以及校园邮箱密码。**仅是当前可读指南文字**，
  本轮没有连邮件端口/验证现代 OAuth、基本认证支持或租户权限，不能作为当前认证兼容保证。
- 页面 `js/js.js` 静态 `GetSupportItem.ashx`：POST `method=UserInfo` 检查会话；
  GET `method=GetItemID&ID=...`、`GetItemTypeID&ID=...` 取项目/类型；
  POST `method=Add` 发送 JSON 数组，字段 Support_ID、SupportType_ID、Booker_Mobile、
  Booker_Tel、Booking_Time_ks、Support_Desc、Support_Title。所有调用均未发出。
  未登录跳 `Default.aspx` 的声明不是认证成功证据；support 支持请求与宿舍/校园综合报修分别处理。

## 医学院独立入口及新发现

医学院不是本部系统的一个别名。由旧 [int.med 根](http://int.med.stu.edu.cn/) 实际重定向到
[融合门户快捷导航](https://yxy.med.stu.edu.cn/quicklink.html)，发现以下独立业务；没有输入本部或
医学院账号。匿名 GET 医学院认证页不代表取得了业务授权。

| 业务 | 当前明确入口 | 本轮证据及缺口 |
| --- | --- | --- |
| 统一认证 | `https://sso.med.stu.edu.cn/cas/login` | 与本部 `sso.stu` 不同；由 OA/教务/科研实际重定向到该登录页，无认证 |
| 公告聚合 | `https://sumcapi.med.stu.edu.cn/oa_notice.php` | 匿名 200；汕医/汕大通知两个 tab，部门筛选和分页；详见下段 |
| 公文 | `https://dzb.med.stu.edu.cn/` | 200 党政办公室公开页面，权限业务未知；不是本部 gongwen |
| 协同 OA | `https://oa.med.stu.edu.cn/seeyon/caslogin/sso` | 实际转独立 SSO，service 同 OA:443 路径；未登录；会议室链接存在但未调用 |
| 教务 | `https://jwgl.med.stu.edu.cn/new/welcome.page?ui=new` | 实际转独立 SSO，回调 `/new/ssoLogin`；没有成绩/课表接口证明 |
| 科研管理 | `https://yxykygl.med.stu.edu.cn/userAction!do_casLogin.action` | 实际转独立 SSO，同 action 回调；项目/成果权限未知 |
| 研究生招生 | `https://yjszs.med.stu.edu.cn/public/index.html` | 根 JS 指向该公开页面，200；招生动态、简章、专业、报考咨询、导师目录真实链接 |
| 导师目录 | `https://yjszs.med.stu.edu.cn/supervisor/supervisor.php` | 匿名 200，公开信息；未做导师选择/报名 |
| 财务 | 快捷导航明确给出独立 SSO，service 为 `http://10.11.16.201/dlpt/caslogin.aspx` | 仅链接，不提取 service 内网 IP 另探，不把本部 wpay 代替它 |
| 资产 | `https://syzwc.med.stu.edu.cn/152/list_152_1.html` | 200 总务处公开列表，不能只凭门户“资产系统”标签声称已找到资产 API |
| 办事大厅 | `https://ywtb.med.stu.edu.cn/` | 200 事项目录、部门筛选、表格；静态读目录 POST 见下段，未提交 |
| 个人流程/学生请假 | `https://ywtb-workflow.med.stu.edu.cn/s/9LimoXmZ` | 200 SPA 外壳；菜单另列 project/todo、workflow/todo/finished/process；没有业务权限或数据证据 |
| 科研申报信息 | `https://keyan.med.stu.edu.cn/` | 200 公告聚合，标注 AI 获取；已验证分页 JSON，须核原文 |
| 中心实验室 | `http://zxsys.med.stu.edu.cn/equip.php` | 200 公开仪器页面，预约/登录未验证；不能与本部 zxsys/genee 合并 |
| 教学业绩 | `http://yeji.med.stu.edu.cn/` | 从办事大厅“业务系统”页发现，200 操作说明；具体登录入口/统计接口未核实 |
| 实验动物设备预约 | `http://stulac.med.stu.edu.cn/book/member/login.php` | 办事大厅真实链接，200 独立登录表单；未登录或预约 |
| 行政服务效能评价 | `https://xnpj.med.stu.edu.cn/index.php?action=login` | 办事大厅真实链接，本机名称解析失败，未知认证和评价接口 |
| 研究生选课 | `http://gc.med.stu.edu.cn/member/login.php` | 医学院研究生教育站真实链接，匿名 200 独立账户/类型/图形码登录页，无认证 |
| 研究生教学质量评价 | `http://gse.med.stu.edu.cn/member/login.php` | 同一研究生站真实链接，本机连接超时；不能与本部 quality 合并 |
| 研究生成绩查询 | `https://yjs-sys.med.stu.edu.cn/index/user/login` | 同一研究生站真实链接，200“汕医校园信息化平台”登录页；仅有入口，不知道成绩 API |

### 医学院可匿名读的接口细节

- `sumcapi` 列表 GET `/oa_notice.php?tab=oa|stu&page=N&dept=<页面给出的部门>`；链接中确有
  10 条一页及下一页、总页数。`tab=stu` 另一次真实 GET 200，但不是本部 OA 全量/实时的保证。
  正文 GET `/article.php?ws=oa&aid=<列表原有 ID>` 抽取一篇教务公告真实 200；只记录公开正文
  可读，不下载附件、不推断受限公告均可读。
- `keyan` 列表普通 GET 返回 HTML；相同 `/?page=1` 加
  `X-Requested-With: XMLHttpRequest` 实测 200 JSON：`code,msg,data,has_next`。
  条目字段 `id,title,date,source,author,content,type_code,url,files_json,summary,create_time,
  subject_scope,deadline_requirements,application_criteria,research_areas,selection_method,
  application_procedure,application_method,type_code_text`。前端静态按 `&type=` 切来源。
  页上明示“由 AI 自动获取”；这些结构字段不能直接当权威期限/报名要求，需读取 url 所指公告。
- `ywtb` 目录公开 HTML 本身可读，前端脚本以 POST `/index/index/index.html`，参数
  `service_name,dep,subject,page,post_type` 做过滤/分页，回调读取 `value,subject_list` 等结果；
  POST 未执行。目录链接 `/index/index/services_detail/id/N`、
  `/index/index/services_system`、`/index/download/index` 提供事项/业务/表格。
  “我的待办/已办/请假”由另一个 workflow 系统承接，不可用目录匿名可读推断流程免登录。

### 医学院旧站和历史学习系统

`bgs.med` 根和 `/search.htm` 匿名 200，是 2005 年最后修改标记的文件发布/FrontPage 搜索页，
栏目为学院通知、意见稿、院务/党务文档；搜索 POST `/_derived/nortbots.htm`，字段 search 和
VTI-GROUP，未执行。旧 `jiaowu.med/jw.asp`、`www.med/xw/yjs/userlogin.aspx`（导师报名）、
`www.med/xw/zp/index.aspx`（招聘）精确 URL 均 404，不能继续按旧导航当有效业务。
`elp.med` 到 `/member/login.php` 200 独立学习平台登录；`usmle.med` 到
`/CommonAdmin/Login.aspx` 200 WebForms 登录，字段 txtUsername/txtPass/CheckCode/btnLogin，
前端提示 IE；未验证在线考试，不能把老客户端要求当成 HTTP 认证不可行证明。
`norton.med`、`zsxx.med` 名称解析失败，`syzx.med`、`update.med` 连接超时，`test.med/ot`
服务端断开，均保留未知状态。

补查医学院 [研究生教育首页](http://yjs.med.stu.edu.cn/) 实测匿名 200，公开最新调课、选课、
学期课表、招生、培养/学位通知，并直接指上述 gc/gse/yjs-sys；旧 `/forum`、`/yjs` 路径均 404。
gc 静态表单 POST 自身，字段 username/password/usertype/checkcodestr/dosubmit；类型列表含
学生与多类管理员，未改变角色或登录。yjs-sys 表单 POST 同页，account/password/keeplogin、
`__token__`，前端配置还出现 Geetest；未请求或解决挑战，不能宣称该挑战一定出现。
旧 ELP 与动物预约各自也有 username/password/checkcodestr/dosubmit 的独立表单；相同
字段不是同会话或统一认证证明，均未登录。`el.med`、`jsj.med` 本机名称解析失败。

[医学院就业指导中心](http://syjob.med.stu.edu.cn/) 匿名 200，以 `detail.aspx?id=...` 提供
招聘/流程通知，新闻检索为 WebForms POST（txtKey、btnSearch 和页面状态，未执行）。
首页图片热点明确将“一站式服务系统”引至校外 `gdc.ncss.org.cn/login`、`/rec/login`，
学生/用人单位是不同路线，仅记录外部来源，不拿本部 gdc 登录替代。

## 本部其他旧教学/社区系统与本科录取查询

- `itc`、`www.stulc/it4.htm`（IT 技能）、`newcourse`、`vc`（虚拟教室）、`ftp`（金凤/电视）
  精确入口名称解析失败；`neie/web/login.aspx`（英语自主学习）连接超时。没有接口/认证证据。
- `appinventor` 连接超时、`arguendo` 拒绝连接、`asso` 根及 `/asso/AssoSky` 服务端无响应即断开；
  本轮没有宣称它们退役或用其他同名平台替代。
- `itv` 到 `/PS_Live.aspx` 200，`phoenix/bt/default.aspx` 200 但正文/可操作内容不足；
  没有验证点播流/BT 目录，也没有进行媒体或大文件下载。
- 本科录取旧 `/RecruitStudents/WebForm/Search.aspx` 精确路径 404；现
  [录取结果查询页](https://zs.stu.edu.cn/zxfw/lqjgcx1.htm) 200，当前模板标题“2026 年录取结果查询”，
  使用站群 openapp 动态表单。只观察页面和公共 api.js，未输入考生姓名/证件/考号或查询任何人。
  静态前缀 `/aop_component//webber/formquery/`，模板 `Form-1773642663029-4261`、viewId
  `1177394`，具体查询条件和有权限的个人返回尚未实际请求；不把站内新闻搜索表单当录取查询 API。
  页面可能返回校园账号初始信息，故即使匿名入口存在也不能按普通公开数据采集。

### 机构首页中有无漏掉的业务

对已发布的机构页另作有界读取：`https://rsc.stu.edu.cn/MainSite/Index.aspx`、
`https://zyc.stu.edu.cn/`、`http://kyc.stu.edu.cn/` 均 200。人事页的人力资源链接仍是上述 hr；
后台管理入口属于网站编辑管理，本轮明确排除，不打开。资源页列资产、车队和报修；其中
资产 href 缺少协议，浏览器实际会变成 `https://zyc.stu.edu.cn/192.168.48.148:8083/gdczsam/`，
不能把它当正确资产入口；采用学校快速通道明确发布的完整裸 IP URL，并保留坏链接证据。
科研处页面以公开申报通知/制度为主，另指国家科技、基金委、专利和全国教育科研外部平台；
这些有独立授权体系，不自动当作学校账户新增能力，也没有把它们的地址加入探测范围。
`https://www.gs.stu.edu.cn/` 本轮 TLS 证书过期校验失败。覆盖复核又对原发布精确
`http://www.gs.stu.edu.cn/` 作了匿名 GET（2026-10-23 12:43:17 UTC），确实收到 301，
Location 指向相同主机 HTTPS 根，随后同样因证书过期失败；没有关闭证书校验或改走其他地址。
因此 HTTP 原入口已检查，受阻点仍是官方 HTTPS 证书，而博士考生、推免等下级业务缺少
本轮根页证据，不能写已全面扫清研究生招生接口。

### 全目录覆盖复核时补出的业务

| 来源候选 | 本轮补查结果 | 业务边界 |
| --- | --- | --- |
| `http://activity.stu.edu.cn/`，导航“汕头大学预约中心” | 本机名称解析失败 | 原先未列入 booking/SLC 等；不能因名称相似断言迁移 |
| `http://xlcs.stu.edu.cn/Login.aspx`，导航“心理测试登录” | 匿名 200，Visual DNA 心理测试登录页 | 校园账号/密码的 WebForms 表单，未登录、答题、查看量表或个人心理数据 |
| `http://cwk.med.stu.edu.cn/`，导航“财务信息网” | 匿名 200，当前医学院计财处官网 | 两篇平台迁移/升级通知补充了当前路线与可查事项，见下段；非个人财务数据 |
| `http://newcourse.med.stu.edu.cn/`，ELP 页真实链接 | 本机名称解析失败 | 与本部 `newcourse.stu.edu.cn` 分开记录，未知内容/API |
| `https://mcm.stu.edu.cn/`，导航“数学建模” | 匿名 200，数学建模协会新闻/资源站 | 当前页面只见文章、通知下载、竞赛外链，未观察在线报名接口，不声称全站没有 |
| `http://io.stu.edu.cn/`，导航“脑力奥运” | 到 `/web/`，匿名 200，社科部教材练习/游戏旧站 | 存在旧 Flash/VBScript 客户端，不是一般机构介绍；未打开练习或提交成绩 |
| `http://192.168.48.189:8080/system/login.jsp`，数学系官方页旧称“本系教师网” | 匿名 200，实际为“全媒体管理平台/站点管理/系统管理” | 本轮排除网站编辑管理后台，绝不按教师事务系统尝试登录 |

xlcs 表单 POST 原页，账号、密码与按钮字段为
`ctl00$ContentPlaceHolder1$tb_user_name`、`ctl00$ContentPlaceHolder1$tb_user_pwd`、
`ctl00$ContentPlaceHolder1$btn_login`，加 WebForms 状态。当前页面文字“校园网账号”不等于
现代 CAS 重定向证据；只有 `AC_RunActiveContent.js`/旧 Flash 显示代码，未进行任何测试。

`io` 公共脚本 `OpenGame.js`、`FsCommand.js` 实际 GET 200。声明教材客户端
`http://io3.stu.edu.cn/{sxddxy,fljc,sxddxyyfljc,mkszy,zgjds,mzdsx}/Client/Client.aspx`，
若干带 `version=2018`；这些是静态地址，不是已执行的读接口。菜单另列个人信息、积分/排行、
论坛等页面，但未打开，以免产生练习或访问个人记录。真实首页链接 `/sso` 实测到 `/sso/`
200，表单 POST `/sso/Default.aspx`，账号/密码字段 `UCLogin31:TB_UserName`、
`UCLogin31:TB_Password`、按钮 `UCLogin31:ImageButton1`。不能因为目录叫 sso 就当作
现代 `sso.stu.edu.cn` CAS；没有进行登录。

医学院计财处 [2026-01-14 通知](http://cwk.med.stu.edu.cn/2/98.html) 实测正文可读，明确学院
财务平台并入 `yxy.med.stu.edu.cn`，走医学院工号/身份，亦给出前述
`http://10.11.16.201/dlpt/caslogin.aspx`。未探人员附件或查询任何工号。
[2026-05-27 通知](http://cwk.med.stu.edu.cn/2/104.html) 另介绍汕大新版 wpay/财务微信服务号，
说明工资收入、项目查询、学生缴费、报销进度/退回、银行单自助查询等功能，密码找回验证码
经微信服务号；这些属于官方说明，尚没有相应真实个人 API/字段证明。通知当时明确旧平台
暂时保留，未来关闭时间未知，不能用旧页面引导新平台就宣称旧版停用。两篇分别描述学院
门户财务与汕大新版平台，不据此合并它们的账号、身份或会话。

## 覆盖边界和后续证据

这些系统已经完成“入口/公开协议取证”的逐项初查；**没有完成所有受保护业务的完整接口图**。
可匿名的公开 JSON、表单状态、API 声明已分清；被 SSO、角色、403、空壳和网络错误挡住的部分
没有伪装成已查清。下一轮若继续，应按具体业务申请对应只读身份/公开指南，先读本人的菜单与
列表，再确认参数、返回结构、分页/错误与稳定身份判据，避免使用职工/管理员功能。

学院/机构门户、2000 年代会议专题、新闻专题、外部媒体/学术服务、监管备案和地图并非当然
“未实现的校园业务 API”。本文件不逐页爬这些栏目；保留原 CSV 来源标签，按上述发现出的明确
业务路径才进入调查。附属医院/其他院校/第三方商业平台不自动纳入学校账号认证范围；省车队
和微软邮箱因为当前官网明确作为业务入口发布，已专门记录，仍不共享学校会话。

<!-- GENERATED_COVERAGE -->

## 精确种子覆盖台账

首批 84 个精确已发布 URL（含别名/不同路径，不是 84 个独立系统）均已有请求记录。
来源文本沿用原 CSV；“live”表示本轮官网新增链接。查询字符串只保留公开业务/文章标识，未记录票据或会话值。

| 精确种子 | 来源标签 / 出处 | 本轮匿名结果 | 核查时间 UTC |
| --- | --- | --- | --- |
| `http://192.168.48.143/` | http://192.168.48.143/  /  研究生管理信息系统<br>数学系常用网站  /  官网快速通道 | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=http%3a%2f%2f192.168.48.143%2fCaslogin.aspx | 2026-10-23T12:11:56.540216+00:00 |
| `http://192.168.48.148:8083/gdczsam` | 固定资产管理系统<br>官网快速通道 | 200 → http://192.168.48.148:8083/gdczsam/ | 2026-10-23T12:11:56.889896+00:00 |
| `http://192.168.48.201/bursary/` | 研究生国家奖助学金管理系统<br>官网快速通道 | 200 | 2026-10-23T12:11:57.004637+00:00 |
| `http://192.168.48.249/dlpt/login.aspx` | http://192.168.48.249/dlpt/login.aspx  /  财务综合服务平台<br>数学系常用网站  /  官网快速通道 | 200 | 2026-10-23T12:11:59.785698+00:00 |
| `http://action.stu.edu.cn/` | Action(项目管理)<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:11:59.845683+00:00 |
| `http://alumni.stu.edu.cn/` | 校友邮箱<br>郁金香 / html/catalog/2311.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:11:59.882403+00:00 |
| `http://alumni.stu.edu.cn/extmail/cgi/index.cgi` | 汕大校友邮箱<br>郁金香 / html/catalog/2512.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:11:59.903283+00:00 |
| `http://appinventor.stu.edu.cn/` | appinventor<br>郁金香 /   /  郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2374.htm | ConnectTimeout: timed out | 2026-10-23T12:11:59.920601+00:00 |
| `http://arguendo.stu.edu.cn/` | Chatwood<br>郁金香 /  | ConnectError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。 | 2026-10-23T12:12:04.945504+00:00 |
| `http://asso.stu.edu.cn/` | 社团联合会<br>郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2373.htm | RemoteProtocolError: Server disconnected without sending a response. | 2026-10-23T12:12:07.003945+00:00 |
| `http://asso.stu.edu.cn/asso/AssoSky` | 汕头大学社团总汇<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | RemoteProtocolError: Server disconnected without sending a response. | 2026-10-23T12:12:07.048078+00:00 |
| `http://bgs.med.stu.edu.cn/` | 公文发布系统<br>郁金香 / html/catalog/2520.htm | 200 | 2026-10-23T12:12:07.069790+00:00 |
| `http://carfleet.stu.edu.cn/` | http://carfleet.stu.edu.cn/  /  车队管理系统<br>郁金香 / html/catalog/2298.htm  /  郁金香 / html/catalog/2354.htm  /  数学系常用网站 | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=http://carfleet.stu.edu.cn/default.aspx | 2026-10-23T12:12:07.186274+00:00 |
| `http://carfleet.stu.edu.cn/index.htm` | 车队管理系统<br>郁金香 /  | 200 | 2026-10-23T12:12:13.184278+00:00 |
| `http://credit.stu.edu.cn/` | 学分制管理系统(校内)  /  学分制系统<br>郁金香 /   /  郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2374.htm | 200 | 2026-10-23T12:12:13.239927+00:00 |
| `http://credit.stu.edu.cn/esms` | 交流生管理系统(校内)<br>郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2374.htm | 200 → http://credit.stu.edu.cn/ESMS/login.aspx?ReturnUrl=%2fesms%2fIndex.aspx | 2026-10-23T12:12:13.449173+00:00 |
| `http://credit.stu.edu.cn/web/` | http://credit.stu.edu.cn/web/<br>数学系常用网站 | 200 | 2026-10-23T12:12:14.095933+00:00 |
| `http://cwc.stu.edu.cn/` | 财务处  /  财务查询系统<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2298.htm  /  郁金香 / html/catalog/2354.htm  /  官网快速通道 | 200 | 2026-10-23T12:12:15.303811+00:00 |
| `http://efms.stu.edu.cn/index.aspx` | 档案管理服务<br>官网快速通道 | 200 | 2026-10-23T12:12:16.566706+00:00 |
| `http://elp.med.stu.edu.cn/` | 学习平台ELP<br>郁金香 / html/catalog/2520.htm | 200 → http://elp.med.stu.edu.cn/member/login.php | 2026-10-23T12:12:18.117252+00:00 |
| `http://equip.stu.edu.cn/` | 固定资产管理系统<br>郁金香 / html/catalog/2520.htm | 200 | 2026-10-23T12:12:18.380835+00:00 |
| `http://eventcalendar.stu.edu.cn/` | 活动安排系统<br>郁金香 /   /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:18.700828+00:00 |
| `http://eventcalendar.stu.edu.cn/WebForms/Index.aspx` | 活动安排系统<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:18.722340+00:00 |
| `http://ftp.stu.edu.cn/` | 金凤FTP<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:18.737339+00:00 |
| `http://ftp.stu.edu.cn/TV/default.aspx` | 汕大网络电视<br>郁金香 /  | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:18.760345+00:00 |
| `http://gdc.stu.edu.cn/` | 就业  /  就业指导中心  /  毕业生就业指导中心<br>郁金香 /   /  郁金香 / html/catalog/2308.htm  /  郁金香 / html/catalog/2354.htm  /  官网快速通道 | 200 → https://gdc.stu.edu.cn/ | 2026-10-23T12:12:18.783145+00:00 |
| `http://gongwen.stu.edu.cn/` | 校内公文系统<br>郁金香 /   /  官网快速通道 | 200 → https://gongwen.stu.edu.cn/ | 2026-10-23T12:12:20.379658+00:00 |
| `http://hr.stu.edu.cn/` | http://hr.stu.edu.cn  /  人事管理系统  /  人力资源管理服务系统  /  人力资源管理系统  /  人力资源系统<br>郁金香 /   /  郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm  /  数学系常用网站  /  官网快速通道 | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=http%3A%2F%2Fhr.stu.edu.cn%2Fbase%2Fframe%2Fmain_stdx.jsp%3FFM_SYS_ID%3Dstdx | 2026-10-23T12:12:20.439003+00:00 |
| `http://infor.stu.edu.cn/index.aspx` | 信息报送系统  /  汕大信息报送<br>郁金香 /   /  官网快速通道 | 502 → https://infor.stu.edu.cn/index.aspx | 2026-10-23T12:12:20.548623+00:00 |
| `http://information.stu.edu.cn/` | 信息报送系统<br>郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:23.616531+00:00 |
| `http://int.med.stu.edu.cn/` | 汕医办公自动化<br>郁金香 / html/catalog/2520.htm | 200 → https://yxy.med.stu.edu.cn/quicklink.html | 2026-10-23T12:12:23.635076+00:00 |
| `http://itc.stu.edu.cn/` | IT技能考试系统(网络故障)<br>郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:23.741811+00:00 |
| `http://itv.stu.edu.cn/` | 网络点播系统  /  网络直播系统<br>郁金香 /   /  官网快速通道 | 200 → http://itv.stu.edu.cn/PS_Live.aspx | 2026-10-23T12:12:23.760396+00:00 |
| `http://jiaowu.med.stu.edu.cn/jw.asp` | 教学管理网<br>郁金香 / html/catalog/2520.htm | 404 | 2026-10-23T12:12:23.888942+00:00 |
| `http://job.stu.edu.cn/` | 诚聘英才  /  诚聘英才(汕大招聘)<br>郁金香 / html/catalog/2298.htm  /  郁金香 / html/catalog/2354.htm  /  官网快速通道 | 200 → https://job.stu.edu.cn/product/recruit/website/RecruitIndex.jsp?FM_SYS_ID=stdx | 2026-10-23T12:12:23.925954+00:00 |
| `http://lrmo.stu.edu.cn/` | 固定资产管理系统  /  资源事务系统<br>郁金香 /   /  郁金香 / html/catalog/2354.htm | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https%3a%2f%2flrmo.stu.edu.cn%2fHome.aspx | 2026-10-23T12:12:24.082251+00:00 |
| `http://m.stu.edu.cn/` | 新版汕大邮箱<br>郁金香 /  | 302；external redirect not followed → https://partner.outlook.cn | 2026-10-23T12:12:24.160188+00:00 |
| `http://mms.stu.edu.cn/` | 会务管理系统<br>郁金香 /  | 404 | 2026-10-23T12:12:24.207073+00:00 |
| `http://mrp.stu.edu.cn/` | 物料管理系统<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 301；external redirect not followed → https:/// | 2026-10-23T12:12:24.239069+00:00 |
| `http://neie.stu.edu.cn/web/login.aspx` | 英语自主学习<br>郁金香 / html/catalog/2520.htm | ConnectTimeout: timed out | 2026-10-23T12:12:24.326763+00:00 |
| `http://newcourse.stu.edu.cn/` | 新教学模式网<br>郁金香 / html/catalog/2520.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:29.348394+00:00 |
| `http://norton.med.stu.edu.cn/` | 反病毒系统<br>郁金香 / html/catalog/2520.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:29.368334+00:00 |
| `http://ogs.stu.edu.cn/` | 固资查询系统<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:29.417174+00:00 |
| `http://outlay.stu.edu.cn/` | 学生经费管理  /  学生经费管理系统<br>郁金香 /   /  郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 403 | 2026-10-23T12:12:29.438632+00:00 |
| `http://phoenix.stu.edu.cn/bt/default.aspx` | 金凤BT<br>郁金香 /   /  郁金香 / html/catalog/2354.htm | 200 | 2026-10-23T12:12:29.505166+00:00 |
| `http://qgjx.stu.edu.cn/` | 勤工俭学申请系统  /  勤工助学申请<br>郁金香 /   /  郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2308.htm  /  郁金香 / html/catalog/2354.htm | 403 | 2026-10-23T12:12:29.788527+00:00 |
| `http://quality.stu.edu.cn/` | 本科教学质量保障平台<br>官网快速通道 | 200 | 2026-10-23T12:12:29.825075+00:00 |
| `http://reg.stu.edu.cn/` | 新生入学管理系统(校内)<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:29.877608+00:00 |
| `http://scholarship.stu.edu.cn/` | 汕大奖学金  /  汕头大学奖学金<br>郁金香 / html/catalog/2308.htm  /  郁金香 / html/catalog/2354.htm | 200 → https://scholarship.stu.edu.cn/ | 2026-10-23T12:12:29.897467+00:00 |
| `http://security.stu.edu.cn/` | 安防系统<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:30.092368+00:00 |
| `http://sro.stu.edu.cn/` | 科研管理平台  /  科研管理系统<br>郁金香 /   /  官网快速通道 | 302；authentication boundary; not requested → http://sso.stu.edu.cn/login?service=https://sro.stu.edu.cn/default.aspx | 2026-10-23T12:12:30.111841+00:00 |
| `http://support.stu.edu.cn/` | 邮箱业务<br>https://info.stu.edu.cn/its/info/1184/4070.htm | 200 | 2026-10-23T12:12:30.194768+00:00 |
| `http://syzx.med.stu.edu.cn/` | 汕医勤工助学网<br>郁金香 / html/catalog/2520.htm | ConnectTimeout: timed out | 2026-10-23T12:12:30.946336+00:00 |
| `http://test.med.stu.edu.cn/ot` | 生物化学与分子生物学课程自测系统<br>郁金香 / html/catalog/2520.htm | RemoteProtocolError: Server disconnected without sending a response. | 2026-10-23T12:12:36.027953+00:00 |
| `http://update.med.stu.edu.cn/` | 自动更新系统<br>郁金香 / html/catalog/2520.htm | ConnectTimeout: timed out | 2026-10-23T12:12:36.089233+00:00 |
| `http://usmle.med.stu.edu.cn/` | 美国职业医师在线考试系统<br>郁金香 / html/catalog/2520.htm | 200 → http://usmle.med.stu.edu.cn/CommonAdmin/Login.aspx | 2026-10-23T12:12:41.147527+00:00 |
| `http://vc.stu.edu.cn/` | 虚拟教室  /  虚拟教室(my stu)<br>郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2374.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:41.628516+00:00 |
| `http://webmail.stu.edu.cn/` | 汕大WEB邮箱  /  汕大邮箱<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm  /  郁金香 / html/catalog/2512.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:41.647096+00:00 |
| `http://www.med.stu.edu.cn/xw/yjs/userlogin.aspx` | 选择导师网络报名系统<br>郁金香 / html/catalog/2520.htm | 404 | 2026-10-23T12:12:41.665540+00:00 |
| `http://www.med.stu.edu.cn/xw/zp/index.aspx` | 人才招聘<br>郁金香 / html/catalog/2520.htm | 404 | 2026-10-23T12:12:46.722903+00:00 |
| `http://www.scholarship.stu.edu.cn/chinese` | 奖学金申请<br>郁金香 / html/catalog/2292.htm  /  郁金香 / html/catalog/2354.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:51.759161+00:00 |
| `http://www.scholarship.stu.edu.cn/chinese/scholarList.aspx` | 奖学金申请<br>郁金香 /  | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:51.777749+00:00 |
| `http://xyh.stu.edu.cn/` | 校友会网站  /  校友邮箱<br>郁金香 / html/catalog/2311.htm  /  郁金香 / html/catalog/2354.htm | 200 → https://xyh.stu.edu.cn/alumni/front/account/index.jsp | 2026-10-23T12:12:51.791769+00:00 |
| `http://xyh.stu.edu.cn/AlumniIntro.aspx?id=a33c719a-6fde-4de4-a6ce-16b14651aac4` | 校友会分陀<br>郁金香 / html/catalog/2311.htm | 404 → https://xyh.stu.edu.cn/AlumniIntro.aspx?id=a33c719a-6fde-4de4-a6ce-16b14651aac4 | 2026-10-23T12:12:53.514730+00:00 |
| `http://xyh.stu.edu.cn/AlumniLogin.aspx` | 汕大校友数据库<br>郁金香 / html/catalog/2311.htm | 404 → https://xyh.stu.edu.cn/AlumniLogin.aspx | 2026-10-23T12:12:53.611524+00:00 |
| `http://xyh.stu.edu.cn/class.asp` | 校友社区<br>郁金香 / html/catalog/2354.htm | 404 → https://xyh.stu.edu.cn/class.asp | 2026-10-23T12:12:53.675728+00:00 |
| `http://xyh.stu.edu.cn/details.aspx?id=6c2925f7-6fe8-4b6e-bb75-07359516e7da` | 申请校友卡<br>郁金香 / html/catalog/2311.htm | 404 → https://xyh.stu.edu.cn/details.aspx?id=6c2925f7-6fe8-4b6e-bb75-07359516e7da | 2026-10-23T12:12:53.741462+00:00 |
| `http://zs.stu.edu.cn/RecruitStudents/WebForm/Search.aspx` | 录取查询  /  本科录取查询<br>郁金香 /   /  郁金香 / html/catalog/2308.htm | 404 → https://zs.stu.edu.cn/RecruitStudents/WebForm/Search.aspx | 2026-10-23T12:12:53.798074+00:00 |
| `http://zsxx.med.stu.edu.cn/` | 终身学习网<br>郁金香 / html/catalog/2520.htm | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:12:53.851965+00:00 |
| `http://zxsys.stu.edu.cn/` | 中心实验室  /  中心实验室(校内)  /  中心实验室（分析测试中心）<br>郁金香 /   /  郁金香 / html/catalog/2298.htm  /  郁金香 / html/catalog/2354.htm  /  官网快速通道 | 200 → https://zxsys.stu.edu.cn/genee/ | 2026-10-23T12:12:53.897767+00:00 |
| `http://zxsys.stu.edu.cn/genee/` | 中心实验室<br>官网快速通道 | 200 → https://zxsys.stu.edu.cn/genee/ | 2026-10-23T12:12:54.077880+00:00 |
| `https://cwc.stu.edu.cn/` | <br>https://info.stu.edu.cn/its/wlfw/yhfw.htm | ReadTimeout: The read operation timed out | 2026-10-23T12:12:54.212891+00:00 |
| `https://gsao.stu.edu.cn/` | https://gsao.stu.edu.cn<br>数学系常用网站 | ReadTimeout: The read operation timed out | 2026-10-23T12:13:02.290574+00:00 |
| `https://jgsw.gd.gov.cn/gcglpt/Home/Login` | 车队管理系统<br>官网快速通道 | 200 | 2026-10-23T12:13:10.398941+00:00 |
| `https://lrao.stu.edu.cn/lrao/` | https://lrao.stu.edu.cn/lrao/<br>数学系常用网站 | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https%3A%2F%2Flrao.stu.edu.cn%2Flrao%2F | 2026-10-23T12:13:10.717007+00:00 |
| `https://parking.stu.edu.cn/parking/approval.html` | 车辆人员进校审批<br>官网快速通道 | 200 | 2026-10-23T12:13:10.792739+00:00 |
| `https://partner.outlook.cn/` | 汕大邮箱  /  邮箱系统<br>官网快速通道 | 200 → https://partner.outlook.cn/mail/ | 2026-10-23T12:13:10.862213+00:00 |
| `https://sro.stu.edu.cn/` | https://sro.stu.edu.cn<br>数学系常用网站 | 302；authentication boundary; not requested → http://sso.stu.edu.cn/login?service=https://sro.stu.edu.cn/default.aspx | 2026-10-23T12:13:11.383635+00:00 |
| `https://support.stu.edu.cn/` | Office365客户端<br>官网快速通道 | 200 | 2026-10-23T12:13:11.446761+00:00 |
| `https://wpay.stu.edu.cn/login` | 财务综合服务平台（新版）<br>官网快速通道 | 200 | 2026-10-23T12:13:11.579845+00:00 |
| `https://zs.stu.edu.cn/zxfw/lqjgcx1.htm` | 本科录取查询<br>郁金香 /  | 200 | 2026-10-23T12:13:11.677095+00:00 |
| `https://ztbzx.stu.edu.cn/lyuapServer.do?login` | 采购管理系统<br>官网快速通道 | 200 | 2026-10-23T12:13:11.748345+00:00 |
| `https://wpay.stu.edu.cn/api/logcas/checkTicket` | 财务综合服务平台（新版）<br>官网快速通道 live 2026-10-23 | 200 → https://wpay.stu.edu.cn/logCas | 2026-10-23T12:13:11.815899+00:00 |
| `https://jgsw.gd.gov.cn/gcglpt/Home/Login#carTask` | 车队管理系统<br>官网快速通道 live 2026-10-23 | 200 | 2026-10-23T12:13:12.015368+00:00 |

## 补充读取与静态脚本证据

以下均是页面实际引用、明确的公开静态接口，或有标明的坏链接规范化候选。静态脚本获取成功不等于其中业务接口执行成功。

| 补充 URL | 结果 | 核查时间 UTC |
| --- | --- | --- |
| `https://www.stu.edu.cn/kstd.htm` | 200 | 2026-10-23T12:11:09.644839+00:00 |
| `https://d.stulip.org/` | 200 | 2026-10-23T12:10:05.588489+00:00 |
| `https://info.stu.edu.cn/its/info/1184/4070.htm` | 200 | 2026-10-23T12:10:06.565468+00:00 |
| `https://parking.stu.edu.cn/parking/management/` | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https%3A%2F%2Fparking.stu.edu.cn%2Fparking%2Fmanagement%2F | 2026-10-23T12:13:22.901899+00:00 |
| `https://parking.stu.edu.cn/motorcycle/management/` | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https%3A%2F%2Fparking.stu.edu.cn%2Fmotorcycle%2Fmanagement%2F | 2026-10-23T12:13:23.176956+00:00 |
| `https://wechat.stu.edu.cn/health-report/management/` | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https%3A%2F%2Fwechat.stu.edu.cn%2Fhealth-report%2Fmanagement%2F | 2026-10-23T12:13:23.244384+00:00 |
| `http://efms.stu.edu.cn/login.aspx` | 200 | 2026-10-23T12:13:23.305083+00:00 |
| `http://efms.stu.edu.cn/guide.aspx` | 200 | 2026-10-23T12:13:23.442638+00:00 |
| `https://scholarship.stu.edu.cn/ListExtendSQLB.aspx` | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https://scholarship.stu.edu.cn/admin.aspx | 2026-10-23T12:13:23.513450+00:00 |
| `http://carfleet.stu.edu.cn/System_Menu.aspx` | 200 | 2026-10-23T12:13:23.645648+00:00 |
| `http://carfleet.stu.edu.cn/left.htm` | 200 | 2026-10-23T12:13:23.734880+00:00 |
| `https://support.stu.edu.cn/office365/help.html` | 200 | 2026-10-23T12:13:23.765544+00:00 |
| `https://support.stu.edu.cn/office365/download.html` | 200 | 2026-10-23T12:13:23.862140+00:00 |
| `http://quality.stu.edu.cn/js/config.js` | 200 | 2026-10-23T12:14:00.559398+00:00 |
| `http://quality.stu.edu.cn/js/common~app.c4c4bd85.js` | 200 | 2026-10-23T12:14:00.901429+00:00 |
| `http://quality.stu.edu.cn/js/app.f5dcde45.js` | 200 | 2026-10-23T12:14:01.054369+00:00 |
| `https://wpay.stu.edu.cn/appconfig.js` | 200 | 2026-10-23T12:14:01.244864+00:00 |
| `https://wpay.stu.edu.cn/js/chunk-common.20772bb8.js` | 200 | 2026-10-23T12:14:01.334943+00:00 |
| `https://wpay.stu.edu.cn/js/index.c69dd6b5.js` | 200 | 2026-10-23T12:14:01.521622+00:00 |
| `https://support.stu.edu.cn/js/js.js` | 200 | 2026-10-23T12:14:01.700250+00:00 |
| `https://gdc.stu.edu.cn/Scripts/Basic.js` | 200 | 2026-10-23T12:14:01.818230+00:00 |
| `https://gdc.stu.edu.cn/js/Main?v=1.0.0` | 200 | 2026-10-23T12:14:02.033305+00:00 |
| `https://gdc.stu.edu.cn/Scripts/index.js?v=21` | 200 | 2026-10-23T12:14:02.586201+00:00 |
| `https://xyh.stu.edu.cn/alumni/front/account/index.js?_v=2.65` | 200 | 2026-10-23T12:14:02.846727+00:00 |
| `http://192.168.48.148:8083/gdczsam/index.js` | 200 | 2026-10-23T12:14:02.921740+00:00 |
| `http://192.168.48.148:8083/gdczsam/core/js/tools/ajax.js` | 200 | 2026-10-23T12:14:02.962020+00:00 |
| `http://efms.stu.edu.cn/script/page-digest-init.js` | 200 | 2026-10-23T12:14:03.035163+00:00 |
| `https://sumcapi.med.stu.edu.cn/oa_notice.php` | 200 | 2026-10-23T12:14:03.086419+00:00 |
| `https://dzb.med.stu.edu.cn/` | 200 | 2026-10-23T12:14:03.535199+00:00 |
| `https://oa.med.stu.edu.cn/seeyon/caslogin/sso` | 200 → https://sso.med.stu.edu.cn/cas/login?service=https%3A%2F%2Foa.med.stu.edu.cn%3A443%2Fseeyon%2Fcaslogin%2Fsso | 2026-10-23T12:14:03.815180+00:00 |
| `https://jwgl.med.stu.edu.cn/new/welcome.page?ui=new` | 200 → https://sso.med.stu.edu.cn/cas/login?service=https%3A%2F%2Fjwgl.med.stu.edu.cn%2Fnew%2FssoLogin | 2026-10-23T12:14:03.932512+00:00 |
| `https://yxykygl.med.stu.edu.cn/userAction!do_casLogin.action` | 200 → https://sso.med.stu.edu.cn/cas/login?service=https%3A%2F%2Fyxykygl.med.stu.edu.cn%2FuserAction%21do_casLogin.action | 2026-10-23T12:14:04.040107+00:00 |
| `https://yjszs.med.stu.edu.cn/` | 200 | 2026-10-23T12:14:04.150608+00:00 |
| `https://syzwc.med.stu.edu.cn/152/list_152_1.html` | 200 | 2026-10-23T12:14:04.228091+00:00 |
| `https://ywtb.med.stu.edu.cn/` | 200 | 2026-10-23T12:14:04.298136+00:00 |
| `https://keyan.med.stu.edu.cn/` | 200 | 2026-10-23T12:14:04.428446+00:00 |
| `https://ywtb-workflow.med.stu.edu.cn/s/9LimoXmZ` | 200 | 2026-10-23T12:14:04.519954+00:00 |
| `http://zxsys.med.stu.edu.cn/equip.php` | 200 | 2026-10-23T12:14:04.570312+00:00 |
| `https://equip.stu.edu.cn/default.htm` | 200 | 2026-10-23T12:14:06.244856+00:00 |
| `https://lrao.stu.edu.cn/med/` | 302；authentication boundary; not requested → https://sso.stu.edu.cn/login?service=https://lrao.stu.edu.cn/med/ | 2026-10-23T12:14:06.381254+00:00 |
| `http://project.stu.edu.cn/` | 200 | 2026-10-23T12:14:06.529264+00:00 |
| `http://credit.stu.edu.cn/Course/DispCourseList.aspx` | 200 | 2026-10-23T12:14:06.576199+00:00 |
| `http://credit.stu.edu.cn/Elective/DispClassList.aspx` | 200 | 2026-10-23T12:14:07.646710+00:00 |
| `http://credit.stu.edu.cn/TrainPlan/DisplayKcPlan.aspx` | 200 | 2026-10-23T12:14:07.907380+00:00 |
| `https://zxsys.stu.edu.cn/genee/category/equipment` | 200 | 2026-10-23T12:14:08.033250+00:00 |
| `https://gdc.stu.edu.cn/JobFair/InnerTalk` | 200 | 2026-10-23T12:14:08.245678+00:00 |
| `https://gdc.stu.edu.cn/Search/SearchJob` | 200 | 2026-10-23T12:14:08.586323+00:00 |
| `https://job.stu.edu.cn/product/recruit/website/RecruitPostNew.jsp?FM_SYS_ID=stdx` | 200 | 2026-10-23T12:14:09.470512+00:00 |
| `http://bgs.med.stu.edu.cn/search.htm` | 200 | 2026-10-23T12:14:09.569813+00:00 |
| `http://quality.stu.edu.cn/js/chunk-2d231588.ef3aed46.js` | 200 | 2026-10-23T12:16:21.175718+00:00 |
| `http://quality.stu.edu.cn/js/chunk-a2f25748.07bab72e.js` | 200 | 2026-10-23T12:16:21.513543+00:00 |
| `http://quality.stu.edu.cn/api/AuthenticationController/getLoginType` | 200 | 2026-10-23T12:16:21.558308+00:00 |
| `http://quality.stu.edu.cn/api/AuthenticationController/getTitle` | 401 | 2026-10-23T12:16:21.590654+00:00 |
| `https://gdc.stu.edu.cn/JobFair/GetDiaryJobFair?month=2026.10` | 200 | 2026-10-23T12:16:21.637303+00:00 |
| `https://gdc.stu.edu.cn/Home/get_event_data?month=2026.10&day=23` | 200 | 2026-10-23T12:16:21.936226+00:00 |
| `https://keyan.med.stu.edu.cn/?page=1` | 200 | 2026-10-23T12:16:22.232619+00:00 |
| `https://sumcapi.med.stu.edu.cn/article.php?ws=oa&aid=-8708005647585817257` | 200 | 2026-10-23T12:16:22.374022+00:00 |
| `https://sumcapi.med.stu.edu.cn/oa_notice.php?tab=stu` | 200 | 2026-10-23T12:16:22.426821+00:00 |
| `https://yjszs.med.stu.edu.cn/public/index.html` | 200 | 2026-10-23T12:16:22.680618+00:00 |
| `https://ywtb.med.stu.edu.cn/index/index/services_system` | 200 | 2026-10-23T12:16:22.759587+00:00 |
| `http://project.stu.edu.cn/Scripts/Pub/user.js` | 200 | 2026-10-23T12:16:22.819637+00:00 |
| `http://project.stu.edu.cn/Scripts/pub/ccenter.js` | 200 | 2026-10-23T12:16:22.867292+00:00 |
| `https://zs.stu.edu.cn/system/resource/js/openapp/api.js` | 200 | 2026-10-23T12:16:22.900633+00:00 |
| `http://yeji.med.stu.edu.cn/` | 200 | 2026-10-23T12:18:01.259829+00:00 |
| `http://stulac.med.stu.edu.cn/book/member/login.php` | 200 | 2026-10-23T12:18:01.632143+00:00 |
| `https://xnpj.med.stu.edu.cn/index.php?action=login` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:18:01.785367+00:00 |
| `http://www.stulc.stu.edu.cn/it4.htm` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:18:01.836076+00:00 |
| `https://yjszs.med.stu.edu.cn/supervisor/supervisor.php` | 200 | 2026-10-23T12:18:01.857492+00:00 |
| `http://credit.stu.edu.cn/Info/DisplayDeptStat.aspx` | 200 | 2026-10-23T12:18:01.953211+00:00 |
| `http://credit.stu.edu.cn/ClassRoom/ViewAll.aspx` | 200 | 2026-10-23T12:18:09.569009+00:00 |
| `https://www.gs.stu.edu.cn/` | ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl. | 2026-10-23T12:24:30.055132+00:00 |
| `https://rsc.stu.edu.cn/MainSite/Index.aspx` | 200 | 2026-10-23T12:24:30.306279+00:00 |
| `https://zyc.stu.edu.cn/` | 200 | 2026-10-23T12:24:30.474007+00:00 |
| `http://kyc.stu.edu.cn/` | 200 → https://kyc.stu.edu.cn/ | 2026-10-23T12:24:30.520690+00:00 |
| `http://el.med.stu.edu.cn/` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:26:55.788827+00:00 |
| `http://jsj.med.stu.edu.cn/` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:26:56.021432+00:00 |
| `http://syjob.med.stu.edu.cn/` | 200 | 2026-10-23T12:26:56.082373+00:00 |
| `http://yjs.med.stu.edu.cn/` | 200 | 2026-10-23T12:26:59.902695+00:00 |
| `http://yjs.med.stu.edu.cn/forum` | 404 | 2026-10-23T12:26:59.964411+00:00 |
| `http://yjs.med.stu.edu.cn/yjs` | 404 | 2026-10-23T12:27:00.003234+00:00 |
| `http://gc.med.stu.edu.cn/member/login.php` | 200 | 2026-10-23T12:27:24.974851+00:00 |
| `http://gse.med.stu.edu.cn/member/login.php` | ConnectTimeout: timed out | 2026-10-23T12:27:25.282623+00:00 |
| `https://yjs-sys.med.stu.edu.cn/index/user/login` | 200 | 2026-10-23T12:27:30.346701+00:00 |
| `http://activity.stu.edu.cn/` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:32:52.159372+00:00 |
| `http://xlcs.stu.edu.cn/Login.aspx` | 200 | 2026-10-23T12:32:52.387033+00:00 |
| `http://cwk.med.stu.edu.cn/` | 200 | 2026-10-23T12:32:52.456101+00:00 |
| `http://newcourse.med.stu.edu.cn/` | 名称解析失败（本机解析器，非权威 NXDOMAIN 断言） | 2026-10-23T12:32:52.530926+00:00 |
| `https://mcm.stu.edu.cn/` | 200 | 2026-10-23T12:32:52.575010+00:00 |
| `http://io.stu.edu.cn/` | 200 → http://io.stu.edu.cn/web/ | 2026-10-23T12:32:53.519266+00:00 |
| `http://192.168.48.189:8080/system/login.jsp` | 200 | 2026-10-23T12:32:54.590515+00:00 |
| `http://io.stu.edu.cn/web/js/OpenGame.js` | 200 | 2026-10-23T12:33:25.076840+00:00 |
| `http://io.stu.edu.cn/web/js/FsCommand.js` | 200 | 2026-10-23T12:33:25.321849+00:00 |
| `http://io.stu.edu.cn/sso` | 200 → http://io.stu.edu.cn/sso/ | 2026-10-23T12:33:25.359393+00:00 |
| `http://cwk.med.stu.edu.cn/2/98.html` | 200 | 2026-10-23T12:33:25.662121+00:00 |
| `http://cwk.med.stu.edu.cn/2/104.html` | 200 | 2026-10-23T12:33:25.707677+00:00 |
| `http://www.gs.stu.edu.cn/` | ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl. | 2026-10-23T12:43:17.089395+00:00 |

本轮总计 180 个不同 URL；同一首页因编码核验重复读取一次，不能重复计作新入口。
