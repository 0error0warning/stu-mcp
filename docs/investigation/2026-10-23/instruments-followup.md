# 大型仪器共享：匿名 HTTP 接口补查

对象是主校 `zxsys.stu.edu.cn/genee`，另按正式链接核对 `equip` 与 `lrao`，不接入 MCP。
本轮真实联网时间为 **2026-10-23 15:04:53–15:15:50 UTC／北京时间 23:04:53–23:15:50**，
共 **30 次请求：GET 22、POST 8**。全部匿名、`trust_env=False`、正常 TLS 校验、有界超时，
未改网络或代理设置；忽略环境代理不证明绕过系统 TUN。

POST 仅还原公开页面明示的统计/目录读取，没有登录、预约、送样、注册、培训申请、缴费、
发送验证码或导出人员名单。没有使用学校密码、其他来源会话或浏览器。页面隐藏 token
仅随当前匿名流程在内存处理，不保存值；请求结束已关闭临时客户端。

安全元数据与两个公开 JS 位于忽略目录
`output/campus-protocol-survey/instruments-followup/`，没有保存 HTML、设备联系人、
预约人或操作人数据。文中设备 ID 都来自公开设备链接，不是用户编号或枚举出来的 ID。

## 1. 业务边界与入口

| 精确来源 | 本轮结果 | 用途与限制 |
| --- | --- | --- |
| [主校仪器共享首页](https://zxsys.stu.edu.cn/genee/) | 15:04:53 GET 200 | 公开仪器展示、分类、中心实验室通知、规则；根域 HTTP/HTTPS 的旧重定向本轮不重复验证 |
| [仪器列表](https://zxsys.stu.edu.cn/genee/category/equipment) | 200，首屏 HTML 不含设备结果 | 真实列表由下述匿名 POST 加载；不能把首屏无设备卡片当空目录 |
| [管理制度目录](https://zxsys.stu.edu.cn/genee/category/rules) | 15:05:21 GET 200 | 发布本科生开放、用户守则、独立操作证等规则链接；目录可读不等于本人有使用资格 |
| 首页“校内用户” | 发布 `/gateway/?from=stu&redirect=…/cf/main/!people/docking/login` | 本轮只核对发布关系，未请求网关或进行认证；不能借现有 MySTU/报修会话使用 |
| 首页“校外用户” | 发布 `http://zxsys.stu.edu.cn/cf/main/` | 独立业务入口，未登录；不能推断校外账户与学校统一账号等价 |
| `zxsys.med.stu.edu.cn` | 本轮未请求 | 独立医学院站点；主校目录里的“医学院”筛选不证明两站使用同一后台或会话 |

页面显式 `<base href="https://zxsys.stu.edu.cn/genee/">`。相对 AJAX、资源路径都必须
以它解析。`data-main=assets/js/main.js`，`main.js` 再设置 RequireJS
`baseUrl=assets/js`；`require(['more'])` 因而精确解析为 `/genee/assets/js/more.js`。

采集器最初第 2、3 个响应的脚本链接分析漏用了 HTML base，产生过
`/genee/category/assets/js/...` 的错误元数据；**没有请求这些错误路径**。第 4 个响应起
已修正，本文脚本合同来自实际读取的 `main.js/more.js`，不是那些分析错误。

## 2. 分类、筛选与真正分页接口

### 已发布分类

公开目录链接以 GET 查询串传递 `group/cat/keywords`，不是借人员 ID 过滤：

| 参数 | 当前页面发布的选项 |
| --- | --- |
| `cat` | `27` 有机分析、`28` 无机与元素分析、`29` 材料微区与表面分析；`0` 为页面发布的不限值 |
| `group` | `3` 中心实验室、`10` 医学院、`11` 理学院、`12` 工学院、`13` 化学化工学院、`17` 文科类共享仪器平台、`18` 公共卫生学院、`20/21/22` 三个实际发布的重点实验室；`0` 为不限值 |
| `keywords` | 页面搜索词；值、token 及编码应按当前表单/跳转保留，不猜其他参数 |

`group=10` 仍是**主校 genee 目录的一个机构筛选**，不能改用 `zxsys.med` 请求它。
当前这组目录选项也不能视为永久完整院系名录。

### 列表读取合同：已实测

```text
POST https://zxsys.stu.edu.cn/genee/AJAX/Stu/Equipment/getEquipments/{start}
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
```

页面 `new More` 传 `data:{ajax_form:...}`。默认 `ajax_form={"m":null}`，jQuery 表单编码为
`ajax_form[m]=`；合法分类页则增加原页生成的 `ajax_form[group]`、`ajax_form[cat]`。
不能把该对象按 JSON body 发送，也不能把不同大小写的 `AJAX` 与首页 `ajax` 路径合并。

| UTC／请求编号 | 输入 | 实际响应 |
| --- | --- | --- |
| 15:09:51／10 | `start=0`，默认筛选 | 200 HTML，50 个不同设备详情 ID，`data-more=50` |
| 15:10:19／13 | 按前一响应继续 `start=50` | 200 HTML，另 50 个 ID，与首批交集为 0，`data-more=100` |
| 15:11:48／17 | `start=0, group=0, cat=27`，由原分类页提取 | 200 HTML，12 个设备 ID，仍有 `data-more=50` |
| 15:15:36／27 | 同一分类继续 `start=50` | 200、49 字节，0 个设备/链接/表格，`data-more=-1` |

返回的是**设备卡片 HTML 片段**，不是 `items/total/page` JSON。真实详情 URL 为
`/genee/equipment/{页面给定ID}`。卡片另有 `cf/main/!equipments/...reserv` 的自主上机及
`.sample` 的送样链接；它们不是本次目录查询 API，没有打开或提交。

`more.js` 将片段追加到容器，读取片段顶层的 `[data-more]`，再移除该标记；其值就是
下一次 `start`。没有标记时也令 `start=-1`。**不能按本批不足 50 条提前判断终止**：
已实测的 12 条分类批仍指向 50，必须尊重服务端游标。默认只读了前 100 个不同设备，
没有扫完整库、没有固定总页数或保证无并发排序变化。

### 搜索、token 与错误/空结果

页头搜索的真实表单为 GET `/genee/search`，字段 `search_type/keywords/token`；
下拉类型是 `equipment`（仪器）与 `all`（全文）。表单 action 字面末尾有空白，按正常
URL 处理去除末尾空白；没有把它误请求成 `/search%20`。全文搜索尚未验证。

- 请求 15、16 使用旧页面快照且未带正常来源上下文，真实为 **302 到 `/genee/error/401`**；
  请求 18 直接向分类页附非空关键词、未保留搜索跳转 token，也返回同一路径。
- 15:12:53 的请求 20 使用**新鲜表单原 token 和正常 Referer**，仪器关键词搜索返回
  302 到 `/genee/category/equipment`，带 `keywords/token`。本轮没有跟进这次正向关键词
  的数据结果，不能称其已验证匹配设备数。
- 15:14:57–58 的请求 23–26 重建一次正常匿名搜索，保留当前 token，搜索一个普通的
  合成不匹配词，跟随服务器原始重定向得到 200 分类页。该页生成的 `ajax_form` 包含
  `keywords/token/m`；按它发送只读列表 POST 后得到 **200、49 字节、零设备、
  `data-more=-1`**。没有保存或向 Agent 展示 token。
- 请求 21 单独 GET 错误页，才是真正的 **HTTP 401**，标题为“HTTP 错误 401 - 您没有访问管理权限”。

因此匿名目录/搜索能够走通，但上下文缺失的请求会走权限样式错误页。由于新鲜度和
Referer 一同改变，**未确诊单一 token 过期、Referer 或其他服务器检查为根因**；不能据
错误文案要求管理员身份，更不能把 302 错误页当无搜索结果。空结果只以正常业务片段、
零设备及终止标记判断，本轮没有证据声称出现某句专门的“无数据”文案。

## 3. 统计、展示和设备详情

首页公开 JS 明示 `POST /genee/ajax/index/equipment/GetSummaryInfo`，表单字段
`res_type=json`。15:07:20 与 15:09:52 的两次读取均为 200，202 字节，
`Content-Type: application/json`；**HTTP JSON 解码结果仍是字符串**，再解码才是对象。
与原页 `JSON.parse(info)` 行为一致，不应强制当普通单层 JSON 对象。

内层实际键为：

```text
totalCount controlCount outServiceCount usingCount unUsingCount noLongInCount
totalPrice totalTime totalUse
```

页面分别消费前几个数量，额外金额/时长字段的单位与统计口径尚未核实。它是公开平台
汇总，不是本人用量、余额或权限；各状态也不能未经证明当作互斥集合相加。

首页明示 `POST .../GetDisplayEquipments`、`id=21`；15:07:20 真实返回 200 HTML，
有 20 个公开设备详情链接。这里的 `id` 是页面传出的展示配置，**不是已证实的设备 ID**。
没有因字段同名便将它与 `/equipment/21` 混用。

沿真实链接只读抽查：

| 详情 | 联网时间与结果 | 当前可确认内容 |
| --- | --- | --- |
| [设备 3](https://zxsys.stu.edu.cn/genee/equipment/3) | 15:09:53 GET 200，20558 字节 | `#summary-info` 可匿名读取主要规格/技术指标、主要功能及特色、主要附件及配置 |
| [设备 30](https://zxsys.stu.edu.cn/genee/equipment/30) | 15:12:53 GET 200，20536 字节 | 同一详情框架，含详细信息、预约、公告、收费等标签 |

两张详情的 `#summary-fee` 容器文字均为空，已读内联脚本没有另外加载价格的分支。
**这不等于免费、无收费规则或所有设备都不公开价格**；当前不能给出单台仪器实际费率。
没有复制设备联系人、联系电话或申请人信息。

详情内联的其他读取声明只静态记录，**未发送**：

| 声明 | 参数及客户端使用 | 未验证边界 |
| --- | --- | --- |
| `POST /genee/ajax/Index/Reserv/getReservations` | `id/start/end`，起止取 FullCalendar 的 Unix 秒；`dataType=json` 后还 `JSON.parse(result)`，使用 `item.id/uname/dtstart/dtend` | 会包含预约人姓名；没有取日历、收集预约人或将它当纯空闲时段接口。客户端声明 `timezone=local`，实际时区与权限未知 |
| `POST /genee/ajax/Index/Reserv/getNotices` | `id`，返回 HTML 替换公告表 tbody | 公告表头为名称/内容/发布日期，真实结果、权限及空态未验证 |

首页另有 `GetTopUsers/getrecords` 等人员或运行记录声明，本轮未调用。
`AJAX/Equipment/getRoot` 虽在脚本里，当前所读页面被 `if(0)` 禁用；不当成已启用接口。

## 4. 公开收费/资格规则，和本人可用性分开

15:06:52 实际 GET [测试费信用额度管理通知](https://zxsys.stu.edu.cn/genee/post/113)，
200，24575 字节。页面字面发布时间为 **2026-03-09 17:42:34**，正文署名 2026-03-09，
声明 2026-03-10 起执行；这些是原文日期，不是本轮联网时间。

可确认它规定的是**已注册课题组的年度测试信用额度及结算/预约限制**，并非每个学生的
现金余额或单台仪器价格。正文说明基础额度、根据上一周期结清金额调整、年度结算及
超限/逾期暂停预约等规则。规则可读不证明本人课题组已注册、余额充足、完成培训或有预约资格。

管理制度目录还发布本科生开放、独立操作证等不同规则，当前只核对链接，未逐页读取
或验证培训/资质接口。没有按公开通知自动提交任何资质申请或恢复预约请求。

## 5. equip/lrao 是资产入口，不是 genee 的别名

| 本轮精确请求 | UTC／结果 | 结论与限制 |
| --- | --- | --- |
| `http://equip.stu.edu.cn/` | 15:15:36，200，1324 字节 | 只见 3 个发布链接：`https://equip.stu.edu.cn/default.htm`、`https://lrao.stu.edu.cn/lrao/`（本部）、`https://lrao.stu.edu.cn/med/`（医学院） |
| `https://equip.stu.edu.cn/default.htm` | 15:15:49，正常 TLS，200，732 字节 | 当前标题解析含替换字符，不能据此判系统失效；没有取得可用资产查询合同 |
| `https://lrao.stu.edu.cn/lrao/` | 15:15:50，302 到 HTTPS 学校 SSO | service 精确为同一本部路径；止于认证入口，未借学校会话或跟进登录 |

先前其他调查 **12:14:06 UTC** 的 `default.htm` 缓存分析曾记录 `Login.aspx` frame；本轮
没有重取该 frame，不能写成 15:15 新验证的登录页。旧缓存经过文本保存，字节哈希不能
直接当本轮原响应对照。医学院 `/med/` 本轮也只核对发布关系，未复用本部身份或验证功能。

## 6. 证据及剩余缺口

| 证据 | 原始 SHA256 |
| --- | --- |
| 实读 `assets/js/main.js`（15:06:52） | `463a9055892b9a9bb50acba51128026472a400bbb23b716662d633468db10df5` |
| 实读 `assets/js/more.js`（15:07:20） | `68dae82780d7b5eaf712f2e1fc2a7b9e21b945eb1d939959f02513652f7711f3` |
| 空结果/分类终止片段（两次同哈希） | `6041aa309f3a4233225ad60319622f392ef793915b98132453b551a63d366df2` |

逐请求证据为忽略目录中的 `observations.jsonl`，真实请求编号 1–30；脚本仅保存上述两个
公开 JS。后续本地计数/字段比较不是新联网核查。该文件没有原响应 HTML、token 值、
Cookie 或个人记录；只留字段名称、结构、公开设备链接、游标、状态和原响应哈希。

已掌握匿名分类/分页/筛选/空态、详情技术说明及平台统计读取；仍缺：完整目录范围与
排序稳定性、其余分类/机构/全文搜索、单台价格与计费口径、正常认证后的本人资格及
可约规则、设备公告/时区合同、资产系统真正的读取接口。匿名可读不等于可自动预约或
计费授权。请求额度到 30 后停止，未在本轮扩展图书馆接口，也没有回到 r 或综测调查。
