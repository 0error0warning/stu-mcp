# 行政、科研、财务、招生校友及医学院入口补查

这是入口与协议调查，不是 MCP 已接入功能清单。承接
[其他业务初查](other-business.md)及[入口覆盖表](entry-coverage.csv)，本轮只补行政和医学院
业务；`r`、综测暂停，未再请求；课程目录、主校就业和主校大型仪器另有专项报告，不重复采集。

本组匿名实测时间为 **2026-10-23 15:55:50–16:15:55 UTC**（北京时间当日
23:55:50 至次日 00:15:55），共 **164 次请求：133 GET、31 只读查询 POST**。
POST 仅用于页面真实声明的公开事项检索/分页、校友文章搜索和教学项目文件列表查询。
没有登录 POST、人员信息查询、角色切换、申请、激活、报名、签约、支付、验证码请求或附件下载。
另有根调查进程的本人 SSO 续票结果，单独标明，不混入本组 164 次匿名计数。

请求使用 `httpx`、`trust_env=False`、正常 TLS 校验、连接超时 5 秒、其余超时 10 秒；
独立站点最多 4 个并发，同站按顺序读取，自动重定向关闭，后续只跟页面真实目标。
一般请求用新匿名客户端；教学项目新鲜查询表单和医学院目录顺序分页各自复用独立匿名客户端。
这排除了应用环境代理，不证明系统 TUN 的实际路径或所有校外网络的可达性。未改网络设置。

证据位于被忽略的 `output/campus-protocol-survey/administration-completion/`：
`requests.jsonl` 只保留状态、公开链接/字段名、JSON 结构/计数和脚本原始字节哈希；
未保存 HTML 正文、表单隐藏值、cookie、CAS 票据、查询人员信息或目录中的负责人/电话。
公开事项清单见 [medical-service-matters.csv](medical-service-matters.csv)。

证据等级沿用初查：**实测**是该次 HTTP 响应；**静态声明**是页面/脚本协议，未执行该业务；
**官网说明**是发布文字，不等于相应业务接口已验证；**未知/受阻**保留具体条件，不能推断停用。

## 1. 本部财务、科研、资产与人事

| 业务 | 本轮实际入口/边界 | 可读与仍未知 |
| --- | --- | --- |
| 财务处公开信息 | `http://cwc.stu.edu.cn/` 200 | 通知/指南，与个人财务不同；不是工资或缴费查询成功 |
| 新财务 `wpay` | 官网 `/api/logcas/checkTicket` 302 至同站 `/logCas`，SPA 200 | 取得实际 CAS 组件及菜单协议；匿名这次没有学校 CAS service，未取得财务 token |
| 科研 `sro` | `https://sro.stu.edu.cn/default.aspx` 302，Location 为 HTTP SSO，service 保持该 HTTPS 地址 | 本组在 HTTP 认证边界停止；根进程本人续票结果见下段 |
| 科研医学院旧别名 `medsro` | 从 `sro` 本人回执提示的裸主机名规范化为 HTTPS 根候选，302 至 HTTP SSO，service 为 `https://medsro.stu.edu.cn/default.aspx` | 不是猜测 `default.aspx` 后探测；路径来自实际 Location。未跟 HTTP SSO，不与医学院当前科研入口自动合并 |
| 人事 `hr` | HTTP 根 301 至 HTTPS，HTTPS 根 302 至 `http://hr.stu.edu.cn/base/frame/main_stdx.jsp?FM_SYS_ID=stdx` | 本轮只到该中间目标；初查已记录学校 SSO，人员/工资业务没有读取 |
| 资源事务 `lrmo` | `https://lrmo.stu.edu.cn/Home.aspx` 302 学校 HTTPS SSO，同地址 service | 独立业务菜单、身份、数据模型未知 |
| 固资 `lrao` | `https://lrao.stu.edu.cn/lrao/` 302 学校 HTTPS SSO，同路径 service | 未认证；本部 `/lrao/` 与医学院 `/med/` 不能换用 |
| `equip` | HTTP 根 200，近空，给出 `lrao` 等链接 | 不是资产列表或会话成功；裸 IP 资产平台、`/service.do` RPC 静态合同保留初查证据，未重复 RPC |
| 旧财务裸 IP | `192.168.48.249/dlpt/login.aspx` 的 WebForms 及改用新平台说明见初查 | 本轮未重提旧密码、不读取人员记录；说明“改用新版”不能证明旧版何时停用 |

**根进程另行本人核查，约 16:06 UTC：**学校 SSO 向固定 HTTPS `sro/default.aspx` 发新票据后，
回调 200 仅 854 字节。页面内嵌提示明确称当前个人信息未引入科研系统，暂不能使用，并让
医学院及附属医院教师另看 `medsro.stu.edu.cn`，随后跳科研处 `http://kyc.stu.edu.cn`。
这条“未引入”来自实际业务提示，不是由小页面、200 或学生身份猜出的权限结论。
没有科研项目/成果/经费菜单，不代表服务对其他合法账号不可用。

**根进程另行 `medsro` 本人核查，16:15:05 UTC：**在上述实际 Location 确认固定 HTTPS
`default.aspx` 后，按学校 SSO 新票据回调取得 813 字节 WebForms 200；内嵌提示同样明确
个人信息未引入，没有业务菜单。它与 `sro` 都是这次账号资料未导入的实际回执，
仍不能据此证明与独立医学院 SSO 同一主体、同一权限或现代科研平台已迁移。
安全摘要位于根进程的 `output/campus-protocol-survey/entry-completion/observations.jsonl`，
`source=medsro,name=extra-auth`；无票据/cookie 出现在本文。

### `wpay` 的真实认证与读取合同（静态）

`/logCas` 的路由来自 `chunk-common.20772bb8.js`，加载器 `index.c69dd6b5.js` 将它解析为
`/js/chunk-40ab330c.6eb7edfe.js`；三个脚本均实际 GET 200。CAS 组件并非“拿 CAS cookie 直接读财务”：

1. 从路由 query 读取 `cas`、`ticket`、`sysid`，当前组件实际将 **cas** 传给
   `GET /api/logcas/caslogintoken?cas=<本次回调结果>`；返回 `code` 转字符串为 `200` 后，`data` 作为用户名。
2. `GET /api/user/pubkey`，取本次 `data.sessionId`、`data.publicKey`。
3. 用官方 JSEncrypt 公钥分别加密本次 `cas` 和固定登录方式字符串，再
   `POST /api/login`，`application/x-www-form-urlencoded`，字段
   `username,password,sessionId,dlfs`。这是独立财务认证握手，未在本组执行。
4. `code=200` 的 `data` 被用于 `token,suid,uname,date`；若 `isyz` 指向身份证校验分支，
   页面会要求另行验证，不能自动填写或假定跳过。令牌后续放 `Authorization: Bearer ...`。
5. `POST /api/getUserInfo`、`POST /api/getMenuTree` 为身份/获授菜单读接口，前端按
   `code` 转字符串等于 `200` 后取 `data`；没有凭据不能将它们当已核实个人读合同。

旧初查中的二维码、图片校验、密码分支仍只是发行脚本声明，本轮没有执行。
`/api/xtQueryConfig/getXtQueryConfig`、`/api/xtTableConfig/getXtTableConfig` 是配置驱动查询，
现有公开代码不足以列出本人实际可查的财务项目或确定所有过滤/分页字段。
本组匿名 `/api/logcas/checkTicket` 只给无 query 的 `/logCas`，**没有拿到本校 CAS 发起 service**；
不能自行构造一个 SSO 地址，或将组件里声明的 `cas` 换成 `ticket`。
根进程 16:09:51 UTC 又以独立研究客户端读取官网相同入口，仍仅 302 至无 query 的
`/logCas`，未取得临时 `cas`，未猜 service 或发送密码。真实认证发起链仍未闭合。

## 2. 校门、车队、档案、公文与采购

### 校门和车队

官网 `https://parking.stu.edu.cn/parking/approval.html` 200，明确列三个不同业务：

| 业务 | 精确入口，同时为匿名重定向中的 HTTPS service | 根进程另行本人续票结果 |
| --- | --- | --- |
| 汽车进校 | `https://parking.stu.edu.cn/parking/management/` | 16:05–16:06 UTC，票据回调 302 至无票据原路径，再 GET 401 JSON |
| 摩托/非机动车 | `https://parking.stu.edu.cn/motorcycle/management/` | 相同顺序到 401 JSON |
| 访客进校 | `https://wechat.stu.edu.cn/health-report/management/` | 本人回调后 500，未取得页面/菜单 |

两个 401 的 JSON 包装为 `timestamp,status,error,message,path`，提示 `No message available`；
不能直接归因学生角色，也不能当申请列表为空。三个业务均没有取得实际表单或个人历史读合同。
`health-report` 路径名不能覆盖官网当前“访客进校审批”的业务身份。

`http://carfleet.stu.edu.cn/index.htm` 本轮仍 200 frameset，实际 frame 为 `Top.aspx`、
`System_Menu.aspx`、`left.htm`、`Page/Car_Application_Add.aspx`。未打开申请 frame。
当前官网的省公务用车平台独立账号/验证码/OAuth 边界见初查，本轮不重复认证。
旧校园车队与省平台的数据、身份互通未知。

### 档案及受阻旧入口

| 精确入口 | 本轮结果 | 合同与边界 |
| --- | --- | --- |
| `http://efms.stu.edu.cn/index.aspx` | 200 综合档案室 | 公开通知、归档操作说明、展厅和服务指南，不是财务系统 |
| `/guide.aspx` | 200 | 明确档案利用说明，审批表/委托书真实链接；未下载、未申请 |
| `/login.aspx` | 200 WebForms | POST 自身，`ctl00$main$txtUserID,ctl00$main$txtUserPwd,ctl00$main$btnLogin` + 当前页面状态；未认证，不能推已接 CAS |
| `/script/page-digest-init.js` | 200 | 实际仅导航/滚动/布局交互，没有读接口或认证挑战；不能从文件名推“摘要验证” |
| `http://infor.stu.edu.cn/index.aspx` | 301 HTTPS 后 502 | 信息报送表单/读取接口均未取得 |
| `http://information.stu.edu.cn/` | 名称解析失败 | 独立旧别名；没有迁移证明 |
| `http://gongwen.stu.edu.cn/` | 302 HTTPS 后 200 **零字节** | 未返回公文列表，不能宣称可读公文 |
| `http://mms.stu.edu.cn/` | 404 | 会务标签之外无当前合同 |
| `http://mrp.stu.edu.cn/` | 301，Location `https:///` | 官方重定向缺主机，停止；未猜修正地址 |

### 招投标：公开公告与独立办理分开

旧官网链接 `/lyuapServer.do?login` 返回 200 但仅 152 字节，没表单/脚本/业务内容。
本轮另跟 **官网根**的实际跳转：`/` → `302 /loginController.do?login` → `302 /gateway.do`
→ `200 汕头大学招投标中心`。匿名会话路径标识不写入报告。

| 已实际请求的公开读路径 | 方法/参数 | 响应及字段 |
| --- | --- | --- |
| `/gateway.do` | GET | 公开采购门户，栏目、公告及办理登录链接 |
| `/portalwebController.do?goAtriclelist&articltype=cggg&page=1&rows=16` | GET；action 参数名保留官方拼写 **goAtriclelist** | HTML，16 个实际 `goArticleDetail` 链接；不是 JSON |
| 同列表 `page=2&rows=10` | GET；来自实际页码链接 | HTML，10 个文章详情链接。页面生成的页码链接使用 `rows=10`，不能假设沿用调用者的 16 |
| `/portalwebController.do?goArticleDetail&id=<列表公开文章 ID>` | GET，抽一条真实公告 | 200，标题“汕头大学理学院海洋调查实习船舶租赁服务采购项目自主公开招标公告”；正文页可读，不下载投标附件 |

门户真实栏目还包括 `jgsz,zbjs,xwtz,tzgg,ttxw,gzzd,gj,sj,xngdzd,bszn,hwl,gcl,fwl,jggs,xzzx,lxfs`，
以及 `goArticlebfilelist`。这些是实际链接的枚举，不代表所有栏目、空态和附件均已请求。

办理登录是 `/gateway.do?login`（200），显示独立用户名/密码；公开 `js/login.js` 声明：
`POST /loginController.do?checkuser&isYzm=1`，收表单输入并添加 `orgId`，用户名/密码使用
页面 AES-ECB-PKCS7 处理，解析 `success,msg,attributes.orgNum`。多组织分支会要求选择机构，
之后还有更改默认机构动作。**本轮没有执行任何认证/选机构/采购申请，未观察到学校 CAS 路线。**
HTML 的默认 form 方法不是实际 JS 登录协议；不能因为样式框架与别站相同就复用认证。

## 3. 教学项目、学校招聘、校友和本科招生

### 教学项目 `project`

根 `http://project.stu.edu.cn/` 200，保留原导航重复 `http://http://` 的修正来源说明，
不声称原错误 URL 可用。账号由平台分发的官网说明见初查；没有 CAS 成功证据。

| 路径 | 实际方法与输入 | 结果/意义 |
| --- | --- | --- |
| `/CCenter/MoreFileMan?id=21|22` | GET，主页真实通知/资料栏目 | 均 200 壳，不能据壳判列表为空 |
| `/CCenter/ZlgcNoteMenuMan` | GET，来自当前 `ccenter.js` 的 `loadcontent` | 200，`viewName` 真实值为 `/CCenter/MoreNote?id=21|22` |
| `/CCenter/MoreNote?id=21|22` | GET | 均 200，实际查询 form `informfilesearchform` 为 POST，字段 `searchpidx,utypeidx,searchname` |
| `/Note/NoteInformFilelist` | **POST 只读查询**，字段取各类别的新鲜原表单，未构造隐藏值 | 两类别均 **500“错误”页**，16:10:32 UTC；没有文件列表成功响应或正常空态证据 |

方法依据：`myform.js` 的 `loadcontent` 使用 GET，`submitfrm_content` 使用原 form 提交；
`note.js` 的 `InformFileList()` 将此 form 发至上述读取路由，分页从返回 `.pidx[pidx]` 取值。
错误结果不证明必须登录，也不能将“成功取得请求参数”写成“公开列表读取成功”。
公开首页另声明 `/PublicHtml/Index/Inform/file1.html` 和 `file3.html` 的静态读链，
本轮未下载对应列表或手册 PDF。`note.js` 中的保存/删除方法明确不执行。

`action.stu.edu.cn` 本轮名称解析仍失败；它与 `project`、科研 `sro` 的关系未知。

### 工作人员招聘 `job` 与校友 `xyh`

- `https://job.stu.edu.cn/product/recruit/website/RecruitPostNew.jsp?FM_SYS_ID=stdx`
  200，页面明确 **共 0 条**；真实分页链接含 `page`、`postTypeCode`。这是本次该栏目空态，
  不是永久无招聘。公告、指南、联系入口仍为独立 `Recruit*New.jsp`；指南本轮也 200。
  既有邮箱注册、独立简历/应聘账号的说明仍适用；未注册/应聘，不与学生就业 `gdc` 合并。
- `https://xyh.stu.edu.cn/alumni/front/account/index.jsp` 200，当前校友公开新闻、
  列表和详情链接可见。真实 form **没有** `.searchForm` class，POST `search.jsp`、字段
  `keyword`，本轮以固定无匹配词实际 POST，200 返回搜索壳，无新闻详情结果链接。
  不能按未匹配本页的通用 `public_search.js` 处理成 `search.html?key=`。
- 当前搜索页实际 `search.js` 声明 GET `./search.jsp?type=mobileAjax&keyword=...&pageNo=...`，
  返回 **HTML** 并追加至 `#items`；这是静态分页声明，未实际翻搜索页。
  点击“下一页”还需取页面的 `pageNo,totalPage`，不能把脚本索引含义直接等同 JSON 页码。
- 校友旧 ASP/ASPX 路径的 404 和 `alumni.stu`/旧邮箱解析失败保留初查精确证据；
  本轮 `alumni.stu` 根亦解析失败。新闻可读不证明校友卡、校友认证或个人档案已接入。

### 本科招生与录取结果

本轮 `https://zs.stu.edu.cn/` 200，当前招生政策/计划/历年分数、院系专业栏目可见。
官网根仍直接链接 `/zxfw/lqjgcx1.htm`，此页 200，模板标题为“汕头大学2026年录取结果查询”。
另一个原候选 `/develop/index.htm` 本轮 **404**；旧
`/RecruitStudents/WebForm/Search.aspx` 的 404 保留初查，不拿新主页替它报可用。

录取组件静态合同进一步定位到：前缀 `/aop_component//webber/formquery/`，
`POST query/front/items/get`，JSON `owner,templateCode`，读取组件规则；原页面还声明
`session,Authorization,owner,appId,resolutionRatio` 请求头。默认模板为
`Form-1773642663029-4261`、组件 `viewId=1177394`。返回客户端按 `code='0000'` 取
`data.needLogin,msgCode,dataItemList` 等，决定登录、验证图和查询条件。
这只是**元数据接口静态声明，未发送该 POST**，未猜匿名头或个人查询字段。
公共 `openapp/api.js` 为泛用 JSON 包装，并非录取结果接口。

页面另指 `/lqcx.jsp`，实际 GET 200 但仅 63 字节，无表单/列表/脚本；不能当录取结果成功。
从未输入姓名、身份证、准考证或查询任何考生。该组件可能暴露校园初始信息，不能当普通公告采集。

## 4. 医学院公开事项目录：208 个唯一事项元数据

`https://ywtb.med.stu.edu.cn/` 与 `/index/index/services_system` 本轮均 200，
事项目录和具体办理系统分开。`/index/download/index` 实际 **404**；
不能因为菜单里有“下载”就视为当前下载列表已可读。

### 公开读取合同与空态

| 项目 | 实际合同 |
| --- | --- |
| URL / 方法 | `POST https://ywtb.med.stu.edu.cn/index/index/index.html` |
| 编码 / 请求头 | `application/x-www-form-urlencoded`；`X-Requested-With: XMLHttpRequest` |
| 字段 | `service_name,dep,subject,page,post_type`；关键词搜索 `post_type=1`，部门选择 `2`，分页 `4`，`page` 从 1 开始；注释中的主题分支 `3` 未执行 |
| 正常 JSON | 顶层 `service_name,total,value,show_page,subject_list,totalpage`；不是 `code/data` 包装 |
| 目录项主要字段 | `id,service_name,type,service_department,service_object_list,service_type_list,service_description,do_method,jump_url_to,url,status,attachfile,service_process` 等；负责人/电话只记录字段存在，不保存值 |
| 普通 POST 差异 | 相同字段不带 AJAX 头，实际 200 **完整 HTML**，不应按 JSON 解析失败当“没有服务” |
| 无匹配词 | 固定无匹配词、`post_type=1`，实际 200 JSON，`total=0,value=[]`；保留 `subject_list` 等，正常空态与 HTTP/解析错误分开 |

实际 `type` 是字符串，页面用宽松比较：`0` 作流程、`3` 作指南，二者点击本目录
`/index/index/services_detail/id/<id>`；其余类型按 `subject_list` 解释后跳 `jump_url_to`。
不要把类型枚举、`status`、`url`、空字段擅自解成是否已开通/获授/已经办结。
已实际 GET `services_detail/id/5` 200，取得事项说明；页面另外声明 `/index/index/jump.html`，
**未调用跳转/申请动作**。

### 逐页去重与缺项补证

16:12–16:13 UTC 按正式 21 页读完：服务端每页 10（末页 8）条，声明 `total=208`，
**208 行只有 207 个唯一 ID**，因为 `244` 同时出现在第 1 页末和第 2 页首。
不是异常就填空，也不靠猜 ID 补齐。
随后使用页面正式“网络与信息中心”筛选（`dep` 为该文字、`post_type=2`、第 1 页），
额外读到 `id=4`；合并得到 **208 个唯一事项，与该快照声明总数一致**。
已保存来源页/补入的部门筛选，仍保留跨页重复事实，不声称分页自身稳定或未来总数恒定。

[安全公开事项表](medical-service-matters.csv) 只含事项 ID、名称、部门、类型和安全跳转来源，
不含负责人/电话/人员资料；所有 208 项是目录元数据，**不是 208 个独立系统，也不是 208 项办理已跑通**。
大量目标是同一 workflow 的短路径、办事指南或静态下载；后台管理目标明确排除。
目录之外的个人待办/已办、流程开始、填写和提交均未请求。

## 5. 医学院独立认证与个人业务边界

| 业务 | 本轮实测入口与认证边界 | 尚缺证据 |
| --- | --- | --- |
| 独立学校认证 | `https://sso.med.stu.edu.cn/cas/login` 200，POST 本页，`username,password,execution,_eventId,geolocation,submitBtn` 等 | 未认证；与主校 `sso.stu` 独立 |
| 医学院教务 | `/new/welcome.page?ui=new` → 根 → 医学院 SSO，service `https://jwgl.med.stu.edu.cn/new/ssoLogin` | 本人身份、成绩/课表/选课列表 API 未核实 |
| 医学院 OA | `https://oa.med.stu.edu.cn/seeyon/caslogin/sso` 302 独立 SSO，service 明确保留 `:443` | 工作台、审批、会议室本人权限未知；会议室申请链接不执行 |
| 当前医学院科研 | `https://yxykygl.med.stu.edu.cn/userAction!do_casLogin.action` 302 医学院 SSO，同 action service | 项目/成果接口、与主校 `medsro` 关系未知 |
| 教学业绩 `yeji` | HTTP 根 200 指南；真实 `/manage/` → `/manage/login.php` → 医学院 HTTPS SSO，service `https://yeji.med.stu.edu.cn/manage/login.php` | 不是看到“manage”就猜管理员；实际获授角色/业绩统计未核实 |
| 个人信息中心 `my.med` | 根 302 `/index/user/index`，200“温馨提示”指登录；`/index/user/login` 200 **本域 POST** `account,password,__token__,_eventId,geolocation,submitBtn` | 标题写“统一身份认证”仍不足以认定与 `sso.med` 同 cookie/session；没有本人数据 |
| 网络自助 `auth.med` | HTTP `/selfLogin.do` 302 HTTPS 同页，200，POST `user_id,passwd,authcode,isRemind,_isRemind` | 验证码/密码表单，未请求挑战、未登录，未查流量/在线会话 |
| VPN 激活 `register.med` | `/vpn/` 200“激活须知”，真实 `/vpn/login.php` 200，POST `loginname,psw,checkcode` | 未请求验证码/验证账号/激活；与主校 WebVPN/TOTP 无同一证明 |
| 账号注册 `api.med` | `/index/user/register` 200，POST 本页含 `name,idcard,tel,mobile,email,unit,dept,address,introduce,title,post,education,graduate,password,captcha` 和状态字段 | **这是注册写流程表单静态合同**，没有注册/查证件/发短信；不能当已获授身份 |
| 医学院个人流程 | `https://ywtb-workflow.med.stu.edu.cn/s/9LimoXmZ` 200 SPA；公开应用 bundle 200 | 仅外壳/代码，不等于请假表单和会话成功；未跟短路径开始流程 |
| 旧门户表单 `int.med` | `index.php?action=form`，另两个精确 `cid=129|135` 均 302 `https://yxy.med.stu.edu.cn/` | 没取得对应表单；不能以门户 200 覆盖原表单 |
| 研讨室 | 目录发布 `http://lib.med.stu.edu.cn/LibSeminarRoom/Default.aspx`，本轮精确 HTTP **403** | 预约/空闲时段/身份未知，未构造 HTTPS 替代地址 |
| `uc.med` 切换目标 | 目录静态跳转 `http://uc.med.stu.edu.cn/index/?sno_switch=` | 参数有账号切换语义，**未请求**；不是网络/认证失败记录 |

workflow 公开 bundle 声明 `baseURL='/api/'`、JSON 默认编码、Bearer 独立 token，
配置组合后的 `GET /api/getInfo`、`GET /api/getRouters` 为会话/路由读取，
`POST /api/ticketValidate`（客户端用 `params`）为认证相关路径；这些均只作静态分析。
401 分支导向医学院 CAS。`/s/:key` 前端标为 `requireLogin:false` 只是路由元数据，
不能推断内部提交免登录。发行代码还含注册、上传、用户管理、验证码和系统管理接口，
**未请求，不能按打包存在就判本校开通**。

医学院财务目录仍给医学院 SSO 的 HTTP 内网 service `10.11.16.201/dlpt/caslogin.aspx`，
仅记录官方链接，不抽出 IP 单独探测。计财处 2026-01-14 和 05-27 两篇公开说明见初查，
分别是学院门户财务与主校新财务，不合并身份或令牌。总务处“资产”链接仍返回公开
`syzwc/152/list_152_1.html`，没有证明那就是资产业务 API。

## 6. 医学院可直接读取的通知、科研、招生、就业和校友

### 公告与科研聚合

| 来源 / 读接口 | 本轮实际响应 | 字段、分页与边界 |
| --- | --- | --- |
| `sumcapi.med/oa_notice.php?tab=oa|stu` | 两 tab 200 HTML；OA 第 2 页和正式 `dept=教务处` 筛选也 200 | URL `page` 从实际链接取得；两源独立。页面本轮 OA 尾页 3065、STU 尾页 4222，仅是快照页码，不作实时/全量保证 |
| `sumcapi.med/article.php?ws=oa&aid=<列表原有文章 ID>` | 抽一条实际 200，“关于购买2027年度汕头市城乡居民基本医保险的通知” | 正文和原 OA 附件 href 可见；没有下载附件/报名表，不外推所有通知、附件或员工办公均匿名 |
| `keyan.med/?page=2` | 带 `X-Requested-With: XMLHttpRequest` 实际 200 JSON，`code=200,data` 10 条、`has_next=true` | 普通 GET 是 HTML；`type` 筛选来自脚本声明，未覆盖所有类型/末页 |

科研 JSON 为 `code,msg,data,has_next`；项字段有 `id,title,date,source,author,content,
type_code,url,files_json,summary,create_time,subject_scope,deadline_requirements,
application_criteria,research_areas,selection_method,application_procedure,application_method,
type_code_text`。页面明确说明 AI 获取，结构化期限/条件须核对 `url` 原文，不直接当学校权威结果。
本轮只保存结构和数量，没有保存含姓名/联系方式的原 JSON 正文。

### 研究生招生、导师与专业目录

- `https://yjszs.med.stu.edu.cn/public/index.html` 200，招生动态、简章、专业、咨询公开链接可见。
- `GET /supervisor/supervisor.php` 的表单字段 `keyword`；第 2 页真实 URL `?page=2`
  200，公开导师链接与第 1 页不同，页码链接截至 27。固定无匹配词查询 200，
  `.supervisor-card` 数为 0 且没有导师详情结果链接，保留页面壳/导航，作为正常无结果结构。
  不复制教师名单、履历或联系方式。
- 实际 `supervisor.js` 声明筛选参数 `major_subjects[],major_fields[],supervisor_level[],supervisor_type[]`，
  点击筛选携当前关键词并重置 `page=1`；真实可选值须取按钮 `data-value`，不能枚举猜导师/专业 ID。
  同时存在当前页卡片 CSS 过滤，不应把 DOM 隐藏数和服务端总结果混成一个分页合同。
- `/public/major/major_list_1.html` 200，专业/学科真实链接；`major.js` 的部门选择和“查看更多”
  **仅操作当前 HTML DOM**，没有新 AJAX API。不是每个折叠按钮都需要一个后端请求。
- `http://yjs.med.stu.edu.cn/` 200 研究生教育通知，调课、培养/学位和系统链接可见；
  新发现 `http://jpp.med.stu.edu.cn/` 200 联合博士项目公开信息，未见个人报名 API。
  未请求录取人员名单、个人报名或考试结果。

### 医学院就业与校友

`http://syjob.med.stu.edu.cn/` 是医学院就业站，和主校 `gdc`、学校招工作人员 `job` 三者分开。
本轮 GET `/job.aspx`、真实分页 `?p=2&t=&c=10&f=10&q=&n=` 和从列表取得的
`/jobdetail.aspx?id=8717` 均 200；列表响应是 HTML，页码/筛选 URL 从原链接取得，不猜 `t,c,f`
枚举。详情真实“申请”链接为 `/jobapply.aspx?jobid=...`，**没有打开**。

职位检索表单 POST 原页，字段 `ctl00$ContentPlaceHolder_RightContent$JobList_ViewState1$ddlSearchField`
（原选项 `Title|Body`）、同前缀 `txtKeyword,btnSearch` 和新鲜 WebForms 状态；本轮未发该检索 POST。
首页的新闻检索是另一组 `txtKey/btnSearch`，不能混作职位过滤。
`/program.aspx` 200，公开签约/报到/档案去向等指南文件，分页链接 `t=tables,p,n`；
没有下载含个人范例、办理报到或签电子就业协议。
官网外链的 `gdc.ncss.org.cn/login`、`/rec/login` 学生/用人单位路线保留初查，不拿主校会话代替。

新从研究生站发现 `http://xyh.med.stu.edu.cn/` 200 医学院校友之家，只有公开 CMS 信息证据；
和主校 `xyh.stu` 独立，不代表校友账户或个人查档 API。

## 7. 老系统、静态指引与未闭合项

本轮实际重查的动物预约 `stulac.med/book/member/login.php`、研究生选课
`gc.med/member/login.php`、ELP `elp.med/member/login.php` 均 200 独立 POST 登录表，
常见字段 `username,password,checkcodestr,dosubmit`；`gc` 另有 `usertype` 的学生/管理员选项，
**没有切角色或尝试登录**。相同字段不能证明同会话；也不证明验证码一定在每次登录出现。
`usmle.med/CommonAdmin/Login.aspx` 200，WebForms `txtUsername,txtPass,CheckCode,btnLogin`，未考试。
`yjs-sys.med/index/user/login` 200，独立 POST `account,password,keeplogin,__token__`，
初查的 Geetest 配置仍只是静态分支，不说实际一定遭遇挑战。

| 对象 | 具体证据状态 |
| --- | --- |
| `gse.med/member/login.php` | 本轮连接超时，停止；没有教学评价表单或接口 |
| `xnpj.med/index.php?action=login` | 本轮名称解析失败；无行政评价登录证据 |
| `bgs.med` | 本轮根 200；2005 FrontPage 文档/搜索合同沿用初查，不称现代 OA |
| `medsao.stu/default.aspx` | 从研究生主页发布的固定学生事务 service，匿名精确路径本轮 404；没有 CAS 成功 |
| 旧医学院 `jiaowu/jw.asp`、`www.med/xw/yjs/userlogin.aspx`、`www.med/xw/zp/index.aspx` | 初查精确路径 404，未重复失败；新的公开指南路径不能据主机名替它报可用 |
| `el.med,jsj.med,norton.med,zsxx.med,newcourse.med` | 初查名称解析失败，本轮不循环重试同阻碍 |
| `syzx.med,update.med`、`test.med/ot` | 初查分别超时、远端断开；未知，不宣称停用 |
| `yjs.med/forum`、`yjs.med/yjs` | 初查精确旧路径 404；当前主页可读不能覆盖这些旧路径 |
| 医学院中心实验室 `zxsys.med/equip.php` | 初查公开仪器目录 200，预约/登录未知；不与已单独调查的主校 `zxsys` 合并 |
| 公开目录中的 CMS 办事说明、申请表下载 | 是可引用的官方说明/静态目标，不逐个当独立系统；附件未下载。`ywtb/admin3.php/...` 后台目标排除 |

由此可把后续工作分为：已证实公开读取合同（采购公告、医学院目录/聚合/招生目录等），
有具体认证合同但无身份或数据（财务、医学院各独立登录），以及精确访问受阻/列表失败。
**尚未完成所有受保护业务的内部接口图**。SSO 票据颁发、表单可见、HTTP 200 和目录事项存在，
分别都不等于对应账号有可用业务会话。

## 8. 本轮关键公开脚本的原始字节 SHA-256

| 来源 | 精确路径 | SHA-256 |
| --- | --- | --- |
| wpay | `/js/chunk-common.20772bb8.js` | `92ec1c603c4f65fa1362a15f94f98c1d5d3b598a0d8aee6e1386ece53df9ed58` |
| wpay | `/js/index.c69dd6b5.js` | `2fdfab3876443db2fbff7b7ed72b1233fc88825c1692a13e74f61ef87e4b27bb` |
| wpay | `/js/chunk-40ab330c.6eb7edfe.js` | `05253b5ceb6b5b9df8164b7c01051fdaab0e8f27e6a336ef99f3b4f194472e37` |
| project | `/Scripts/Pub/ccenter.js`（小写 `/pub/` 版本本轮字节相同） | `683bac0befc4ab90d9572f9c5ae44722750d5a152d4764c6dd567ab61199dd98` |
| project | `/Scripts/note/note.js` | `c17ddfda48bc50153ac6bab7d39f6a35ddc4be506a8636fc42072dd3774c2730` |
| project | `/Scripts/common/myform.js` | `9362a11f4df3d9f68b9569bfe7de80530a26d4b5b09c0b4ea0aa24cbc1ab82bf` |
| ztbzx | `/js/login.js` | `70ae8e0c1dfa94526379d209fe31319947598c82543dc6f0b2313f1c62bff3b9` |
| 医学院 workflow | `/js/app.6bcb4576.js` | `0c2dc8eb0501016d1f10eca301c98dd4712ffb56e47eedec5141d0b0ce73984c` |
| 医学院导师 | `/supervisor/assets/js/supervisor.js` | `3102eac41f67f5843f625ca753c1c461461be202a8048ee58f2e7e0f7a2064aa` |
| 医学院专业 | `/public/assets/js/major.js` | `c088a586bbc2757d0ca69b2880174d3a2e0245473ab509036c6d5df3b218b0e5` |
| 本科招生 | `/system/resource/js/openapp/api.js` | `0951a5cc5b65bff40400a02cf18de902a4b7697bf0ba85f0108186dfe0aa79c8` |
| 主校校友搜索 | `/alumni/front/account/search.js?_v=2.65` | `b4951c627ac4272d61c542e6ef31b27b7a7c3274ce9911ea2adaf58e2b62a179` |

公开脚本哈希用于定位本次协议版本，不是对学校服务器或认证策略长期不变的保证。
