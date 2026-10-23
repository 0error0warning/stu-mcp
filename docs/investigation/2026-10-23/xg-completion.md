# 学工门户 19 个应用：精确目标、配置与查询补查

请求时间：**2026-10-23 16:15–16:31 UTC（北京时间 10 月 24 日 00:15–00:31）**。
本轮只做 HTTP 协议调查，未接入 MCP。沿已有门户真实发布的 19 个 appShow 链接逐个
核对，不按主机名替代业务核查。综测及 `r` 未请求，仍按用户要求暂停。
认证与业务会话仅在内存，进程已关闭；没有角色切换/赋权、填写问卷、申请、打印生成、
读取心理健康资料或修改记录。

## 19 张卡片的实际目标

主机均为 `https://xg.stu.edu.cn`，下表 `*default` 是字面路径。旧入口跳转中的 HTTP
目标未携带 Cookie 跟随，而是取同主机的 HTTPS 同路径；实际前端也会将 ROOT_PATH
按当前页面协议、端口重写。因此原报告只读到初始 `http://...:80` 配置，不足以证明
浏览器必然把后续请求发往明文；必须核对运行时拼接规则。

| 门户名称 | 实际目标（省略 THEME/语言参数） | 当前结果 |
| --- | --- | --- |
| 基本信息 | `/xsfw/sys/jbxxapp/*default/index.do` | 200，取得模块配置和脚本；未批量读取个人资料 |
| 迎新服务 | `/xsfwnew/sys/yxapp/*default/index.do` | 302 回 SSO，不续票重试 |
| 学生问卷调查 | `/xsfw/sys/wjdcapp/*default/index.do` | 200，未答卷或提交；配置解析见下限制 |
| 学生证明打印 | `/xsfw/sys/xszmdyapp/*default/index.do` | 200，申请记录只读查询返回正常空列表 |
| 学生请假 | `/xsfwdt/sys/xsqjapp/*default/index.do` | 后续独立 HTTPS CAS 200，模块及本人未销假读取已补证 |
| 宿舍违纪 | `/xsfw/sys/sswjapp/*default/index.do` | 200，取得当前宿舍违纪读取声明 |
| 宿舍卫生 | `/xsfw/sys/sswsapp/*default/index.do` | 200，宿舍/个人卫生两个模块，不是心理健康模块 |
| 宿舍申办 | `/xsfw/sys/xszsapp/*default/index.do` | 200，取得申办模块；未调退/申请 |
| 心理咨询 | `/xsfw/sys/xlzxapp/*default/index.do` | 200、配置可读；不取预约/健康资料 |
| 困难生 | `/xsfw/sys/knsapp/*default/index.do` | 200，取得困难认定模块，未读家庭财务资料 |
| 勤工助学 | `/xsfw/sys/qgzxapp/*default/index.do` | 200，设置、审核概览、本人岗位均返回数据 |
| 助学金 | `/xsfw/sys/zxj/*default/index.do` | 200，取得申请/项目查询声明 |
| 绿色通道 | `/xsfw/sys/lstdapp/*default/index.do` | 200，取得查询与保存边界，未取家庭成员数据 |
| 助学贷款（新） | `/xsfwdt/sys/zxdkapp/*default/index.do` | 后续独立 HTTPS CAS 200，模块及本人申请空记录已补证，不等同旧奖助入口 |
| 奖学金 | `/xsfw/sys/jxjapp/*default/index.do` | 200，三个模块含申请和 GPA 信息；未重新计算或提交 |
| 违纪处分 | `/xsfw/sys/wjcf/*default/index.do` | 200，取得处分/解除申诉读取及写入声明 |
| 荣誉称号 | `/xsfwdt/sys/rychapp/*default/index.do` | 后续独立 HTTPS CAS 200，取得本人角色模块和申请/项目查询声明，未读项目列表或申请 |
| 第二课堂 | `/xsfw/sys/dektapp/*default/index.do` | 200，活动申报、成绩查询模块；未申报或读取完整成绩 |
| 学生社团 | `/xsfw/sys/xsstapp/*default/index.do` | 200，加入/管理社团模块；未初始化人员、申请或审批 |

首批 15 个目标 index 为 200、1 个返回 SSO、3 个新 context 未继续跟随。随后按这三个
实际公布的新目标分别以独立客户端取得正常 HTTPS CAS 票据，三页均 200；最终这组
19 卡片中 **18 个到达业务 index、1 个迎新目标回 SSO**，不等于18项业务读取已验收。
卡片与新一网通办相似名称不保证同一后台；原 appShow ID 的有限集合可在
[协议台账](business-protocol-ledger.csv)追溯，没有枚举未公开的应用 ID。

## 真正的缺失步骤是动态模块配置

index 在调用 `getAppConfig` 前，对 `ROOT_PATH` 进行协议/端口重写，并从实际页面取得
`APPID/APPNAME`。真实配置读取是：

```text
POST /xsfw/sys/swpubapp/indexmenu/getAppConfig.do?appId={当前页面值}&appName={当前页面值}
请求体为空（不是 JSON {}）
```

首批14个有效应用得到200 JSON，含 `MODULES`、`HEADER.dropMenu/userInfo`、`schoolID/APP_ID`；
`MODULES` 项为 `title/range/route/buttons`。这是当前模块导航及身份角色配置证据，
不是业务记录。没有调用 index 中另外声明的角色切换、角色赋值或调查问卷强制跳转。
问卷页曾因研究解析器先取到 `APPNAME="null"` 而发出一次不正确的配置读取，返回 HTML；
这条不算上游业务失败，不以它推断问卷权限，也没有反复试参数。

实际 `config.js` 是返回 `window.xgconfig` 的 RequireJS 包装，不能把小文件当模型不存在。
沿官方 `appcore.js` 的 MODULES/route 和默认 baseUrl 算法，首批取得18份
`/{app}/*default/modules/{route}/{route}.js`，均 200。未取心理咨询模块脚本。
该层有具体业务读取路径，不再是只有通用 `callJs.js` 框架。

| 应用/模块 | 已读脚本中的具体读取声明（均相对该应用根路径） | 本轮未执行的边界 |
| --- | --- | --- |
| jbxxapp / wdxx | `/modules/infoStudent/getAppConfig.do`、`getAuditInfo.do`、`getStuStudies.do`、`getStuLiving.do`、`getStuFunding.do` 等 | 个人详细资料、资助/奖惩/学习生活数据没有批量读取 |
| xszmdyapp / wdzmdy | `/modules/wdzmdy.do` action `cxksqdzmdykp`；`/modules/xszmdy/studentPrint/queryStudentApplyPrint.do` | `studentApplyPrint/reApplyPrint/recallApply/previewPrintReport` 不当普通列表调用 |
| sswjapp / student | `/modules/stu/queryDiscipline.do`，参数 `bh`；`/modules/stu/getTimes.do` | 未任选编号查他人或提交申诉 |
| sswsapp / dorm_health_student、person_health_student | 模块使用 `.do` 页面模型 | 仍需提取模型合同，不凭文件名猜动作 |
| xszsapp / xsDormApply | `/sys/xszsapp/modules/studentApplyDorm/queryCampusInfo.do` 从平台 context 拼接 | `saveStuApplyDrom`、`gxxssjh` 等不执行；名字含 query 也需看调用语义 |
| knsapp / difficulties | `/modules/poorApply/validateStuExistsQuestion.do` 及申请组件 | 未查询家庭敏感资料、未回答问卷 |
| qgzxapp / wdqgzx | `/modules/qgzx/studentApplyJob/queryApplyJobSetting.do`、`queryStudentApplyAudit.do`、`queryStudentJobs.do`、`queryStudentFreeTime.do`、`queryStudentJobSalary.do` | 本轮仅前三项；不保存空闲时段、申请岗位或退出岗位 |
| zxj / apply | `/modules/apply.do`，action `cxxsysqzxjjl/xsdcxjzxx` | 未调用提交检查或申请 |
| lstdapp / apply | `/studentApply/queryStudentGreenChanelInfo.do`、`queryFamilyMemberInfo.do`、`/greenCheck/getStudentFinancial.do` | `saveStudentApplyInfo/deleteFamilyMemberInfo` 写入未调用 |
| jxjapp / apply、gpaxxglxg、gpaxxgl | `/modules/apply.do`，action `cxxsysqjxjjl/xsdcxjzxx`；`/dzGpaxxglController/getCurxn.do` | `generalGpaxx/generalGpaxxXg` 不因属于成绩模块就视作只读；未生成/重算 |
| wjcf / violate_examine | `/modules/violateExamine/getViolateExamine.do`、`getCurrentDate.do` | `submitJcApply/backJcApply` 写入未调用 |
| dektapp / hdsb、cjdcx | `/modules/hdsbManage/getXn.do`、`getShzt.do`；`/modules/cjdcxManage/` 下 `getCj.do/getLedaData.do/getSzfzpj.do/getXfgz.do`；action `cxhdxzs` | 删除/申报不调用，成绩细项和分页仍待读证 |
| xsstapp / jrst、glst | `/modules/jrst.do` action `cxst_card`（页大小 8）；`/glstController/queryUserRole.do` 等 | `initStu/saveApplyJoinInfo/glstAuditJoin/xsAddCySave` 不调用，通用初始化也可能写入 |

## 四个具体只读 POST 的真实响应

官方 `COMMON.querySyncAuto` 最终使用 `COMMON.postSync`，方法为 POST，编码是：

```text
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
requestParamStr={JSON字符串}
```

这与通用 callJs 的 `requestParams/actionType/actionName` 不同，不能混用。
当前四条调用的官网参数均为 `{}`，身份由来源会话确定，没有传任意学生 ID。
`exception.js` 明确 `RETURNCODE.SUCCESS="#E000000000000"`；不能因为前缀含 `#E` 就判错。

| 应用 / 相对路径 | 本轮 200 响应（`returnCode` 均为官网 SUCCESS） |
| --- | --- |
| qgzxapp `/modules/qgzx/studentApplyJob/queryApplyJobSetting.do` | `data` 对象：`XQ_DISPLAY/GWSQLC/XQ/WID/XN/XN_DISPLAY/YCGWS` |
| qgzxapp `/modules/qgzx/studentApplyJob/queryStudentApplyAudit.do` | `data={AUDITSIZE:int}` |
| qgzxapp `/modules/qgzx/studentApplyJob/queryStudentJobs.do` | 本人岗位 `data` 数组 1 项；字段 `CXZH/GZJSRQ/GWDM_DISPLAY/SGBH/DWDM_DISPLAY/GZKSRQ/SFFFXZ/GWDM/LGLBDM_DISPLAY/DWDM/LGLBDM/SQBH`，不输出岗位、单位、日期或编号值 |
| xszmdyapp `/modules/xszmdy/studentPrint/queryStudentApplyPrint.do` | `data=[]`，与前端“暂无申请记录”分支一致；没有生成证明 |

这四条是本人来源会话下实际读取，不意味着其余模块都读通或用户可以申请全部项目。
该 xg 会话尚缺独立账号字段的正向绑定与过期合同；非空岗位数据的业务语义、工资、
学年筛选和完整分页仍缺。所有未读范围继续在台账保留，不用 18 份脚本充当 18 项验收。

## 证据定位

安全回执位于忽略目录 `entry-completion/observations.jsonl`：`source=xg`，
16:15–16:21 UTC 的 `cards/configuration_reads/requirejs_config_reads/module_script_reads/
fixed_readonly_queries` 字段分别对应入口、配置、资源及实际读取。本地解析操作单独注明
`network_request_performed=false`，解析时间不能更新为联网时间。

| 公开脚本 | 内容 SHA256 |
| --- | --- |
| `swpubapp/publicjs/common.js` | `429b6254b754c18e68a05cfda2a971657d949e2a0b150558062ddb481862f7e3` |
| `swpubapp/publicjs/exception.js` | `56e5643a7ef1fe99dd72f36a60f6a1c57eb2537312d8388bd541f39e4a0aa84f` |
| `qgzxapp/*default/modules/wdqgzx/wdqgzx.js` | `bd5acb5ebde80cdcb9c65327795b2baacd0b96b9a8af9e8d89b1ff9da81ee67f` |
| `xszmdyapp/*default/modules/wdzmdy/wdzmdy.js` | `dbdcdd34e7bf79c27700d5092a64078ff54896662b7668f778f2951f0d5d35bb` |

原19卡片名称与精确appShow地址、业务脚本和查询证明分别保留，避免继续把“门户可见”
和“真实模型读取”混成同一个完成状态。

## 后续：三个 `/xsfwdt` 目标可以读取，不能套用 `/xsfwnew` 的失败结论

16:28:53–16:31:31 UTC，按当次门户的真实目标，对请假、助学贷款、荣誉称号各以独立
内存客户端完成正常 HTTPS CAS。没有使用 `_UT_` 桥或复用旧 `/xsfw` jar，未请求综测。
三页均200，随后各自 `POST /xsfwdt/sys/swpubapp/indexmenu/getAppConfig.do` 取得200 JSON，
模块分别为 `wdqj/stu_loan/apply`。当前新版公开 `appcore.js` 也实际GET核对了同一模块
加载规则，三份模块脚本均200；因此总计17个有效配置、21份模块脚本，仍按具体范围计。

| 应用 | 当前脚本中的协议声明 | 尚未调用的边界 |
| --- | --- | --- |
| xsqjapp / wdqj | `/modules/leaveApply/getLeaveSetInfo.do/getAppliedDays.do/getCurrentTime.do/getNoRemoveLeave.do/queryWaitAuditData.do` 等同级路径 | `backleaveApply/delleaveApply`、续假及审批不调用；`getReadTime` 也没有按名字当只读 |
| zxdkapp / stu_loan | `/modules/loanStudent/getRecordLength.do`，`ACTION=xsdksqjl`；页面模型 `/modules/stu_loan.do` action `xsdksqjl/xsdkfkjl/xsdkhkqk/xsdkyxjl` | 未创建贷款申请、授信/还款，也未取家庭/银行材料 |
| rychapp / apply | `/modules/apply.do` action `cxksqjtrych/xsdcxgrrychjxxx/xsdcxysqrychxx`，以及带实际项目参数的 `getTipInfo.do/getJxsqInfo.do` | 尚无项目、本人申请及分页返回证明；不调用 `checkSubmitApply` 或申请 |

上表连续 `.do` 名称表示该目录下独立路径，不是将多个文件名拼成一个 URL。
新版 `common.js` 已实际核对仍使用 `requestParamStr=<JSON>` 的表单 POST；只读实测为：

| POST 路径 | JSON 作为 `requestParamStr` | 结果 |
| --- | --- | --- |
| `/xsfwdt/sys/xsqjapp/modules/leaveApply/getNoRemoveLeave.do` | `{}` | 200、`returnCode=#E000000000000`，`data` 为本人未销假对象；记录字段类型，不输出姓名、学号、手机号、日期或申请编号 |
| `/xsfwdt/sys/zxdkapp/modules/loanStudent/getRecordLength.do` | `{"ACTION":"xsdksqjl"}` | 200、相同返回码，`data=[]`；这里的 `getRecordLength` 实际返回数组，不能仅按接口名强解为数字 |

请假对象实际同时存在 `SHZT_DISPLAY`、拼写不同的 `SHZT_DISPALY` 及
`SHZT_DISPALY_DISPLAY`，`QJTS/SJQJTS` 为浮点数；字段歧义需按展示与业务语义再核对，
不能随意覆盖别名。未执行销假或读取他人记录。成功属于这次 `/xsfwdt` 的精确目标，
既不撤销旧 `/xsfwnew` 受阻样本，也不推断暂停调查的综测已经恢复。

新版公开脚本 SHA256 和三份模块路径在安全回执 `source=xg_leave/xg_loan/xg_honor`、
16:30:25 UTC 的 `config_status/module_assets` 字段中逐项记录；两条真实读取可定位
16:31:31 UTC、`source=xg_leave/xg_loan` 的 `form_field/encoded_json/json_shape`。
第二个临时进程也已结束并确认不保留会话。
