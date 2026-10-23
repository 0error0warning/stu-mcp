# 公开查询、行政及研究生入口第二轮协议补查

本轮只做上游协议调查，**没有接入 MCP、改产品代码或变更学校资料**。`r` 与综测暂停，未请求。
承接 [就业](employment-followup.md)、[仪器](instruments-followup.md)、
[credit](credit-followup.md)和[行政初轮](administration-completion.md)，下列新证据与旧结果分开。

匿名实测为 **2026-10-23 16:59:00–17:35:09 UTC**（北京时间 10 月 24 日 00:59:00–01:35:09）：
**101 次请求，85 GET、16 只读查询 POST；91 次 200、10 次 302**。其中常规调查 78 次，
研究生院新发布的成绩单 IP 和研究生雨课堂入口另 11 次，招生组件同源匿名初始化/元数据 8 次，
公开课程附件 4 次。16 次 POST 是 6 次开课筛选、1 次仪器公告、2 次财务公开配置、
5 次成绩单登录方式/学校/身份元数据、2 次招生查询字段规则读取；
没有认证、验证码、人脸、人员初始化、选课、申请、草稿保存、打印、预约、支付或其他写操作。
同源查询按顺序，用各站独立匿名客户端；`trust_env=False`、正常 TLS 校验、连接超时 5 秒、
其余超时 10 秒、关闭自动重定向。未改代理、DNS、证书或网络，不证明系统 TUN 的具体路径。
本组临时客户端已关闭。

根调查进程另持有各来源独立的本人 SSO 内存会话；本文引用其资产、仪器与一网通办结果，
**不计入上述 101 次匿名请求**。没有向本组传递中央 cookie、票据、密码或个人记录正文。

安全证据在忽略目录 `output/campus-protocol-survey/round2/public/`：
`requests.jsonl`、`external-published-requests.jsonl`、`admissions-metadata-reads.jsonl`、
`course-file-contracts.jsonl` 记录每次日期、目标、方法、响应结构、
选项、计数及原始字节 SHA256；`derived.jsonl` 是已取得响应的本地解析，明确标记
`network_request_performed=false`，不作为新请求时间。仅公开 JS 保存原始字节；匿名初始化的
session/授权值仅用于同源内存请求，没有输出、哈希或保存。未保存匿名
HTML 原文、WebForms 隐藏状态值、学校登录凭据、cookie、票据、学生名单或教师整表。
根进程引用证据为同级 `round2/observations.jsonl`。

## 1. 就业职位：关键词正常，真实分页仍未前进

正式入口是 [搜索职位](https://gdc.stu.edu.cn/Search/SearchJob)。本轮先读取当前页面及其
`/Scripts/Search/SearchJob.js`，再按官网真实拼接参数查询；不是继续只用旧的 `pageindex`。

### 当前客户端实际构造

官网 `searchJob.search()` 以 `pageindex=1` 开始，取 `#txtKeyword`、
`#city[sel_default]`、`#jobCategory[sel_default]` 等值。两个未选筛选的实际值均为 `0`，
因此一次普通搜索包含 `city=0&jobCategory=0`。关键词调用旧 JavaScript `escape()`，
本轮验证词为 ASCII；中文 `%uXXXX` 的服务端兼容性未验证。

| 参数 | 静态来源/边界 |
| --- | --- |
| `pageindex` | 搜索固定初值 `1`；翻页使用响应中实际 `<a href>` |
| `keyword` | `#txtKeyword` 非空时附加 |
| `city`、`jobCategory` | 各自 `sel_default`，本轮默认 `0` |
| `minMoney`、`maxMoney` | 输入非空时附加；未执行工资筛选 |
| `jobKind`、`educationLevel` | 前端条件写成 `.lenght > 0`，静态拼写错误；不能假设点击这两个分类后参数已正常发送 |

### 实际结果

| UTC | GET 条件 | 结果 |
| --- | --- | --- |
| 17:01:44–17:01:45 | `pageindex=1&city=0&jobCategory=0`，随后 `pageindex=2` | 两次 200，但 `.Pager .Current` 均为 `1`，同一组 10 个职位标识，不能当两页数据 |
| 17:01:45 | `pageindex=1&keyword=Java&city=0&jobCategory=0` | 200、关键词回显 `Java`，10 个职位与默认列表不同，是关键词影响结果的正例 |
| 17:09:23 | **跟 Java 页实际发布的下一页链接**，同参数仅 `pageindex=2` | 200，关键词仍 `Java`，当前页仍 `1`，与 Java 第一页 10 个标识逐项相同 |
| 17:03:01 | `keyword=qzvx`，其余仍为完整官网默认参数 | 200、关键词回显一致，无职位链接、无分页容器；这是正常空结果样本 |
| 17:01:46 | `keyword=STU_NO_MATCH_20261023`，同默认筛选 | 302 到 `/Home/Error`；不是正常空结果，尚不能把原因确定为长度限制或服务器某项规则 |

职位标识仅在本地用于去重，不持久保存招聘联系人。当前 `/js/Main?v=1` 与页面引用的
`/bundles/global?...` 未检出职位分页/关键词拦截逻辑；这是已读脚本范围，不能排除其他服务器逻辑。
**可确认关键词读取与空态；翻页完整性仍缺证**，不可按页数直接累加、声称扫完所有职位。
公共职位 JSON 数组等合同仍见初轮，不把 HTML 搜索和另一组接口响应包混在一起。

## 2. 大型仪器：公告空态、收费规则与注册前提

### 匿名接口与价格

`GET https://zxsys.stu.edu.cn/genee/equipment/3` 本轮 200，仍有详细信息、预约、公告、
收费标签。当前内联 JS 实际声明：

```text
POST /genee/ajax/Index/Reserv/getNotices
Content-Type: application/x-www-form-urlencoded
id=<来自公开设备列表的设备标识>
```

17:01:46 用公开设备 `3` 执行一次，**200、响应体 0 字节**。这是当前设备公告的空 HTML
片段样本，不是 JSON，也不能解释为平台没有公告；未调用会显示预约人/排行人员的接口。

设备 `3` 的 `#summary-fee` 仍无文字；初轮设备 `30` 也为空，本轮没有把同一空样本当成
“所有仪器免费”。沿当前首页导航读到：

| 真实公开路径 | 实测/用途 |
| --- | --- |
| `/genee/category/rules` | 200、管理制度正文及子导航；不是列表 JSON |
| `/genee/category/rules/dxyqsbgxglbf` | 200、校级大型仪器共享管理办法，正文说明有偿使用、校内外服务对象收费有区别；未取得单台价目表 |
| `/genee/category/download` | 200，当前主体未列出可直接跟进的价目附件；不能据此认定从不发布附件 |
| `/genee/post/116` | 200、新设备投入使用公开通知；未取得可计算费率的结构数据 |
| `/genee/post/113` | 200、测试费信用额度办法，页面显示 2026-03-09；**额度不是余额或某设备单价** |

本轮只验证公开政策可读。按设备、用户类型、测样方式计算价格，以及本人独立操作资格、
课题组余额和预约权限仍不能给出。

### 本人纯 HTTP 认证到何处

当前公开首页的正式链是 `/gateway/?from=stu&redirect=.../!people/docking/login` →
`/gateway/login?...` → 学校 SSO。SSO 发布的 service 原样带空端口冒号：

```text
https://zxsys.stu.edu.cn:/gateway/login?from=stu&redirect=https%3A%2F%2Fzxsys.stu.edu.cn%2Fcf%2Fmain%2F%21people%2Fdocking%2Flogin
```

根进程 **17:04:38 UTC** 按该正式 service 完成纯 HTTP SSO/gateway/docking，最终
`GET /cf/main/!labs/signup` 200，页面含当前本人账号判据，但要求建立仪器用户档案。
表单声明字段包括身份/姓名/性别/课题组/学号或工号/专业/单位/实验室/有效期/联系方式及
`verify_token`、`token_backend`、`glogon_pass` 等；**只记录字段名，没有记录预填值或隐藏令牌**。
未提交此表，不能跳过注册前提声称本人资格、计费和预约读取已完成。

## 3. credit：学年控件校验、汇总统计及交流生边界

### 真实查询与回显问题

`POST http://credit.stu.edu.cn/Elective/DispClassList.aspx` 是匿名开课查询，继续使用
新鲜原表单、GB2312 URL 编码、当前隐藏状态与以下业务字段：

```text
__EVENTTARGET, __EVENTARGUMENT, __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
Xnxq$XN$Text, Xnxq$XN$List, Xnxq$hfXN, Xnxq$XQ, ddlJxdw
btnSearch.x, btnSearch.y
```

当前教学单位下拉 **56 项，含“请选择”和“所有教学单位”，即 54 个具体单位**；
学期为春季 `2`、夏季 `3`、秋季 `1`。没有把教学单位、招生学院与专业编号互换。

进一步取得原页实际引用的 ComboBox `WebResource.axd` 及内联 `buildItem()`：
服务端选项 value 是完整 `2020-2021学年` 形式，`buildItem()` 却用数字年份生成新 Option；
它还重建输入年份前后各三年的选项，未显式选中输入年。原 ComboBox 脚本又会在键入/选取时
操作 `selectedIndex` 和文本，因此不能只修改一个文本框或硬编码 `List`。

| UTC | 请求与实际响应 | 结论边界 |
| --- | --- | --- |
| 17:01、17:03 | 使用官网 `buildItem` 声明的数字 value 模拟 2026/2020 年查询 | 均 302 错误页；读错误页确认“回发或回调参数无效”，正文明确事件验证，不是空课表 |
| 17:11:01 | 新鲜原表单用服务器已有完整 `2020-2021学年` value、春季 `2`、计算机系 `551` | 200，`dgkkb` 38 行＝表头加 37 数据行、14 列；Text/hfXN 为 2020，但重建后的 List 显式选了首项 2017，仍存在回显冲突 |
| 17:12:44 | 新 GET 复用该匿名会话，再直接请求 2026 | 302；**该次新表单实际只发布 2017–2023，2026 不在可选值中**，不用于推断 2026 数据是否存在 |
| 17:14:31→17:14:48 | 先选当前已发布的 2023 完整 value，得到新表单，再选其中正式列出的 2026 完整 value；秋季、`551` | 两次均 200、仅表头；2026 响应 Text/hfXN 一致，List 重建为 2023–2029 且无显式 selected，HTML 默认首项为 2023，查询年份完整性仍保留未知 |

新 GET 的年份范围会受之前匿名查询影响，说明“重新 GET”不等于完全初始状态。
不修改或关闭事件验证，不发送原表单未接受的状态去绕过校验。当前可复现非空公开开课表及
带条件的空 HTML 表，**不能把它当本人课表，也不据有冲突的控件回显断言某学年一定无课**。
14 列仍为班号、课程、教师、课室、起止周、周日到周六、学生数、开课班状态。

### 专业分布与交流生

| 入口 | 本轮结果与合同 |
| --- | --- |
| `GET /Info/DisplayDeptStat.aspx` | 200；`DeptStat` 689 个直接 `tr`（含表头），4 列为所在院系、专业年级、专业、学生数。是汇总统计，**不是 688 个唯一专业或学生名单**；页面无筛选/分页控件证据，数据更新时间未确认 |
| `GET /ESMS/login.aspx` | 200；独立 WebForms POST 同路径，`txtID`、`txtPwd`、`btnLogin` 及 3 个状态字段；没有 SSO 跳转证明。只读登录表，未把主校账号发到 HTTP，也未验证交流生身份 |

课程目录、培养方案、课程关系和教室静态容量合同沿用初轮；本轮没有把公共开课与教务本人
成绩/课表混合，也没有重新查询个人记录。

## 4. 财务 wpay：当前配置关闭登录页统一认证按钮

`https://wpay.stu.edu.cn/logCas` 仍返回财务 SPA。当前 `appconfig.js`、公共 bundle、
webpack loader 及真实登录懒加载组件均已 GET；CAS token 交换链见初轮，未重复认证。

| 当前脚本声明的只读接口 | 本轮实际响应 |
| --- | --- |
| `POST /api/selectAllCs`，JSON `{}` | HTTP 200，业务 `code:401`；不能按 HTTP 200 当配置读取成功 |
| `GET /api/user/zhmmset` | HTTP 200、`code:200`、`data` 7 条登录设置；每条 `csid,csname,csshow,csvalue` |
| `POST /api/user/selectShowAllCs`，JSON `{}` | HTTP 200、`code:200`、`data` 147 条公开配置；每条 `csid,csshow,csvalue`。未复制整份配置或把参数名当秘密凭据 |

后两者均实际返回 **`tyrzLogin=0`、`sfsydly=1`**。登录组件逻辑也对应：
`tyrzLogin` 为字符串 `"0"` 时隐藏统一认证按钮；否则将其值当 `tyrzLoginUrl`，点击后
`window.location.href`；`sfsydly` 不为 `"1"` 才按其值换登录路由。
所以不是仅凭“没找到 SSO 字符串”推断缺口：**当前登录页这一条统一认证发起配置未启用**。

这不能证明其他正式上游入口永远不会向 `/logCas?cas=...` 交付临时授权。
初轮学校财务官方 `/api/logcas/checkTicket` 只跳回 `/logCas` 且没有授权参数，本轮没有新
上游目标可据以申请 school CAS service，因而未猜 service、未发主校密码、未交换临时 cas、
未取得财务 token，个人缴费/工资/报销业务仍缺认证证据。

## 5. 研究生：当前官网、公开 CMS、独立业务和新成绩单

### 精确主机不能混用

**`GET http://gs.stu.edu.cn/` 在 16:59:11 UTC 为 200，标题“汕头大学研究生院”，
包含 2026 年入口和通知。** 它是当前官网链接实际发布的无 `www` 主机，不能继续用旧
`https://www.gs.stu.edu.cn/` 的证书错误覆盖这一结果。也不能因此宣布旧主机的具体业务
路径和证书已恢复。

| 实际公开 CMS 合同 | 本轮结果 |
| --- | --- |
| `GET /list/90` 办事指南 | 200，发布 1 篇本地正文与 4 个旧 `www.gs` 附件链接，分页仅发布 `/list/90/page/1` |
| `GET /list/90/page/1` | 200；只验证正式页面 1，没有猜第 2 页或声称全站只有 5 份指南 |
| `GET /list/90/post/0eb0974f-ab88-45cf-b58b-fed747eee2d1` | 200、补办毕业/学位证明公开指南，另发布申请表 docx；未下载或填写申请表 |
| 官方搜索表单 `GET /search?kw=...` | `kw=qzvx` 实际 200，却仍显示一篇 2021 年通知，不是正常空态；未确认关键词过滤生效，也未把“看起来随机的词”直接当无匹配 |

指南搜索和栏目的后端合同是服务器 HTML；当前 `/web/js/index.js` 仅见导航/轮播/回顶部，
没有找到可替换 HTML 的公开 JSON 搜索合同。正文、附件与旧招生 WebForms 仍须分别核查，
不靠一个首页 200 声称全站附件可下载。

### 官网新发布的具体业务

| 入口 | 实际证据与停止条件 |
| --- | --- |
| `http://192.168.48.143/` 研究生管理 | 302 到学校 HTTPS SSO，service 为该 IP 的 **HTTP** `/Caslogin.aspx`；未向 HTTP 发票据或凭据 |
| `http://192.168.48.201/threeplus/index.aspx` | 200、三助系统，公开 student/teacher/worker/admin 导航；本轮仅跟 student 实际链接 |
| `http://192.168.48.201/bursary/` | 200、国家奖助学金；同样仅跟 student |
| 上两项各自 `stunic.aspx?role=student` | 17:11:02 均 302 到 **HTTP** `sso.stu.edu.cn/login`，其 service 也是原 IP HTTP `stunic.aspx`；未跟 HTTP SSO、未切换其他角色 |
| `https://gsstu.yuketang.cn/` 研究生慕课 | 17:16:16 GET 200、新版雨课堂前端 1.3.325；是官网独立发布的 tenant，未扫码、未复用本科 `changjiang` 会话，不代表课程已读取 |
| `https://stu.libsp.net/` | 官网标签为**科学导航地址**；仅保留发布关系，不能写成论文提交系统，也未在本组扩大到第三方平台查询 |
| `https://www.gs.stu.edu.cn/Open/replyopen.aspx` 及硕/博报名 `Signin.aspx` | 当前无 www 官网仍明确链接旧 www 路径；已有证书阻碍没有新线索，本轮未重复失败或把无 www 官网当这些业务的修复地址 |

### 电子成绩单的新协议及配置冲突

当前官网明确发布 `http://202.192.149.206/transcript_server/login`。
17:16:13 UTC 匿名 GET 200，标题“电子凭证”，是 SPA；继续只跟页面实际发布的
`setting.js`、`app.46d39190.js` 和 webpack 公开 runtime 中的 `login.490157c1.js`。
没有扫描 IP 的其他路径或端口。

本地 `ZMEDU_CONFIG` 写 `BASE_URL=http://202.192.149.206`，显示名“可信电子凭证服务平台”，
`isOpenCas=false`、`isShowLoginPage=true`，本地配置列账号密码类型 `3` 和在校生类型 `4`。
**但标签不是实际后端已启用方式的证明。** 登录组件真实声明的只读元数据已 POST 验证：

| 目标（相对 `BASE_URL`，不是 `/transcript_server/`） | 请求 | 实际 JSON |
| --- | --- | --- |
| `/manage/Sys/listSchoolConfig` | 空 POST | 200，`errcode:"0"`，`result.data` 1 条，字段 `schoolCode,schoolName,unifiedLoginAuthUrl,unifiedLoginOutAuthUrl` |
| `/manage/LoginMode/LoginModeParam` | JSON `{"loginModeType":"pc"}` | 200、`errcode:"0"`，`result.data` 1 条，含 `loginType,loginTypeTitle,loginEnable,loginTwoVerificationEnable,loginModeType,listConFig[]` |
| `/manage/Role/getLoginRoles` | 空 POST | 200、`result.data` 6 条公开登录身份元数据；未切换身份或查询该身份人员 |

这里的响应包是 **`errcode/errmsg/result.data`**，不是 `code/data`；实际共享 HTTP wrapper
处理后才由 Vue 组件读取 `response.data`，不能照别站约定直接取顶层 `data`。

17:19 的安全配置摘要显示：学校名为汕头大学，但 `unifiedLoginAuthUrl` 指向
**`http://kxpt.hdu.edu.cn/cas/managelogin.jsp`**，不是主校学校 SSO；本组没有跟随该他校目标。
后端实际只列 `loginType:13`、`loginEnable:1`、`loginTypeTitle:"xydl"`，人脸验证
`Face` 的 `verificationEnable:1`，与本地 3/4 标签存在差异。
因此目前只能说明“官网仍发布的平台与可读登录配置”，不能猜默认密码、拿主校密码试
独立账户，或声称主校 CAS、在校生成绩单、校友人脸验证已经跑通。
`/manage/api/user/login`、验证码/手机验证、`updateByLogin` 和任何打印/付费接口均未调用。

## 6. 主校行政 SSO：真实业务阻碍与旧结果

| 来源 | 本轮/沿用证据 | 当前可确认边界 |
| --- | --- | --- |
| 人事 `hr` | 17:00 前 GET 实际发布主路径的同源 HTTPS 候选 `/base/frame/main_stdx.jsp?FM_SYS_ID=stdx`，仍 302 到学校 HTTPS SSO，但 service 写成 HTTP 同路径 | HTTPS 外层不能自动改变 HTTP 业务回调；未续票或读取人员/工资 |
| 固资 `lrao` | 根进程 17:02:57 `/lrao/` 正常 CAS 后 200 外壳，iframe `/lrao/main` 先 302 SSO；17:13:00 再按 iframe **实际 service** 正常续票，最终 200、515 字节 | 17:14:30 对该已取页面本地解析出明确 alert“用户没有权限或找不到，请重新登录”；这是业务拒绝判据，不能只用外壳 200 宣称成功，也不确定是角色还是资料缺失 |
| 资源事务 `lrmo` | 根进程 17:02:57 固定 HTTPS `/Home.aspx` 新票据仍 302 回 SSO；17:14:30 本地解析 Location，service 内嵌本次原 ticket | 当前回调/重定向异常；不是以本地研究 allowlist 拒绝当校方拒绝，不递归提交嵌套票据，不推断必须用浏览器 |
| 科研 `sro`、`medsro` | 沿用初轮约 16:06、16:15 本人独立 SSO 回执，页面明确“个人信息未引入” | 缺系统资料，不因 200 当科研项目查询成功；医学院科研与主校仍独立，不试不同身份密码 |
| 车辆 `parking` 与 `motorcycle` | 沿用初轮约 16:05 两条独立 SSO：回调跳回无 ticket 路径后 401 JSON | 当前身份未取得业务读取证明；没有单凭学生账号或 401 判定具体角色原因 |
| `visitor` | 沿用初轮本人回调 500 | 新线索缺失，未反复重试、不申请通行 |
| 裸 IP 资产平台/固资 RPC | 独立账户、手机/微信/动态码及 `/service.do` 静态合同见初查 | 未发现可安全代用主校 SSO 的新正式 service，不提交普通学校凭据、验证码或资产变更 |
| 采购、项目、档案、信息、人事其他职工入口、医学院独立业务 | 初轮已按精确入口记录公开元数据、DNS/TLS/HTTP 回调或独立身份阻碍 | 本轮无新正式目标，不重跑相同失败，不读工资、档案人员和医学院私数据。医学院不因学校名相近自动纳入主校 SSO |

## 7. 一网通办 37 内部事项：可读元数据、本人空历史与完整表单的边界

不是把“50 个事项”等同于“50 套系统”。目录仍为
[service-matters.csv](service-matters.csv) 的 50 个公开事项，其中 **37 个内部办理事项**
与 13 个外部跳转分开；本文调查 37 项共用的流程引擎协议，而不是擅自启动 37 次申请。

### 静态链与实测链

从当前 `https://service.stu.edu.cn/fe/` 发布的 `entry.5b106b76.js` 追到
`useJumpMatter.939bb610.js`、`matterDetails.82e373c4.js`、
`matterApplication.9b7a1357.js` → `matterApplication.730f8366.js`、
`app-shell-core.cd237f07.js`。当前 `routeBasePath='/fe'`、**`apiBasePath=''`**，
以下目标均位于主机根，不能拼成 `/fe/site/...` 或臆造 `/api/site/...`。

根进程于 **17:14:30–17:14:58 UTC**，用当前本人 service 独立会话，对固定目录内全部
37 个内部事项各做下列 3 个 GET，**111 个响应全部 HTTP 200、`e:"OK"`**。
ID 取自公开目录，不是人员标识，没有探测其他事项 ID。

| 真实目标 | 真实参数 | 可读合同/本轮结果 |
| --- | --- | --- |
| `GET /site/app/app-check` | `app_id=<目录 id>` | `{e,m,d:{is_apply:int,msg:str}}`；首轮 36 项安全摘要保留 `is_apply:1`，首项 197 初次只保留 int 形状，根进程于 **17:25:48** 对 197 另做实际 GET，200、`e:OK,is_apply:1`。因此 37 项均有真实值证据，不是由形状补写；可申请判据不等于已经申请或职工身份已授予 |
| `GET /site/app/start-config` | `app_id`；官网也可附 `app_version_id`，本轮未附 | `d.app` 含 `public_version_id,name{en,zh},start_config,steps,flags,type,preconditions,start_node,fill_task_id` 等；配置可见不是完整填表 schema 或审批权限成功 |
| `GET /site/session/list` | `app_id,status=0` | `d:{list,total,running,page,perpage}`；37 项本人记录全部空；其中 36 项保留 `total:0,running:0,page:1,perpage:10`，首项只保留列表空及字段类型。没有他人历史，没有非空分页/详情证明 |

正文/流程导览还静态声明 `GET /api/app/detail?app_id=...`、
`GET /api/app/proc?app_id=...` 等，详情之前已抽查；本轮未把这些当完整申请表。
引擎配置允许 `steps[].forms`、自动草稿/即时草稿、流程前置条件、申请期限等变化，
不能把一项字段布局当所有事项的固定表单。

### 为什么未直接 GET “start-data”

前台实际表单初始化为 `GET /site/form/start-data`，参数声明有
`app_id,department_id,app_version_id,agent_for,sess_id,from_sess_id,draft_id,fill_task_id,test_uid`。
前端消费响应中的 `forms,step,app_version,data_check_count,first_save,load_id`，
再初始化表单 store；随后监听表单变化以保存草稿。
**GET 方法和名字不能证明完全没有初始化副作用**，尤其 `first_save/load_id` 尚未取得服务端合同。
本轮没有发送该请求，也没有打开会自动调用它的完整申请页；不能把“未请求”写成不支持纯 HTTP。

另确有编辑器预览：`/matterCenter/form/preview` → `Preview.vue.97f8ad1e.js` →
`/system/app-module-version/detail`，参数 `id=<model_id>`，返回表单模块版本供 renderer 使用。
`model_id` 来自该后台页面 query，**不等于目录 app_id**；当前没有 37 项可安全直接代用的
公开 model_id/普通学生权限证明，故未猜 ID 或越过后台身份取 schema。
独立 `/site/form-center/preview` 属于表格中心，也不能无证据替代这 37 个事项。

明确写边界仍是 `POST /site/app/save`、`POST /site/app/start`、
`POST /site/draft-v2/save`、`POST /site/draft-v2/form-draft-save` 等，均未执行。
这次可以覆盖“配置、当前可申请判据、本人历史是否为空”；**逐事项必填字段、数据联动、
完整表单和真实提交结果仍未验证**。

## 8. 最后四项真实补查：医学院设备、课程附件、招生规则及大纲

### 医学院设备目录与独立详情

17:27:38 后，`GET http://zxsys.med.stu.edu.cn/equip.php` 200，页面真实内联函数为
`detalis(id,type)`（原拼写），调用 `showstatus.php?act=details&id=...` 或
`act=czsm`；ID 来自设备卡片，不是人员编号。弹窗脚本 `static/js/box/box.js`
声明以 HTML AJAX 读取，未显式给其他方法时走 GET。

| 正式请求 | 实测结果 |
| --- | --- |
| `GET /equip.php` | 200，提取到 **51 个不同设备 ID**；页面只有 `page_num=1` 这一页码链接，无筛选表单证据，不猜第 2 页或另造分类参数 |
| `GET /equip.php?page_num=1` | 200，设备 ID 集合与上一份一致；是正式第一页核对，不算第二批设备 |
| `GET /equip2.php`（官网“不常用设备”） | 200，1 个不同设备 ID `95`；分类名称来自页面，不能把“常用/不常用”解释为当前可用/停用 |
| `GET /showstatus.php?act=details&id=57` | 200、3360 字节 HTML 表，14 个字段表头；不是预约列表，不采集联系人值 |
| `GET /showstatus.php?act=czsm&id=57` | 200、27 字节小片段，未取得实质操作说明或文件下载合同，不能按 200 当说明书已下载 |

详情 14 个字段为型号规格、英文名称、技术指标、功能及特点、服务范围、样品要求、主要附件、
厂家、所属部门、安放地点、联系人、联系电话、电子邮件、说明文档。只记录字段，不抄联系人。
当前设备 ID 数量是这两类目录快照，不是全历史数量或预约资格。
`yuyue(id)` 还会载入 `showstatus.php?id=...` 预约状态和日历，该分支可能显示预约人，
本轮没有调用；独立登录/注册、验证码与预约写动作没有执行，不把本部 genee 会话借给它。

### 当前医学院课程附件实际是 DOC/XLSX，不能写成 PDF

当前首页正式发布的 `GET /29/1862.html` 200，标题为“2026–2027 学年度秋季学期研究生课程表”，
页面发布时间 **2026-09-14 15:07:18**。它真实链接两个 RAR 及校历 JPG：

| 公开附件目标 | 实测合同 |
| --- | --- |
| `/upload_files/file/20260916/1789525700684719.rar`（学硕、博士） | 200、39953 字节、`application/x-rar-compressed`、RAR4 魔数；以 RAR 文件头交叉检查，恰有 DOC 课表和 XLSX 课程设置方案两个文件头，无加密标记 |
| `/upload_files/file/20260914/1789369631259473.rar`（临床专硕） | 200、39603 字节、同类 RAR4；文件头同样为 DOC 课表和 XLSX 课程设置方案，没有 PDF 文件头 |
| 后续正式课程通知 `/29/1868.html` 发布的 `/upload_files/file/20260928/1790565743801522.doc` | 200、303616 字节、`application/msword`、OLE Compound 魔数 `d0cf11e0a1b11ae1`；确实是旧 DOC，不是 HTML/PDF 或仅靠扩展名判断 |

两包的 DOC 名称分别说明“学硕、护理、博士”和“临床医学专业学位—线上直播课”；
并不是同一适用人群。另沿首页读取调课 `/17/1872.html`、选课 `/29/1864.html`、
线上直播 `/29/1866.html` 及 `/29/1868.html`，均 200；后两项有后续 DOC/XLSX 附件与校历 JPG。
没有请求明确标作选课学生名单的附件。

最初系统 `tar -tf -` 对一个 RAR 返回退出码 0 却没有条目，**没有据此认定空压缩包**；
随后重新读取同一公开附件，纯内存解析 RAR4 主头/文件头/结束头，核对 2 个条目与总字节边界。
这只是文件格式/条目合同，不是 DOC 内容排版、课时和周次完整解析，也没有解压执行文件。
原始 RAR、DOC、课程表和教师/学生整表均未持久保存。
原先“课程 PDF”只是待核查线索，本轮这些当前正式附件**实际没有 PDF**；不会把 DOC、XLSX
强行送入 PDF 解析或把某一人群的表当本人课表。校历及后续调课通知仍需按日期与适用范围合并，
本轮不生成导入课表。

### 本科录取组件：匿名元数据已跑通，个人查询未执行

当前 `https://zs.stu.edu.cn/zxfw/lqjgcx1.htm` 内联配置再次确认公开
`owner=2120259523`、`viewId=1177394`、`templateCode=Form-1773642663029-4261`，
前缀保持原样 `/aop_component//webber/formquery/`。当前引用 `token.js` 的真实初始化是：

```text
GET /system/resource/getSession.jsp?r=<客户端随机数>
GET /system/resource/getToken.jsp?mode=10&r=<客户端随机数>
POST /aop_component//webber/formquery/query/front/items/get
JSON: {owner:<页面值>, templateCode:<页面值>}
headers: session, Authorization, owner, appId=app-form-query, resolutionRatio
```

`tokenStr()` 明确调用 `gettoken(10)` 并去掉 CR/LF，不是凭空猜一个 Authorization。
本组在独立匿名同源客户端按正式 GET 初始化，值只在内存中随本次请求使用；未读取现有登录
cookie、SSO 票据或用户凭据，未保存返回值。`resolutionRatio` 是客户端声明的视口，
研究请求固定 `1440*900`，没有冒充读取到用户浏览器尺寸。

**17:31:48、17:35:09 UTC 两次只读 metadata POST 均 200、`code:"0000"`**。
响应为 `{code,msg,respTime,data,appendInfo,count}`，`data` 包含模板信息、
`needLogin:"N"`、`msgCode:"Y"`、`queryRole:"1"`、`dataItemList` 2 项。
第二次仅补录第一份安全摘要未保留的字段名称/规则，没有改变查询模板或提交个人条件。

| 字段声明 | 本轮真实元数据 |
| --- | --- |
| 姓名 | `columnCode=Item-1773642663041-878`，`ifCondition:Y,ifShow:Y,itemType:text`；规则原拼写 `ifRequred:true` |
| 身份证号码 | `columnCode=Item-1773643236601-2232`，同为 text/查询条件/可显示；`ifRequred:false`，`idcard:false` |

两项规则的长度限制开关均 false、minLength/maxLength 为 `-1`。
**规则不是服务端允许仅凭姓名查询的证明**，也不能由 `needLogin:N` 推断所有个人查询无门槛。
页面客户端会按 `msgCode` 决定图形验证分支；本轮未请求验证码、未解挑战、未输入姓名/身份证，
没有查询录取结果、初始校园账号或其他考生信息，也未调用提交个人查询的接口。

### credit 大纲：文件下载尚不成立

17:27:40 UTC 对课程详情正式发布的
`GET http://credit.stu.edu.cn/Course/Displaykcdg.aspx?kckey=2084` 只读实测为
**200、175 字节、`text/html; charset=gb2312`**。正文包含延时把顶层位置跳向
`/secure/logout.aspx` 的脚本，不是大纲文件。没有执行脚本、跟随 logout 或借用其他来源会话。
这补实了“下载目标当前匿名取到什么”，没有把 200/后缀当成功，也不能据此认定大纲永不存在。

## 9. 证据定位与后续接入前缺口

本轮解决了：就业关键词/正常空态、分页重复复核、开课控件事件校验和学年状态、
专业汇总/交流生入口、仪器公告空态及注册前提、wpay 当前统一登录配置、可用研究生官网
及新成绩单配置差异、一网通办 37 项真实元数据/本人空历史。
仍需合法业务条件或更明确上游合同的部分已在各节限定，不把全部入口标成“已接入”或“全部可用”。

以下为本轮新取公开脚本的原始字节 SHA256；完整 URL、时间和其余脚本哈希见请求摘要。

| 发布脚本 | SHA256 |
| --- | --- |
| `gdc /Scripts/Search/SearchJob.js` | `97141a93e8e66415dc6773793b7bec573fc7701a91b64328e421527e05523705` |
| `credit` 原页 ComboBox `WebResource.axd` | `39d022f08fb1cad87e8a452d845594b4eea68d2cfa4e760860849db6bf9d9792` |
| `wpay /js/chunk-7e6f75a3.5d492110.js` | `82e3331028ecd0d5f4b68dd9e69080e8c43d6b8561140144a84d06a5df7f12ff` |
| `service app-shell-core.cd237f07.js` | `04cf9a0e7b07443f65db708198cebdf63a7f93fdc797235dace3fdd983ade25f` |
| `service matterApplication.730f8366.js` | `c18e6463935bdca55046b6f2ff9890a75e67584e7c0d1095843b26d598a56edf` |
| `service Preview.vue.97f8ad1e.js` | `afcbadae94c6333968493ec273804034315bedef30569549485674b9e01c44c6` |
| 成绩单 `setting.js` | `925b956758430675b141d15f079ce515da66f27aed842c7ad71713c8ff495b79` |
| 成绩单 `app.46d39190.js` | `9236d63623400ce7eb92bacc192cdde084a03e88e7adc1bba6bc70e7d204243a` |
| 成绩单 `login.490157c1.js` | `c1840f3e184ba8bc3db3b91c13768310a9eb0d426c826fa0ea5809effed93c47` |
