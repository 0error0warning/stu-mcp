# 学工平台第二轮：本人读取合同、表格模型与目录分页

调查日期：2026-10-23 UTC（北京时间已跨 10-24）。这是对 [第一轮学工报告](xg-completion.md) 的深入补查，**没有接入 MCP、修改产品源码或办理业务**。`r` 和综测继续暂停；第二课堂 `dektapp` 与暂停的年度综测系统分开。

本轮使用中央 HTTPS SSO 为 17 个应用及门户分别建立仅内存保留的业务会话，不复制中央 cookie 或不同应用的 cookie jar。请求直连、正常验证 TLS、忽略环境代理，单次请求有短超时，不执行浏览器 JS。只保存安全结构回执及已发布 JS，不保存本人 HTML/JSON、姓名、学号、联系方式、金额、成绩、请假理由、家庭资料、密码或票据。

## 1. 当前证据层级与身份范围

17 个应用为：旧上下文 `/xsfw/sys/` 的 `sswjapp`、`sswsapp`、`knsapp`、`zxj`、`lstdapp`、`jxjapp`、`wjcf`、`dektapp`、`xsstapp`、`wjdcapp`、`xszsapp`、`jbxxapp`、`qgzxapp`、`xszmdyapp`，及当前上下文 `/xsfwdt/sys/` 的 `rychapp`、`xsqjapp`、`zxdkapp`。每个应用实际入口为对应 `/*default/index.do`；门户独立入口为 [学生工作平台](https://xg.stu.edu.cn/xsfw/sys/emaphome/portal/index.do)。共享主机不等于上下文、应用或业务记录可以互换。

认证和 bootstrap 于 17:02:23–17:02:25、17:11:43–17:11:44 UTC 完成；后续业务读取时间见下表与回执。页面状态码与菜单配置不单独作为本人数据证明：

- `knsapp` 本人首页响应的 `studentInfo.DZXX` 精确匹配当前学校邮箱；`WID/XH/XSBH` 匹配已独立验证的本人学号，`XM` 匹配本人姓名。回执仅保留匹配字段名。
- 官网前端存在两种真实赋值链：`userId = pageMeta.params.USERID` 和 `userId = pageMeta.params.userId`。本轮用 AST 读取本应用 `pageMeta` 的字面量对象，再与已验证本人身份精确比对。后续 `XSBH` 只使用这个同来源值，没有从别站复制学号填表。
- GPA 的两个管理表先读取正式搜索模型，确认 `XH` 和 `equal`，再发本人精确条件；两份实际响应的每一行 `XH` 均匹配本应用本人标识，`XSBH/XM` 也通过比较。没有读取未加本人条件的学生列表。
- 初版调查器只识别小写字面量赋值，随后只识别 `params.USERID`，曾阻止宿舍/绿通请求；这是本地解析不完整，**不是上游认证失败**。补齐真实大小写链后已成功读取，不保留为当前访问障碍。

## 2. 四种实际请求编码不能混用

以下均为本轮取得的官网前端合同，并有实际响应；不是靠端点名称推测。

| 调用族 | 精确请求与编码 | 结果合同 |
| --- | --- | --- |
| `COMMON.querySyncAuto/post*` | POST 应用内路径；普通表单 `requestParamStr=<JSON字符串>` | `returnCode/description/data`；本轮成功值 `#E000000000000`。成功响应可没有 `data`、返回对象或数组，不能一律当列表 |
| `XGJSUTIL.querySyncAuto/post*` | POST 应用内路径；普通表单 `data=<JSON字符串>` | `code/msg/data`；本轮成功 `code="0"`。`getCj.do` 官方初始调用省略参数，本轮按 jQuery 表单编码传 `data=`，没有替换为 JSON null |
| `mineQuery/dataModelQuery` | POST `.../commoncall/callQuery/{action}-{MINE\|DATAMODEL}-QUERY.do`；表单 `requestParams=<JSON字符串>`、`actionType`、`actionName`、`dataModelAction=QUERY` | `resultCode/msg/data`；本轮成功 `resultCode="00000"`。没有调用 `call`、`callBatch` 或任何非 QUERY 动作 |
| WIS EMAP | POST `.../modules/{page}.do`，表单 `*json=1` 取模型；POST `.../modules/{page}/{action}.do`，`*searchMeta=1` 取搜索配置；真实数据同一 action 路径，普通表单 `pageNumber/pageSize/querySetting` 及官网业务条件 | `code/datas`；实际 `datas[action].rows/totalSize/pageNumber/pageSize`。`querySetting` 是 JSON 条件字符串；未分页组件按官网删除分页字段，而不是强加默认页码 |

WIS 协议沿真实 `appcore.js` 的 `resourceConfig` 取得：`PUBLIC_NORMAL_JS` 的 `/emap{{version}}.js` 按当前页面 `BH_VERSION` 和实际 appcore 目录组合，缓存字段为 `rv`；没有猜文件版本。实际取得旧、新两套 `emap-1.2.js` 及 `bh_utils.js`。`getPageMeta` 的 `*json`、`joinActionIdToDoUrl`、`BH_UTILS.doSyncAjax` 的默认 POST、卡片/表格一基页码均来自这些脚本，未执行脚本。

## 3. 已读取的业务范围

表中数量只说明本轮本人或当前可见目录结果，不代表全校启用范围。空数组、没有 `data`、空对象、HTML 空态分别保留，不强制归成同一种“没有记录”。

来源对齐：前轮已跟随勤工 `appShow` 到 `qgzxapp`、住宿 `appShow` 到 `xszsapp`；一网通办的“住宿调退”和“假期留校”共用后一个应用入口。本轮验证的是对应应用的具体本人读取，不是两次住宿申请均可办理。旧事项的 `xsfwnew` 请假／荣誉路径及奖学金 `#/scolarship_manage` 不能继承当前 `xsfwdt` 或学生查询分支的成功。

| 业务、精确应用入口族 | 本轮实际读取 | 结果与范围 |
| --- | --- | --- |
| 宿舍违纪 `/xsfw/sys/sswjapp/` | `queryDiscipline.do`，`bh=1`；`getTimes.do`，`{}` | 17:06:20 成功。首条响应没有 `data`；计数对象 `ZS:string`。官网该分支显示暂无违纪数据，未猜更多 `bh` |
| 宿舍/个人卫生 `/xsfw/sys/sswsapp/` | 两个 EMAP 页面模型及 `sswsxs_sswsxsbg`、`grwsxs_grwsxsbg` 首屏 | 17:20:49 成功，各 `rows=[]/totalSize=0`。这里是宿舍卫生检查，不是心理健康记录；未请求照片/附件 |
| 困难认定 `/xsfw/sys/knsapp/` | `checkApply/getPoorSet/getAllPoorHistory.do` | 17:11:44 成功，设置对象、本人状态/身份对象、历史 `[]`；没有读取家庭成员、民政细节、消费、问卷答案或开始申请 |
| 助学金 `/xsfw/sys/zxj/` | 模型 `apply`，可申请 `xsdcxjzxx`、本人 `cxxsysqzxjjl` | 可申请列表及本人列表均正常空。条件 `TJ1/TJ2/TJ3=1,FHTJ=""` 与本人 `XSBH` 分清 |
| 奖学金 `/xsfw/sys/jxjapp/` | 同名可申请动作 `xsdcxjzxx`、本人动作 `cxxsysqjxjjl` | 可申请正常空；本人申请 1 行。本人可申请条件的 `XSBH/XSBH1/2/3` 均取本来源身份；没有提交、撤回或生成申请表 |
| GPA `/xsfw/sys/jxjapp/` | `getCurxn.do`；`gpaxxgl/dzgpaglbgxx`、`gpaxxglxg/dzgpaxgglbgxx` 模型、搜索元数据与本人 `XH equal` 查询 | 17:31:30 两表各 2 行、`totalSize=2`，逐行本人匹配为 true。字段类型和空值不同，不合并教务/学工版本；没有调用 `generalGpaxx/generalGpaxxXg` 同步写入 |
| 绿通 `/xsfw/sys/lstdapp/` | `queryStudentGreenChanelInfo.do`；MINE `hqxsyxszpc`，本人 `XSBH` | 17:11:44、17:27:41 均成功正常空。没有为无申请样本虚构流水/财务详情，也未请求家庭或财务资料 |
| 处分 `/xsfw/sys/wjcf/` | `getViolateExamine.do`，`{}` | 17:06:20 成功 `data=[]`；没有用于详情的本人 WID，不猜详情参数，不发解除/撤回 |
| 第二课堂 `/xsfw/sys/dektapp/` | 活动状态/学年、本人学分模块/雷达/评价、折算规则、活动表 `cxhdrdxx`、徽章表 `cxhdxzs` | 17:16:08–09 六项 API 成功；状态 6 项、学年 3 项，模块/雷达各 10 项、具体项目 `mk=[]`；活动/徽章表正常空。仅保留结构，未导出成绩值 |
| 社团 `/xsfw/sys/xsstapp/` | 可申请计数、本人角色/审核权限、`jrst/cxst_card` 全部 10 页 | 17:20:49 首页，17:23:30–31 补齐第 2–10 页；每页 8，末页 3，总 75 行、75 个唯一 `STDM`、0 重复，匹配 `totalSize=75`。这是社团目录，不是成员名单；未调用 `initStu` |
| 问卷 `/xsfw/sys/wjdcapp/` | `getAvailableQuestionnaires.do`，`{}` | 17:11:44 成功 1 条元数据，字段 `WJMC/WJDM/HASFILLED/TXSM:string`。没有读取问题/本人答案、启动作答或提交 |
| 宿舍申请 `/xsfw/sys/xszsapp/` | MINE `sqsh_cxxszsxx/cxxszsdz/sssqform/xsjbxxcx/xtsjcx`；DATAMODEL `T_SS_ZS_SQSZ` | 17:25:03 系统时间、17:27:40–41 其余成功；本人住宿/地址/申请/学生类别各 1 行，设置 5 行。设置按本人类别、`SFQY=1,*order=+PX` 查询；5 行有日期上下界，官网当前日期窗口内 **0** 行，不能把“启用”当当前开放 |
| 个人首页 `/xsfw/sys/jbxxapp/` | 配置、展示分区、本人审核/学业摘要、奖惩/资助摘要 | 17:28:34 成功；展示分区 6 项，奖惩/资助 `[]`。没有调用代码中与综测排名、个人消费相关的其他首页分支 |
| 勤工 `/xsfw/sys/qgzxapp/` | 设置、审核数、本人岗位/申请、可申请岗位、本人申请状态、本人岗位薪资明细 | 17:25:02–03 成功；本人岗位 1、申请 1、可见岗位 26。薪资请求 `GWDM` 只从本来源刚返回的本人岗位取，`SALARYARRAY` 12 项；不记录或展示工时/薪资值，未读取他人任职或保存空余时间 |
| 证明打印 `/xsfw/sys/xszmdyapp/` | `queryStudentApplyPrint.do`；EMAP `wdzmdy/cxksqdzmdykp` | 17:28:35–36 成功，本人记录 `[]`、可申请证明类型 1 项。只读种类，没有预览、申请、生成、打印或撤回 |
| 请假 `/xsfwdt/sys/xsqjapp/` | 本人已请/未销假统计、请假设置；`wdqj/wdqjbg` | 17:28:35 成功，表格 2 行、`totalSize=2`。未读取附件/提交或撤回请假/同意承诺书；设置读取不会标记承诺书已读 |
| 贷款 `/xsfwdt/sys/zxdkapp/` | 首页 `getLoanApply/getLoanSet.do`、可办理状态、四类 `getRecordLength.do`、`stu_loan` 模型及四类真实列表 | 17:28:35–36 成功。申请/意向/放款/还款四类都返回正常空；`getRecordLength` 的 `data` 是数组，**不是整数计数**。官方 `pageable:false` 未发送分页字段，响应 `pageSize=1000` 只是服务端合同，不能当已返回 1000 行 |
| 荣誉 `/xsfwdt/sys/rychapp/` | 新版 `getJxsqInfo.do` 及本人 `apply/xsdcxysqrychxx` | 17:16:09 当前符合条件目录 2 项；本人列表正常空。新版初始流程走 `getJxsqInfo`，旧 `emapCard` 代码仍在但不冒充同一实际流程 |

### 3.1 COMMON 与 XGJSUTIL 的精确业务路径

以下路径都以前表对应的应用根路径为前缀；所有方法均为 POST，JSON 对象再按第 2 节对应表单字段编码。除明确列出的参数外，输入为 `{}`。

| 应用/编码 | 应用内路径 | 业务参数 |
| --- | --- | --- |
| `sswjapp/COMMON` | `/modules/stu/queryDiscipline.do`；`/modules/stu/getTimes.do` | 前者 `bh=1` |
| `knsapp/COMMON` | `/modules/poorApply/checkApply.do`；`getPoorSet.do`；`getAllPoorHistory.do` | 无 |
| `lstdapp/COMMON` | `/studentApply/queryStudentGreenChanelInfo.do` | 无 |
| `wjcf/COMMON` | `/modules/violateExamine/getViolateExamine.do` | 无 |
| `wjdcapp/COMMON` | `/modules/questionnaireAnswer/getAvailableQuestionnaires.do` | 无 |
| `qgzxapp/COMMON` | `/modules/qgzx/studentApplyJob/` 下 `queryApplyJobSetting.do/queryStudentApplyAudit.do/queryStudentJobs.do/queryStudentApplyRecord.do/queryCanApplyJobs.do/checkStudentApplyProcess.do/queryStudentJobSalary.do` | 薪资为本人返回的 `GWDM`，其余无 |
| `jbxxapp/COMMON` | `/modules/infoStudent/` 下 `getAppConfig.do/queryStudentIndexSetting.do/getAuditInfo.do/getStuStudies.do/getStuAwardAndPenalty.do/getStuFunding.do` | 审核信息 `XSBH=<本来源本人>` |
| `xszmdyapp/COMMON` | `/modules/xszmdy/studentPrint/queryStudentApplyPrint.do` | 无 |
| `xsqjapp/COMMON` | `/modules/leaveApply/getAppliedDays.do/getNoRemoveLeave.do` | 两个独立路径，均无参数 |
| `zxdkapp/COMMON` | `/modules/loanStudent/getLoanApply.do/getLoanSet.do/getRecordLength.do` | 最后一路分别 `ACTION=xsdksqjl/xsdkyxjl/xsdkfkjl/xsdkhkqk` |
| `dektapp/XGJSUTIL` | `/modules/hdsbManage/getShzt.do/getXn.do`；`/modules/cjdcxManage/getCj.do/getLedaData.do/getSzfzpj.do/getXfgz.do` | 各自独立路径；`getCj` 官方省略参数 |
| `xsstapp/XGJSUTIL` | `/jrstController/querySfksqst.do`；`/glstController/queryUserRole.do/getPrivShztInfo.do` | 各自独立路径，无 |
| `rychapp/XGJSUTIL` | `/modules/studentApply/getJxsqInfo.do` | `TJLX="1",FHTJ="",querySetting="[]",PAGENUM=1,PAGESIZE=12` |
| `jxjapp/XGJSUTIL` | `/dzGpaxxglController/getCurxn.do` | 无 |
| `zxdkapp/XGJSUTIL` | `/modules/loanStudent/getStuApplyInfo.do` | 无 |
| `xsqjapp/XGJSUTIL` | `/modules/leaveApply/getLeaveSetInfo.do` | 无 |

表中斜线分列的文件名是同一目录下的多条独立请求，不是一条多级路径。

### 3.2 关键响应字段与歧义

- 困难认定：`data.studentInfo`、`SFSZ:boolean`、`poorSet:object`、`checkTimeResult/checkResult:string`；具体状态字面值与申请设置必须分别解释，不能将成功读取等同于当前可申请。
- GPA：教务表的 `GPA/ZGPA` 实际为 number；排名/比例混有 string/null；学工表的 `GPABFB/GPAPM` 在不同行为 null 或 string。`ZRS/KCS/KCMC` 可 null。保留来源、原始类型和未知值，不能统一补零。
- 第二课堂：`getCj` 是对象 `cj[10]/mk[]`，`getLedaData` 是 10 项数组；`getSzfzpj` 是 `ZXF:number/PJ:string`；规则是 `ZHJF/各类XF:number,ZHFS:string`。这些不是教务课程成绩，也不是综测系统读取成功。
- 社团：`STDM/STMC/STLXDM/STLXMC/SFYJR:string`，`SHZT/SFYSH/DSH/NOPASS` 实际可 null。只有 `STDM` 用于内存分页去重，不输出其真实值。
- 勤工：本人岗位的 `GWDM/SGBH/SQBH` 是不同身份；薪资明细 `GS/JSJE/SFJE/BCBZ/YGZSX:number`，`FFYF:string`。没有按字段名称自行推导发薪、到账或最新月份结论。
- 宿舍：`SQLB/XSLBDM/SFQY` 实际 string，`PX` 实际 int；是否开放还要比较同来源 `xtsjcx.DQRQ` 与 `KSRQ/JSRQ`。设置类别、本人申请状态与当前住宿分开保存语义。

## 4. 门户消息与公告

17:26:10 UTC，独立门户来源完成 CAS、进入 `/xsfw/sys/emaphome/portal/index.do`。17:28:20 读取页面实际两份 JS 和四个 `data-mod` 名：`widgets/common_service`、`widgets/main_tab`、`widgets/msg_list`、`widgets/notice_list`。

官网模板实际执行 `POST /xsfw/sys/emaphome/portal/render.do`，普通表单 `name=<页面 data-mod>`；本轮只取 `widgets/msg_list` 与 `widgets/notice_list`。17:31:30 两次均 200 HTML，消息 widget 有 7 个 `li`，公告 widget 没有列表项；它们不是完整消息总数或全校公告状态。没有点击消息正文、执行标记已读、主题保存或角色切换。

17:36–17:39，继续沿 widget 实际链接读取 `GET /xsfw/sys/emaphome/portal/more_msg.do`，以及页面发布的 DataTables 与 `more.js`。表格声明两个 mapper：`more_unread_msg`、`more_read_msg`。正式列表是 `POST /xsfw/sys/emaphome/portal/grid.do`，表单 `mapper,draw,start,length,columns[i][data/name/searchable/orderable/search][value/regex],order[i][column/dir],search[value/regex]`；列定义来自当前表格 `th[col]`。

17:46:37 UTC，两种 mapper 的 `start=0,length=10` 均返回 200 JSON。未读 `recordsTotal=recordsFiltered=12`、`data` 10 条；已读总数 0、`data=[]`。17:47:22 继续未读 `start=10`，返回 2 条，内存比较 `WID` 后累计 12 个、页间交集 0。消息字段为 `DO_URL,WID,CONTENT,ROW_ID,CREATE_DATE,APPNAME,TOPIC,CREATE_USERNAME`，只保留字段与计数，没有导出私人正文或发送者。模板中的 `POST /portal/markMsg.do` 会标记已读，本轮未调用。

通知应用 `tzggapp` 另有独立入口 `/xsfw/sys/tzggapp/*default/index.do`，本轮 CAS 后 200。它使用 `xgpspubapp`，不能直接套其他应用的 `swpubapp` 配置路径。17:41:03 UTC，按页面实际声明 `POST /xsfw/sys/xgpspubapp/indexmenu/getAppConfig.do?appId=<当前APPID>&appName=tzggapp`、空请求体，返回 200、0 字节且无 Content-Type，无法继续取得动态模块。17:47–17:48 仅在内存复核原脚本：`PATH` 是 `/xsfw`，`type:'post'`，当前 `roleIdparam` 为空，与已发请求一致；没有执行页面中的自动角色切换或设置角色接口。这是本次配置空响应的事实，原因未定，既不证明没有公告，也不证明必须浏览器。

## 5. 证据、纠错与剩余边界

安全回执：忽略目录 `output/campus-protocol-survey/round2/observations.jsonl`。`query/xg-query/mine-query/emap-query` 是具体业务请求；`bootstrap/emap-model/emap-search/framework/dependencies` 分别是菜单、模型或客户端声明，不能相互顶替验收。局部解析与本地校验另标 `network_request_performed=false`，不冒充新网络查询。

| 当前官网脚本 | SHA256 |
| --- | --- |
| `https://xg.stu.edu.cn/xsfw/sys/swpubapp/publicjs/common.js` | `429b6254b754c18e68a05cfda2a971657d949e2a0b150558062ddb481862f7e3` |
| `https://xg.stu.edu.cn/xsfwdt/sys/swpubapp/publicjs/common.js` | `5b8300b9b6e3d7bd7f7f3ed44a046b17c651692ce746f4320c607ca6832c05f5` |
| `https://xg.stu.edu.cn/xsfw/sys/swpubapp/publicjs/xgjsutil.js` | `845c5d43ae3c162e2894535de823774f57a9c126f76711567898e17fd263e2b1` |
| `https://xg.stu.edu.cn/xsfwdt/sys/swpubapp/publicjs/xgjsutil.js` | `211e894851d45e3481f25475ab987afcb031650ca75576c5e7f7646d4d733663` |
| `https://res.stu.edu.cn/fe_components/emap-1.2.js` | `5f0558e031c9a55fc174a699d80028a240cfb58731e9bfc0546730b94da5766e` |
| `https://res.stu.edu.cn/1.8.1_TR36/fe_components/emap-1.2.js` | `0f00d086f85b7faa51532aadb07bf52771564c5f1bda4bc51a4a27ac9a54633e` |
| `https://res.stu.edu.cn/fe_components/bh_utils.js` | `8c1ab50f226b769583547b2859d4ad945e6ad701c0ea0e14df913ba0dd4446ca` |
| `https://xg.stu.edu.cn/xsfw/sys/emaphome/public/js/portal.js` | `9e1313b69e9556a5352f474ba1fd6d6b8c2c2648ead17e635eb9d6646c80a65a` |
| `https://xg.stu.edu.cn/xsfw/sys/emaphome/templates/template2/index.js` | `a878279d54044cba6b5aa6c64bab7a09a5a38bfcaf378e6a41af94251eb57421` |

本轮已经越过“只拿到 index/配置/JS”的旧边界，但仍不是所有角色、所有业务状态和所有写流程的验收。原门户 19 卡中的迎新、心理咨询不在本轮 17 应用实读范围内；它们保留第一轮时点和范围，不能并入本轮成功数。未执行申请、撤回、删除、审核、打印生成、薪资/空余时间修改、同步 GPA、社团人员初始化、问卷答题/心理健康资料读取、照片附件抓取或通知已读；这些明确属于本轮不执行范围，不能写成认证被阻。

本人正常空样本没有可用详情 ID，不能猜 ID 补成详情成功；处分、困难生历史、贷款四类、绿通等保留这个样本边界。当前可见可申请目录不证明所有学院/年级适用，也不证明所有奖助正在开放。社团已补齐当前 75 项目录，不能扩大成社团成员、负责人或工作人员管理能力。
