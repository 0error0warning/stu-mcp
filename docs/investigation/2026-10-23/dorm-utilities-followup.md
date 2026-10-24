# 宿舍与水电：HTTP 协议补查

本轮研究 `dorm.stu.edu.cn`、`power.stu.edu.cn`，不接入 MCP。先匿名核对原入口及
HTTPS 同路径，随后由主任务用本次获准的独立 HTTP 客户端完成认证并只读打开实际导航。
下文区分真实响应、公开脚本静态声明和仍待验证的合同。没有运行浏览器、缴费、代缴设置、
留校/退宿申请或资料变更。学校账号密码仅由主任务在 HTTPS SSO 内使用；各业务 jar 独立，
不复制 SSO Cookie。本报告不保留票据、Cookie、页面隐藏字段值及个人记录。

联网核查区间：2026-10-23 **13:06:50–14:12:40 UTC**，即北京时间 21:06:50–22:12:40；
13:24 / 13:26 / 13:39 / 14:07:05 / 14:11:53 / 14:17:40 的分析另标缓存解析，不能混作联网请求时间。
本机纯 HTTP，`httpx trust_env=False`、正常 TLS 校验、有界超时，没有改系统代理、Clash、
DNS、证书或 hosts。应用层忽略环境代理不证明绕开系统 TUN。匿名证据在忽略目录
`output/campus-protocol-survey/dorm-utilities-followup/observations.jsonl`；后续安全结构摘要及
公开业务脚本在 `output/campus-protocol-survey/followup/`。独立匿名网络复查在前者目录的
`anonymous-recheck.jsonl`。认证状态只在进程内保留。**最新结果是在恢复校园网后重新认证、
真实 GET 成功及历史筛选 POST 成功；第 6 节的热点故障是此前过程，已不代表当前阻碍。**
最新本人水电查询为 **14:09:55 UTC**；**14:12:40** 只重新读取公开脚本，不是本人账单或读数更新。
此前历史数组的“9 列”是临时调查器删除稀疏空槽造成的误计，已撤回；第 4 节给出保留位置后的纠正。

## 1. 精确入口与协议对照

`default.aspx` 来自入口自身的真实 CAS `service`，HTTPS 对照是本轮要求的同主机同路径
检查。匿名探测均止于 SSO，没有发票据。

| 匿名 GET | 本轮结果 | 真实 SSO `service` / 阻碍 |
| --- | --- | --- |
| `http://dorm.stu.edu.cn/` | 302 到 HTTPS 学校 SSO | `http://dorm.stu.edu.cn/default.aspx` |
| `http://dorm.stu.edu.cn/default.aspx` | 同上 | 相同 HTTP service |
| `https://dorm.stu.edu.cn/` | TLS 正常，302 到 HTTPS 学校 SSO | `https://dorm.stu.edu.cn/default.aspx` |
| `https://dorm.stu.edu.cn/default.aspx` | 同上 | 相同 HTTPS service |
| `http://power.stu.edu.cn/` | 302 到 HTTPS 学校 SSO | `http://power.stu.edu.cn/default.aspx` |
| `http://power.stu.edu.cn/default.aspx` | 同上 | 相同 HTTP service |
| `https://power.stu.edu.cn/` | 连接拒绝 `WinError 10061`，无 HTTP 响应 | 未到 TLS 校验或业务页面 |
| `https://power.stu.edu.cn/default.aspx` | 同样连接拒绝 | 不是证书错误，不能靠关闭 TLS 校验解决 |

认证目标均为 `https://sso.stu.edu.cn/login`。SSO 的 HTTPS 与业务回调协议须分别记录。
随后 dorm 固定 HTTPS service 已接受本次认证并返回业务 HTML；不是只有匿名 302。
用户本次明确允许 power 官方 HTTP 只读票据回调后，主任务使用新票据及 power 独立 jar，
于 **13:11:19 UTC** 落到 `http://power.stu.edu.cn/index.htm`（200）。这证明本次 HTTP
认证路线可进入业务页，不意味着可持久放宽产品设置或获得缴费授权。

## 2. 官方用途与校区边界

[2025 官方智慧校园简介](https://zs.med.stu.edu.cn/upload_files/file/20250801/1754016918198845.pdf)
是前轮学校说明：学生事务及宿舍管理指向 `xg`，水电指向 `power`。本轮没有重下此 PDF，
不能据它认定旧 dorm 与 xg 已迁移、合并或停用。

本轮重新 GET [东海岸校区 2024-01-15 水电通知](https://stuecc.stu.edu.cn/info/1027/1395.htm)，
于 **13:08:03 UTC** 返回 200，标题“关于对东海岸校区欠缴水电费学生宿舍进行断电的通知”。
真实 href 为 `http://power.stu.edu.cn/`。通知涉及校园账号、自助缴费、代理缴费和欠费处理；
历史东海岸规则、扣费/复电时间不能当成 2026 年桑浦山规则或本人当前欠费证据。

## 3. dorm：真实导航与读取边界

**13:11:18 UTC**：本次 HTTPS 认证返回 `default.aspx` 200。页面为服务端 HTML，采用
ASP.NET 页面状态（`__VIEWSTATE`、`__VIEWSTATEGENERATOR`）；不能仅以 200 判定本人数据
正确，仍需正向身份/本人关联校验。**13:13:11–13 UTC** 沿实际导航 GET 三个固定 FID，均 200：

| 实际 GET 导航 | 页面声明的 POST action | 可见表头 / 用途 | 边界 |
| --- | --- | --- | --- |
| `/Index.aspx?FID=EEDF550D66B6D505` | `/CheckInOrOut.aspx?FID=EEDF550D66B6D505` | 学号、姓名、性别、学院、原入住社区/书院、联系方式、状态、取消操作 | 读取列表；“取消操作”可能改状态，不执行 |
| `/Index.aspx?FID=09005F4C98720662` | `/DormStayList.aspx?FID=09005F4C98720662` | 申请日期、学号、姓名、学院、年级、宿舍、临时宿舍、留校时段、状态、操作 | 含 `ctl00$CPHContent$btnCheckIn` 及 `__EVENTVALIDATION`；留校申请属于写入，不执行 |
| `/Index.aspx?FID=A851CEBD694D246E` | `/MyDormitory.aspx?FID=A851CEBD694D246E` | 序号、房号、床位号、学号、姓名、学院、专业；表 ID `ctl00_CPHContent_GridView1` | 可能含室友信息；只在内存核对本人关联，不导出整表 |

FID 是页面真实导航标识，不是枚举得出。返回页的 form action 与导航 URL 不同，适配时
不能把所有 POST 发回 `Index.aspx`。摘要中的 `tables.rows` 是 HTML `tr` 数量，含表头/
空态等，**不能当成实际申请数、住宿人数或本人身份成功证据**。

目前已验证服务端 HTML 可经纯 HTTP 客户端读取，未发现必须浏览器渲染的查询步骤。
尚未验证分页、列表无记录合同及当前本人完整身份绑定。第 7 节已取得 dorm 302 到 SSO、
续票后恢复 200 的会话失效/认证不足样本，更全面的失效响应判据仍需扩充；未提交任何住宿
POST。页面含其他人信息也不赋予查询/导出他人数据的范围。

**缓存本人关联核对**：13:39:07 UTC，主任务仅在内存中解析先前 **13:13:12 UTC** 已获取的
`MyDormitory.aspx` 响应。按 `ctl00_CPHContent_GridView1` 的 7 个表头提取出 3 个合法数据行，
与用户此前提供的姓名在“姓名”列作精确比较：**本人关联匹配 `true`、匹配行数 1**。
只记录布尔/数量，不保存姓名、学号、房号、床位或室友内容。这是该成功快照的本人关联
证据，尚不是学号与 SSO 账号字段完整正向绑定；13:39 是本地解析时间，不能写成最新成功
联网查询。当时网络尚未恢复，保留此原始快照及获取时间；之后的联网恢复另见第 7 节。

## 4. power：框架、表单与真正数据入口

认证后 `index.htm` 是 frameset，frame 为 `Banner.aspx`、`index_Menu.aspx`、`left.htm`、
`Page/ExtHeadPage.aspx`、`bottom.htm`。主任务于 **13:13:13 UTC** GET 菜单 200：

| 真实页面/导航 | 观察结果 | 处理范围 |
| --- | --- | --- |
| `/Page/ExtHeadPage.aspx` | **13:13:14** 实际 GET 200；13:14:43 / 13:26:04 是同一缓存页本地解析；**13:41:17** 重新 GET 200；引用 `ExtJS/headpagegrouping.js` | 读数/费用显示；结构及本轮恢复见下文 |
| `/Page/ExtChargeSearch.aspx`，“历史账单查询” | **13:14:44** 实际 GET 200；13:24:07 是同一缓存页本地解析；**13:41:16 / 14:06:06** 重新 GET 200，**13:41:28 / 14:09:55** 只读筛选 POST 200；引用 `ExtJS/chargegrouping.js` | 成功结果由 HTML 内联数组承载；筛选合同及稀疏位置已验证 |
| `/Page/SelfPay.aspx`，“一卡通自助缴费” | 仅在菜单看到，**没有打开** | 支付/授权/代缴设置不在本轮范围 |

### 4.1 历史账单筛选：已观察表单声明

真实 form 为 **POST `/Page/ExtChargeSearch.aspx`**。控件为 `dp_billStatus`（select）、
`ImgSearch`（image，未声明 onclick），另有 `__VIEWSTATE`、`__VIEWSTATEGENERATOR`。
以下是 **13:14:44 UTC 获取的历史页快照**中的真实选项，于 13:24:07 在内存中解析，
没有新联网：

| `dp_billStatus` 值 | 页面文字 | 本次 selected |
| --- | --- | --- |
| `0` | 未缴费 | 否 |
| `1` | 已缴费 | 否 |
| `2` | 已退款 | 否 |
| `3` | 查无缴费人 | 否 |
| `4` | 未退款 | 否 |
| `-1` | 所有 | **是** |

最小只读查询候选为：进程内保留的真实页面状态、当前/用户选择的真实 `dp_billStatus`，
以及图像提交的 `ImgSearch.x` / `ImgSearch.y`。当前 -1 重现查询无需学号/房号参数。
恢复前这只是表单声明得到的查询候选，**13:32 的尝试未成功**；不能猜加 `__EVENTTARGET`、
`__EVENTVALIDATION` 或未出现的过滤参数。主任务于 **13:32:51 UTC** 严格限定原表单状态、
`dp_billStatus=0`（未缴费）及 `ImgSearch.x/y`，准备一次只读查询，实际请求发生
`ConnectError`，没有收到响应。不能把它说成筛选成功、无未缴费账单或服务器拒绝操作。
恢复校园网并重新认证后，**13:41:28 UTC** 从新鲜表单仅提交上述五个字段，
`dp_billStatus=0`，真实 POST 200，返回 selected=0，历史数组 4 行；当时列数由临时调查器误计，已在第 4.2 节纠正。
这验证了本次“未缴费”只读筛选合同及其数据响应，不代表其他筛选均已测试；没有打开
SelfPay 或进行支付。网络失败尝试已消耗原先的查询执行额度，恢复后用独立、有界的
`after_network_restore` 额度执行一次；不是重试缴费或重复交易。
**14:09:55 UTC** 再按新鲜正常表单执行一次相同未缴费查询，200、4 行；修复后的解析保留每行
12 个位置。**14:11:53 UTC** 仅对这个响应作本地 AST 复核，确认位置 2/3/4 均为省略元素，
不是显式 `null`；复核本身没有新网络请求。

### 4.2 实际内联数组与稀疏空槽纠正

两脚本于 **13:15:46 UTC** GET 200，按原始 GB18030 解码分析，没有执行 JS：

- `/ExtJS/headpagegrouping.js`，SHA256 `17b18067bd319b4a3e26113af6cb9315fa4aff6734fc82451cdc6b0b00a10839`。
- `/ExtJS/chargegrouping.js`，SHA256 `b064936647b73be966a2c01da977d1a820ea56354601413c3b4ee9e2f65a7127`。

二者使用 Ext JS 2.2 `ArrayReader` + `GroupingStore({data: ...})`，不是远程 JSON store。
脚本没有 `Ajax`、`HttpProxy`、data URL 或分页请求；排序/分组在本地完成，固定 grid 高度
不是分页。历史按 Address 分组升序，读数按 CountDate 分组升序。脚本自带空数组
`Ext.grid.dummyData` / `flowdummyData` 是模板初始化，**不代表本人没有账单/用量**。

**13:14:44 获取的历史 HTML 快照**实际内联赋值 `Ext.grid.dummyData`，13:24:07 本地结构
解析确认 **25 行**，但临时调查器 `constant()` 使用 `if x` 过滤 `row.elements` 中代表省略元素的
`None` 节点，删除了三个空槽，错误地报告为“9 列”。未缴费 4 行的早期摘要也受此错误影响。
**这是调查器错误，不是上游把 12 字段改成 9 字段；原先 9 与 12 冲突的结论撤回。** 行数 25/4 不受影响。

**14:06:06 UTC** 新 GET 历史页真实返回 200、25 行；**14:07:05 UTC** 本地 AST 逐行保留
`row.elements` 的所有位置，确认每行均为 **12 个位置**，其中位置 **2、3、4** 每行都是 JavaScript
省略元素（sparse holes），没有显式 `null`。位置 0 为 `str`、1 为 `float`，5–11 均为 `str`。
14:09:55 的未缴费新查询与 14:11:53 缓存 AST 复核再次确认 4 行同样的 12 位置及空槽。

hole 是缺失位置，不能补 0、冒充显式 `null` 或删除后将后续字段左移。忽略目录的
`sparse_fixture.py`/合成 JSON 单独验证了 12 个位置、空槽索引和后续字段不移动，不含真实数据；
合成验证不代替上面的真实响应。本轮没有持久保存个人 HTML，没有导出地址、金额、缴费人或操作人。
例如以下纯合成片段有 12 个位置、9 个已赋值元素，`"unit"` 仍在位置 5：

```js
["sample", 1.25, , , , "unit", "status", "time", "payer", "operator", "resident", "period"]
```

25 只是本次数组长度，不能推广成完整历史数、无分页保证或特定校区覆盖。

### 4.3 字段合同：静态声明与实际位置分别核对

读数 `dummyData` 声明 12 位置（0 起）：

| 位置 | 字段 | 页面列头/声明 |
| --- | --- | --- |
| 0 | Address | 地址 |
| 1 | MeterName | 表类 |
| 2 | PowerDataCurrent | 本次行码；float |
| 3 | PowerDataPrevious | 上次行码；float |
| 4 | Quotiety | 倍感系数；float |
| 5 | PowerDataVerify | 调整量；float |
| 6 | PowerDataUsed | 使用量；float |
| 7 | PowerDerate | 减免量；float |
| 8 | PowerPrice | 单价(元)；float |
| 9 | PowerReceivable | 费用(元)；float |
| 10 | CountDate | **计量区间**，不是已证实的单一读表日期 |
| 11 | Remark | 备注 |

`flowdummyData` 再声明位置 12 `ActualPerson`，客户端用于人数和人均费用。
**13:26:04 UTC** 主任务在内存解析 **13:13:14 已获取的读数页快照**，没有新联网；
内联数组结构为 `dummyData=[]`、
`flowdummyData` 12 行，抽样前三行均 13 列。13 列与 flow reader 宽度相符，但空数组的业务含义、金额
口径、读数单位及本人宿舍关联仍待验证。没有导出读数、地址、人数或金额值。

**14:12:40 UTC** 新 GET 当前页实际引用的 `/ExtJS/chargegrouping.js` 返回 200，SHA256 仍为
`b064936647b73be966a2c01da977d1a820ea56354601413c3b4ee9e2f65a7127`，与 13:15:46 所取版本完全相同。
再次提取 `ArrayReader` 的 12 字段、grid 的 `dataIndex` 和可见列头，结合保留空槽的真实响应，可确定下表
**位置对应关系**；它不额外证明金额单位、余额口径、分摊或学校完整业务规则。

| 位置（0 起） | reader 字段 | 可见列头 | reader 类型声明 | 25 行全部 / 4 行未缴费的原始类型与缺失状态 |
| --- | --- | --- | --- | --- |
| 0 | Address | 地址 | 未指定 | `str`，位置存在 |
| 1 | PayAmount | 本期应付 | `float` | `float`，位置存在 |
| 2 | LastTimeSurplus | 上期结余 | `float` | **missing：每行均为 hole**，无显式 `null` |
| 3 | ThisTimeActualPayAmount | 本期实收 | `float` | **missing：每行均为 hole**，无显式 `null` |
| 4 | ThisTimeSurplus | 本期结余 | `float` | **missing：每行均为 hole**，无显式 `null` |
| 5 | MeterPropName | 使用单位 | 未指定 | `str`，位置存在 |
| 6 | BillStatusName | 缴费状态 | 未指定 | `str`，位置存在 |
| 7 | UpdateTime | 缴费时间 | 未指定 | `str`，位置存在 |
| 8 | UserName | 缴费人 | 未指定 | `str`，位置存在 |
| 9 | Operator | 收款人 | 未指定 | `str`，位置存在 |
| 10 | ConsignerID | 实住人 | 未指定 | `str`，位置存在 |
| 11 | CountDate | 计量区间 | 未指定 | `str`，位置存在 |

源注释与列头对 `LastTimeSurplus` 有出入，以可见列头记上期结余；本次相应位置缺失，不能推断余额为零。
`ConsignerID` 列头为“实住人”，不可因 ID 后缀认定它是稳定用户标识。
`PayAmount`、`PowerReceivable`、`ThisTimeSurplus` 也不可合并成同一个“余额”。

### 4.4 客户端汇总的局限

读数脚本按 `max(PowerDataUsed-PowerDerate,0)` 统计用量、按 `PowerReceivable` 求费用；
`getPowerAmountPay` 用最后一行 `ActualPerson` 除总费用。表类分支为“电表”“水表”“热水表”
及“清洁水表”。静态代码的“清洁水表”分支把用量加到 `WaterAmount`，`CleanWaterAmount`
保持零；人数没有可见零值保护/金额舍入。这里只记录静态风险，没有证实影响本次个人账单；
后续不得照搬前端汇总代替服务端应付/实收字段。

## 5. 当前结论与剩余验证

本次 dorm HTTPS、power 官方 HTTP 认证路线均进入业务 HTML；校园网恢复后重新认证、
宿舍/水电真实 GET 及历史只读筛选都成功，证实本轮读取无需浏览器。dorm 已有三个
真实导航的表头/状态字段及一份快照的本人姓名关联证据；power 已有框架、读数、历史及
未缴费结果与已退款空结果的真实响应；**字段语义与完整数据范围尚未完成全部验收**。

后续可在独立客户端中完善本人身份字段绑定、金额/单位/分摊语义及完整范围，
并扩充会话失效/认证不足判据；dorm 已实测的 302 SSO 续票恢复样本见第 7 节，无需再为
已验证的筛选合同重复请求。
历史行宽的疑点已由稀疏空槽复核解决，最终位置对应见第 4.3 节；缺失的三个金额位置不能补零，
也不能据列头把应付、实收或结余混作同一余额。无需枚举其他学号、宿舍或筛选；
不访问 SelfPay、申请、取消、代缴设置。

仍未知：除未缴费/已退款外的筛选、分页/完整范围、当前学年校区覆盖、余额/分摊
含义、水电 500 根因及更全面的会话失效/认证不足判据；dorm 的 302 SSO/续票恢复样本已
验证。可读不等于所有业务或写入完成验证，不等于能跟随任意重定向、复制
其他业务会话或永久使用旧内网 IP。

## 6. 此前连接变化：热点期间没有业务响应

主任务 **13:22:33 UTC** GET 历史页发生 `ConnectTimeout`。之后 13:24:07 / 13:26:04 只是
对先前成功响应的缓存解析，**没有新的 200 网络响应，不能证明超时后连接已恢复**。
此前成功也不证明系统永久可达，后续连接失败也不足以证明系统永久停用。13:32:51 只读筛选请求的
`ConnectError` 后，主任务于 **13:34 UTC** 只读核对连接配置，确认本机已在 OPPO 手机热点，
不同于早前校园网路径。没有自动切网、修改 DNS 或使用旧 IP 重试。

随后本子任务使用全新匿名 jar、`trust_env=False`、正常 TLS、连接最多 3 秒/读取 4 秒，
逐项一次复查。DNS 使用当前系统解析器，单独有 4 秒上限；未指定公共 DNS 或固定 IP。

| 核查时间（UTC） | 匿名检查 | 结果 |
| --- | --- | --- |
| 13:34:51 | 系统解析 `power.stu.edu.cn` | 返回 `202.104.245.183`；只说明当前解析结果 |
| 13:34:54 | GET `http://power.stu.edu.cn/` | `ConnectError`，没有 HTTP 响应 |
| 13:34:58 | GET `https://dorm.stu.edu.cn/MyDormitory.aspx?FID=A851CEBD694D246E` | `ConnectTimeout`，没有 HTTP 响应 |
| 13:35:01 | GET `http://power.stu.edu.cn/Page/ExtChargeSearch.aspx` | `ConnectTimeout`，没有 HTTP 响应 |

**这三次检查只能确认当时网络通道不可达，不能新判定匿名可读、需认证、无权限、会话过期或
业务数据变化。** 第 3–4 节的 dorm / power schema 是主任务先前隔离的已认证客户端响应，
不是这三次匿名请求拿到的内容；匿名访问边界仍需在服务可达后核实。DNS 返回地址也不
证明 TCP 服务可达。保留各次成功/失败的原时间，不用 13:13/13:14 成功快照，或把
13:24/13:26/13:39 缓存解析时间，冒充联网成功。后续恢复是下面独立的新请求证据。

## 7. 校园网恢复后：新认证、读取与只读筛选成功

主任务 **13:40 UTC** 只读确认 WLAN 已切回 `stu.edu.cn`，由用户切网，没有自动修改网络。
随后真实网络请求按顺序产生以下结果，均不是旧响应再解析：

| UTC | 请求/动作 | 真实结果与边界 |
| --- | --- | --- |
| 13:40:58 | 普通 GET power `/Page/ExtChargeSearch.aspx`，无查询串 | 500；错误标题只记录关键词“order 附近语法错误”，没有 SQL 测试、参数注入或故障探测 |
| 13:40:58 | GET dorm `/Index.aspx` | 302 到学校 SSO；与当前业务会话失效/不足相符，但不同于网络连接失败 |
| 13:41:15–16 | 中央现有登录态为两个固定 service 分别重发新票据，各自 jar 处理回调 | power HTTP 落到 `index.htm` 200；dorm HTTPS 落到 `default.aspx` 200；没有再次输入密码或复制中央 Cookie 到业务 |
| 13:41:16 | GET power 历史页 | 200，`Ext.grid.dummyData` 25 行；selected=-1“所有”；早期列数误计已撤回，后续稀疏位置复核见下表 |
| 13:41:17 | GET power 读数页 | 200，`dummyData` 空，`flowdummyData` 12 行、全部 13 列 |
| 13:41:18 | GET dorm 原固定 MyDormitory 导航 | 200，原 7 个表头，4 个 HTML `tr`；没有把 `tr` 数当住宿人数或重做完整身份绑定 |
| 13:41:28 | 一次 POST power 历史页，只提交新鲜表单五字段，筛选 `0` | 200，selected=0“未缴费”，数组 4 行；早期列数误计已撤回；只读查询完成，没有支付/申请/设置变更 |
| 13:43:22 | 按同一真实表单的新鲜 WebForms 状态及 `ImgSearch.x/y`，POST `dp_billStatus=2` | 200，selected=2“已退款”，`Ext.grid.dummyData=[]`、0 行；只切换查询筛选，**没有执行退款** |

最后一项提供明确空结果样本：正常业务 HTML、有效 selected=2 与解析成功的空数组同时出现。
它证明本次“已退款”查询可以成功返回空结果，不代表账户从未退款或所有账期均完整覆盖；
不能把连接异常、500、缺失数组或解析失败都归并成这个空态。没有输出任何账单金融字段。

power 500 在重新认证后恢复，**可推测与当时业务会话状态有关，但没有证实根因**。
因此现阶段的错误合同需同时识别连接失败、SSO 重定向和业务 500；不可把 500 当空记录，
也不可断言所有 500 都能靠重登解决。dorm 的 **302 → SSO → 续票后 200** 已构成本次会话
失效/认证不足响应链的实测样本，但没有区分具体失效原因。匿名直达这两个具体业务页的访问边界仍未独立验证，
不能用上表已认证响应证明匿名可读。

本次新鲜响应每位置的原始类型集合（只保留类型，不保留个人值）：

| 数据结构 | 位置（0 起） | 原始类型集合 |
| --- | --- | --- |
| 历史全部 25 行及未缴费 4 行（后续保留空槽复核） | 0 | `str` |
| 同上 | 1 | `float` |
| 同上 | 2–4 | 每列均为 hole，**missing**；无显式 `null`，没有可报告的值类型 |
| 同上 | 5–11 | 每列均 `str` |
| flow 12 行 | 0–1、10–11 | 每列均 `str` |
| flow 12 行 | 2–3、6–9 | 每列均 `float` 或 `int` |
| flow 12 行 | 4–5、12 | 每列均 `int` |

这是本次响应的类型观察，不能当所有账期固定 schema。原摘要的“9 列”和位置 2–8 字符串分布
因空槽被过滤而失真，已用保留位置的结果更正；不能将 hole 删除、补 0 或当作显式 `null`。
flow 13 列与 reader 宽度一致也不等于所有金额、单位与分摊语义已确认。

### 后续稀疏数组复核时序

| UTC | 网络 / 本地动作 | 结果与范围 |
| --- | --- | --- |
| 14:06:06 | 本人历史页新 GET | 200，25 行；不是旧缓存重新联网证明 |
| 14:07:05 | 仅在内存对上述响应作 AST 解析 | 全部 25 行各 12 个位置，位置 2/3/4 为 hole、无显式 `null`；修复调查器误计，没有新请求 |
| 14:09:55 | 新鲜正常表单的一次未缴费只读 POST | 200，selected=0、4 行，修复后保留 12 个位置；没有支付或退款 |
| 14:11:53 | 仅在内存复核上述 4 行 | 再次确认每行的 hole 都在 2/3/4；不是本人查询时间 |
| 14:12:40 | 新 GET 公开 `chargegrouping.js` | 200，与原脚本同 SHA256，12 字段及 `dataIndex`/列头再次确认；不是本人账单或读数更新 |

详细脱敏结构摘要在忽略目录 `followup/observations.jsonl`。最新成功本人读取时间分别保留为
dorm **13:41:18 UTC**、power **14:09:55 UTC**；power 读数页最近成功 GET 仍为 **13:41:17 UTC**。
各次本地解析和公开脚本读取不更新本人数据的采集时间，热点阻碍不再是当前事实。

## 8. 未缴费快照的有限字段一致性

**14:17:40 UTC** 只在内存中再次解析 **14:09:55 UTC** 的未缴费 4 行快照，没有新联网。
脱敏记录仅保留布尔与数量，结果如下：

| 校验 | 结果 |
| --- | --- |
| 行数 | 4 |
| 每行均为 12 个位置 | `true` |
| 每行位置 2/3/4 均缺失 | `true` |
| 每行位置 1 均为数值 | `true` |
| 每行位置 6 均与表单当前 selected 的“未缴费”文字一致 | `true` |
| 每行位置 6 均属于官网表单已发布的状态标签集合 | `true` |
| 导出个人值 | `false` |

这补强了位置 6 `BillStatusName` 与本次筛选的对应，不证明其他筛选、所有账期或金融字段含义。
位置 1 为数值不等于确认余额、支付或分摊算法；其余仍以第 5 节的未验收范围为准。
本人数据的最新采集时间仍为 **14:09:55 UTC**，不是本地校验时间。
