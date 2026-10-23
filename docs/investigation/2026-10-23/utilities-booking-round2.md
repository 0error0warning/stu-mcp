# 宿舍、水电、预约与 ELC 的第二轮只读合同复核

本报告记录本轮实际读取与缓存内存分析，不接入 MCP；没有支付、代缴设置、留校/退宿、
预约、取消、签到、申请或资料变更。root 保管中央 HTTPS CAS 与各业务独立内存 jar，
没有复制中央 cookie；本人页面与字段值未落盘。`power` 的既有来源级 HTTP 只读兼容与
`dorm/booking` 的 HTTPS 路线分开，不扩展成任意来源的传输许可。

## 1. dorm：本人关联增加独立来源绑定，账号类型仍不能硬合并

本轮已改用学校实际发布的固定 `https://dorm.stu.edu.cn/default.aspx` service 重新认证，
随后沿页面真实链接读取原 FID 的本人宿舍导航。**17:05:51.468142 UTC** 的实际响应为
200，仍为 `Index.aspx?FID=A851CEBD694D246E` 的 WebForms 页面，form action 指向
`MyDormitory.aspx`。不是仅有根页 302 或借其他业务 jar 后的结果。

**17:11:43 / 17:12:04 UTC** 由 root 仅在内存完成独立身份关联：NetMS 的 LDAP 字段
与本次授权学校账号精确一致，再取同一已认证本人信息中的姓名，与宿舍表“姓名”列比较，
得到唯一匹配。没有把姓名、房号、学号、床位或室友内容写入摘要。

**17:12:05 UTC** 的本地结构分析对应的仍是 **17:05:51** 那份网络响应：

| 结构或比较 | 结果 |
| --- | --- |
| `ctl00_CPHContent_GridView1` 表头 | 序号、房号、床位号、学号、姓名、学院、专业 |
| 符合 7 列表头的数据行 | 3 行；不导出整表 |
| 与已证明 LDAP 账号对应的私密姓名匹配行 | 1 |
| 表中学号直接等于学校登录别名的行 | 0 |
| 真实 GridView `Page$...` 链接或常见分页控件 | 本页样本未见 |

这补强了当前本人关联，而不是仅凭同域名或 HTTP 200 判定身份。学校登录别名、NetMS
其他编号、宿舍学号不保证相同；未采用字符串变形、拼音猜测或派生规则强行对齐。
同名匹配也不能推广成跨系统唯一身份映射或授权查询全部室友。分页控件未见只描述这个
小样本，不能保证所有账号/宿舍/业务列表没有分页。

## 2. power：12 槽历史、13 槽读数与样本费用关系

最新用于本节比较的真实响应：

| 实际读取时间 UTC | 页面 | 结果 |
| --- | --- | --- |
| 17:05:50.051727 | `/Page/ExtChargeSearch.aspx` | 200；历史内联数组 25 行 |
| 17:10:59.182119 | `/Page/ExtHeadPage.aspx` | 200；`dummyData=[]`，`flowdummyData` 12 行 |

**17:12:05 / 17:13:05** 为这些响应的内存分析时间，不更新账单/读数采集时间。
历史仍是每行 **12 个位置**，索引 `2/3/4` 是 JS 省略槽 `missing_hole`，不是零、`null`
或少了三列；读数 flow 是每行 **13 个位置**。提取只接受字面量数组，不 eval 或执行页面 JS。
合成夹具单独确认 12 槽及三个 hole 不会使后续字段左移；没有把合成结果当真人账单。

### 样本一致性，可用来校验解析，不能取代财务规则

原公开脚本将 flow 按 `CountDate` 分组；`ActualPerson` 位于索引 12。以下只输出布尔计数，
没有输出人数、日期、地址或任何金额值：

| 当前样本内部关系 | 结果 |
| --- | --- |
| 12 条数值行：`PowerDataUsed ≈ (Current-Previous)×Quotiety + PowerDataVerify` | 12/12 吻合；容差 0.005 |
| `PowerReceivable ≈ max(PowerDataUsed-PowerDerate,0)×PowerPrice` | 12/12 吻合；容差 0.011 |
| 按实际计量区间形成的组 | 4 组 |
| 同组地址一致、`ActualPerson` 为正且恒定 | 各 4/4 |
| 历史与 flow 按实际地址及计量区间精确关联 | 4 对 |
| 历史 `PayAmount ≈ 同组 PowerReceivable 合计 / 该组人数` | 4/4 吻合 |
| 历史 `PayAmount ≈ 同组整屋费用合计` | 0/4 吻合 |

因此，这份样本支持将历史 `PayAmount` 理解为该人对应的本期应付，而不能直接当整屋费用。
它不是全校所有账期、退款、特殊减免、金额舍入或校区收费办法的证明。两页采集时间不同，
关联只按本次实际共同键比较，不向服务器猜房号或枚举记录。

原脚本 `getPowerAmountPay` 使用组内最后一条 `ActualPerson` 求均摊；本样本人数恒定且为
正只是降低了这一样本的歧义，不替前端补上其没有的零值保护、不同人数策略或金额舍入。
原“清洁水”分支的用量汇总写入 `WaterAmount` 的静态风险仍保留，不用页面汇总替代源字段。

### 公开单位和分页合同进一步收窄

本轮 **17:16:02.834809 / 17:16:02.876508 UTC** 以独立匿名客户端实际 GET 两份公开 JS，
均 200，字节哈希与前轮完全一致：

| 公开脚本 | SHA-256 |
| --- | --- |
| `http://power.stu.edu.cn/ExtJS/headpagegrouping.js` | `17b18067bd319b4a3e26113af6cb9315fa4aff6734fc82451cdc6b0b00a10839` |
| `http://power.stu.edu.cn/ExtJS/chargegrouping.js` | `b064936647b73be966a2c01da977d1a820ea56354601413c3b4ee9e2f65a7127` |

读数列头明确写“单价(元)”和“费用(元)”，但没有标出 `元/度`、`元/吨`、kWh、立方米等
用量量纲。历史页“本期应付/上期结余/本期实收/本期结余”列头本身没有单位标注。故可以
报告脚本明确的人民币费用标签及上述样本对应，不能凭“电表/水表”名称自行填入全部单位。

两份脚本都使用内联 `dummyData/flowdummyData` 的 `Ext.data.GroupingStore`，未见
`PagingToolbar/PagingMemoryProxy/HttpProxy/pageSize/bbar/totalProperty/startParam/limitParam`。
当前本人页也未见普通 WebForms 分页控件。**本轮已知前端没有远端分页合同**，不等于
服务器承诺输出了该用户所有历史账期，更不等于可以猜补 `page/start/limit` 参数。

## 3. power 六个原表单筛选已实际补齐

忽略脚本 `round2/root_aux.py` 已为 root 准备严格的原表单查询：`power` 仅允许页面公开的
`dp_billStatus=-1/0/1/2/3/4`；每次先取新鲜 WebForms 状态，验证原 action 和 `ImgSearch`
控件，再只 POST 状态、当前枚举值与图像按钮坐标。不跟重定向，不支付/退款/改设置。
root 已实际执行全部六项；每次原表单都只需五字段：`__VIEWSTATE`、
`__VIEWSTATEGENERATOR`、`dp_billStatus`、`ImgSearch.x`、`ImgSearch.y`。

| 实际 POST 时间 UTC | `dp_billStatus` / 当前标签 | HTTP | 实际历史数组 |
| --- | --- | --- | --- |
| 17:16:10.738874 | `-1` 所有 | 200 | 25 行 |
| 17:16:13.817615 | `0` 未缴费 | 200 | 4 行 |
| 17:16:15.869125 | `1` 已缴费 | 200 | 21 行 |
| 17:16:18.940518 | `2` 已退款 | 200 | `[]` |
| 17:16:21.009566 | `3` 查无缴费人 | 200 | `[]` |
| 17:16:23.329238 | `4` 未退款 | 200 | `[]` |

六次响应的当前 selected 均与提交枚举相等，数组提取均无失败；非空行均为 12 槽，
`2/3/4` 缺失，状态列均属于官网当前标签，未缴/已缴的每行状态与该次筛选标签一致。
三次 `[]` 是正常业务响应中的显式空数组，不是连接异常、解析失败或状态未知；“已退款”
查询没有执行退款。六个样本均未见普通分页控件。

这是当前用户当次条件下的读取结果，不能用 4+21=25 就证明账户全部历史无限完整，
或把当前未退款空记录解释成未来无退款业务。最新本人历史查询时间为 **17:16:23 UTC**，
未缴费样本的实际读取时间为 **17:16:13 UTC**，不再沿用前轮的 14:09 查询时间。

## 4. booking 日期合同继续按当前表单核实

`booking` 的当前辅助分析只接受原 `Venue_Application_Form.aspx` 或 `BookingChart.aspx`
缓存，输出真实表单 action、日期/时段/周按钮字段、公开选项和图例；默认仅本地解析。
日期查询必须显式选择下面已验证的查询分支。`btn_next`、`btnSave` 及任何实际申请/保存
按钮均不属于日期查询；不能把空表推成可预约空位。

### 当前页面已经明确限制该账号预约，不能再写成“只差未登录”

root **17:17:41.016568 UTC** 沿本轮 `AllLibraryRoom.aspx` 的真实资源链接 GET 日期页，
200；不是猜 `hdid`。同路径 form 为 POST，当前字段是：

- `__VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION`。
- `venue_book_lib1$input_time` 与 `venue_book_lib1$btn_choose`（按钮“确定”）。
- `venue_book_lib1$ddl_start/ddl_end`，本轮都只有值 `0`、“请选择”这一项。
- `venue_book_lib1$btn_last_week/btn_current_week/btn_next_week`。
- `btn_next`：实际被禁用，标签明确提示当前账号不是该场地的预约对象。

体育园 `/SportsPark/BookingChart.aspx` 也有独立的 `ctl00$CPHContent$btn_*_week` 和
`btnSave`，本轮保存按钮同样显示对象限制。不能因为日历 GET 可读，就说当前用户拥有
这些资源的申请权限；也不能把这两个已测资源的对象限制推广到全部场地。
默认页面只见“可预约”等图例、少量表结构，没有可据以确认真实空闲的时段行。

日期页实际加载的 `/script/application.js` 于 **17:23:04.239865 UTC** 匿名 HTTPS GET
200，SHA-256 为 `8650a11567fcf25126bff521c3fcccb2ec1ecbe736fb3e2d25411b2cfad97edc`。
只有申请表的账户/单位/联系字段等客户端校验，没有本页日期控件引用、Ajax/fetch 或读接口
路径。通用表单校验不是已验证的学校开放规则；没有沿猜测接口、预约下一步或保存分支执行。

### 本轮实际日期查询：表单与日期回读成功，周范围仍不冒称推进

每次 POST 前 GET 同一个真实资源 URL，使用该次 `__VIEWSTATE/__VIEWSTATEGENERATOR/
__EVENTVALIDATION`；只带原来的日期字段、两个当前时段选项 `0`，以及本次查询按钮。
没有带下一步或保存按钮，也没有勾选真实时段。以下为实际请求，不是合成夹具：

| 实际 POST 时间 UTC | 本次唯一查询按钮 | 请求与结果 |
| --- | --- | --- |
| 17:21:30.794569 | `venue_book_lib1$btn_choose` | 新鲜原表单日期为 `2026-10-31`，改为其后 7 天 `2026-11-07`；200，返回日期值精确相同；下一步仍禁用并显示对象限制 |
| 17:21:31.232382 | `venue_book_lib1$btn_next_week` | 保留该次新鲜 GET 的日期 `2026-10-31`；200，返回日期仍为 `2026-10-31`，对象限制未变 |

第一项证明正常选日期查询的 POST 与日期字段回读合同；不能只靠回读断言真实空闲时段
已经载入。第二项证明原周按钮可以按正常表单发送并返回页面，但没有证据证明周范围已
推进，不能写成“下周日历查询已成功”。两次都只有图例和原表结构，没有得到实际可约
名额或符合资格的时段合同。体育园只读到了默认 GET/原周按钮，未把 Venue 的 POST
泛化为体育园所有查询已经实测。

`booking-resource-rules` 最初只在图片链接的最近空行取文字，得到四个目标但标签/容量为空。
这是本地容器选择范围过窄，不是官网没有容量或设备说明；前轮公开资源描述仍有效。
后续只在缓存做祖先容器的容量/设备/对象词提取，并保留容器中资源链接数，避免把共享
容器的介绍错误分配给某一个房间。没有因为解析空标签去猜更多资源 ID。

**17:26:10 UTC** 只在内存复核上述周按钮响应，没有新请求：可见日历日期标签集合仍为空，
日期控件为 `2026-10-31`，故没有补上“周范围已推进”的证据，保留这一限制。
同次修正祖先容器分析，针对 **17:16:24.012260 UTC** 已取得的 `AllLibraryRoom.aspx`
响应，找到每个只含一个资源链接的独立介绍 `div`，可对应以下公开资料：

| 公开资源 | 容量文字 | 本次安全提取到的设备词 |
| --- | ---: | --- |
| 报告厅 | 200 人 | 投影 |
| 30A 研讨室 | 48 人 | 未额外提取到所列设备关键词 |
| 30B 研讨室 | 36 人 | 同上 |
| 30C 研讨室 | 36 人 | 同上 |

介绍里没命中设备词不能解释为没有设备；这些静态容量也不等于当前空位/预约资格。
共享父容器有四个链接的汇总没有逐一套给房间，负责人姓名与电话未导出。

## 5. ehall：本人身份、资源规则与实际分页空态

root 于 **17:31:06.087720 UTC** 依官方现行 OIDC 配置、独立业务 jar 和中央 CAS 完成
纯 HTTP 流程，`access_token/id_token` 只保留内存，没有启动浏览器或借用其他业务 jar。
**17:34:15.843147 UTC**，`GET https://ehall.stu.edu.cn/sso/oauth2/userinfo` 使用原 Bearer
访问令牌返回 200。响应字段包含 `sub/external/openId/loginName/name/userType/userName/
account/email/userCode/deptCode/tenant`；仅在内存把 `email` 与授权学校账号的预期学校邮箱
作精确匹配，命中 `email`。没有输出邮箱、姓名、sub、openId 或令牌。

完成本人正向判据后，按已取得的官方 GraphQL query 模板进行资源读取：

- `POST https://ehall.stu.edu.cn/bus/graphql/me`，原 Bearer 头及内存 `id_token_hint` 查询参数。
- JSON 由 `operationName/query/variables` 构成；
  `operationName=findResourcesAllByAccount`、变量 `{first:10,offset:当前页偏移}`。
- 响应为 `data.findResourcesAllByAccount[]`；本轮各页均 HTTP 200、GraphQL `errors` 为零。
  没有把 GraphQL HTTP 200 自动等同业务成功；空数组与错误信封分开。

| 实际请求时间 UTC | first | offset | 资源行数 |
| --- | ---: | ---: | ---: |
| 17:34:15.930766 | 10 | 0 | 4 |
| 17:34:17.005453 | 10 | 10 | 2 |
| 17:46:19.072525 | 10 | 20 | 2 |
| 17:46:19.719488 | 10 | 30 | 2 |
| 17:46:19.790540 | 10 | 40 | 0 |

在同一内存会话比较资源 ID：五页累计 **10 个不同资源 ID**，任意两页交集为零，offset40
取得真实空数组后停止。因此第一个 4 行短页不能作为遍历终点。本次响应没有提供过滤前
总数，不能把 10 个可见资源推广成平台全部资源，也不能据短页形态擅自确定服务端过滤/
分页的先后顺序。ID 只参与内存集合比较，未导出。

资源读取字段全部出自官方已发布 query，不用 GraphQL introspection 或猜字段。实际返回
的规则字段包括 `capacity/capacity_field_type/capacity_string`、开放起止日期/时刻、
`appointment_date_rule/week_rule_*/days_rule_*`、提前预约上下限、时段/间隔、批量/周期、
`hide_appointment_information/hide_resources_detail/need_approve/open_process_form`，以及
`resourcesConfig` 中的时长/次数、签到/签退、归还审批等配置。第一页四行均有
`resourcesConfig`，部分楼层、校区或日期字段为空；空值不能改写成默认许可或零。
这是实际资源配置读取，不代表已通过任何预约、签到或设备操作验收，也不代表账号必然
能申请所有返回资源。

**17:34:17.092745 UTC**，同一固定 POST 读取
`findResourcesTypeAllByAccountForDisplay`，JSON `variables={}`，返回
`data.findResourcesTypeAllByAccountForDisplay[5]`、HTTP 200、无 GraphQL 错误。实际字段
包括类型名、时间/次数/时长限制、取消规则、对象/频率验证、周期/批量、容量方式和
`appointment_category`。这些字段在原 query 模板中声明、响应中已观察到；没有以外观
像 query 的名字放行写操作，也没有调用 `updateAppointmentState`、新建、取消或签到。

静态来源仍为前报告已取得的 `ehall-static-graphql-operations.json` 及其原公开 bundle，
本轮没有把静态模板解析时间当作脚本重新下载。`round2/ehall_aux.py` 只是临时研究 helper；
所有本人字段、令牌和资源 ID 均由 root 私密内存管理。

## 6. ELC：本人的 MRBS 日/周/月可读，检索空提示仍按实际证据描述

root 依已有 ELC/MySTU 来源的独立业务 HTTP 会话读取学校实际发布路径；不是把新系统
名称或匿名 200 当作本人认证。**17:03:01.027534 UTC**，ELC 根页 200；其后通过原页面
真实链接进入预约模块。没有猜个人 ID、查看其他人的预约详情、报告或导出名单。

| 实际请求时间 UTC | 同来源路径 | 结果 |
| --- | --- | --- |
| 17:31:06.704780 | `/courses/elc/blocks/mrbs/web/index.php` | 303，实际发布到日历页 |
| 17:31:29.915674 | `/courses/elc/blocks/mrbs/web/day.php` | GET 200，原 `day/month/year` 参数来自跳转 |
| 17:32:35.106361 | `/courses/elc/blocks/mrbs/web/week.php` | GET 200，原日历链接的 `year/month/day/area` |
| 17:32:35.248387 | `/courses/elc/blocks/mrbs/web/month.php` | GET 200，原链接的 `year/month/area` |
| 17:32:35.377357 | `/courses/elc/blocks/mrbs/web/search.php` | GET 200，沿日历原表单的公开查询合同 |
| 17:33:16.680092 | `/courses/elc/user/profile.php` | GET 200，链接来自当前本人页，未导出实际 ID |

搜索 form 的 method 为 GET，字段白名单为
`search_str/day/month/year/area/lang`，日期、场区和语言保留该次原表单值，仅把搜索词设为
合成无匹配字面词。**17:34:17.155550 UTC** 的本地解析只对应上述缓存：查询词正确回显，
没有 `view_entry` 详情链接，但已检查的固定“无匹配”提示未命中。因此当前证据可以描述
“本次查询返回无详情链接”，还不能伪造官网明确的零条提示、统计总数或分页末页。
日/周/月页面成功返回，也不自动证明某时段空闲、具有申请资格或可自动提交。
**17:47:22 UTC** 追加的仍是纯缓存复核：原响应严格 UTF8 解码成功，扩大后的固定英文/
中文无结果模式全部未命中，查询词仍精确回显、详情链接仍为 0，也没有识别到带搜索结果
ID 的表格。因此保留上述证据边界，没有把本地模式解析时间写成重新查询时间。

同次缓存身份复核：本人 profile 可见文字与 root 已有预期姓名精确匹配；预期学校邮箱和
学号未在本页可见文字中命中。姓名和 ID 都没有落盘。不能把未命中邮箱/学号解释成学校
账号不存在，也不能据姓名匹配推广为跨业务永久唯一 ID 规则。

## 7. 安全证据

- root 本轮安全摘要：`output/campus-protocol-survey/round2/observations.jsonl`，分别保留真实
  GET 与 `network_request_performed=false` 的本地解析时间、哈希、数量和布尔值。
- 本子任务公开单位/分页证据：`round2/utilities-booking/public-script-receipts.json` 及两份
  未改字节的公开 JS；没有保存本人页面、账单、宿舍表或 WebForms 状态值。
- `round2/root_aux.py` 是忽略目录中的临时研究辅助，复用 root 的独立内存业务客户端；
  不是产品新适配器、工具接口或永久认证配置。

本轮执行过程中临时缺少研究解析依赖属于本地调查器问题，不是学校站点故障；后续已使用
无额外依赖的字面量解析并保留 hole，不能把修复后的重解析写成新联网取数。
