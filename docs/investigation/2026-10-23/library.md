# 图书馆入口、协议与证据：2026-10-23

本页调查公开馆藏、读者中心、图书荐购、资源目录、CARSI、空间预约，以及图书馆首页直接发布的检索和失物招领入口；补查医学院图书馆及其实际链接的目录/读者服务。没有新增 MCP 功能，没有登录或借用已有个人会话，没有执行预约、续借、荐购、收藏、申请、取消等操作。

## 证据范围与读取路径

- 本机检查时间：`2026-10-23T12:08:49Z` 至 `12:23:08Z`（北京时间 20:08 至 20:23）。
- 医学院图书馆补查：`2026-10-23T12:43:08Z` 至 `12:44:07Z`（北京时间 20:43 至 20:44），仅首页和该页实际给出的 4 个目录/读者/门户目标，没有发送主校或医学院凭据。
- 本机 HTTP：`httpx`，`trust_env=False`，系统解析、正常证书校验、单次连接 5 秒/读等待 8 秒、至多四次同校域重定向、正文上限 2 MB；逐站和逐请求执行。应用层忽略环境代理不证明绕过系统 TUN，也不推断物理网络位置。
- `www.lib.stu.edu.cn` 本机 HTTPS 明确因证书过期失败。以下官网正文/表单证据由 **Firecrawl 远端读取**，返回 `statusCode=200`、`proxyUsed=basic`、`cacheState=miss`。这证明远端取得内容，不证明本机可连接，也不能据此改变本机 TLS 设置。返回 HTML 是其处理后的页面 DOM，没有原始响应脚本；不能据此断言官网没有 JavaScript。
- `app.lib.stu.edu.cn` HTTPS 因 `unable to get local issuer certificate` 失败。其 **HTTP 地址同时出现在官网首页及规章**，本轮单独检查这条已发布的匿名公开路径；没有自动把 HTTPS 认证降级或发送凭据。
- 公开脚本的字符串、路由和请求定义是 **静态线索**，不能证明学校启用了相应业务，不能证明该账号有权限。

忽略目录 `output/campus-protocol-survey/library/` 保存公开响应的状态/时间/哈希、必要脚本和解析结果。失物招领只保留表单、脚本和页面结构，不保存物品或联系人明细；认证入口返回的临时状态已从记录中删去。没有保存用户密码、Cookie、会话票据或令牌。

## 当前结果总表

| 业务 | 已发布入口及本轮结果 | 已掌握程度 |
| --- | --- | --- |
| 汕大馆藏 OPAC | 官网当前仍发布 `http://opac.lib.stu.edu.cn/opac.php`；HTTP 200 跳转壳，HTTPS 连接被拒绝 | 入口及跳转脚本已读，实际检索接口未知 |
| 本人借阅/续借/图书预约 | `http://opac.lib.stu.edu.cn/web/index.html?type=reader`；HTTP 200 Vue 壳 | 官网说明支持馆内账号或 MySTU；认证/本人列表接口未取得 |
| 图书荐购 | `http://opac.lib.stu.edu.cn/web/index.html?type=recommend`；同一壳页 | 官网说明需登录“我的图书馆”；提交接口未取得 |
| 主题书展 | `http://opac.lib.stu.edu.cn/apps/special/index.html`；HTTP 200 壳 | 数据/业务 JS 被替换为跳转脚本，未取得书展列表 |
| 数据库资源导航 | `https://www.lib.stu.edu.cn/zy/database`；远端 200 | HTML GET 筛选、130 条目录行、详情字段和空态已验证；本机证书受阻 |
| 校外资源/CARSI | `https://www.lib.stu.edu.cn/zy/xwfw`；远端 200 | 官方 SP/IdP 链接、公开 SAML 元数据已取得；未认证、未检验订购权限 |
| 空间预约 | 官网当前发布 `http://app.lib.stu.edu.cn/newic/`；HTTP 200 | API 基址、SSO 模式、匿名状态和菜单契约已验证；本人会话/可预约清单未验 |
| 超星发现 | 官网表单 `https://ss.zhizhen.com/s`；匿名 302 至独立登录页 | 查询参数 `sw` 已知；未检索、未认证 |
| 全国高校学术资源 CALIS | 旧 `http://www.yidu.edu.cn/510400/search.html` 301 至 `https://yidu.calis.edu.cn/510400/search.html` | 公开检索 JSON、分页、空态已实测；并非汕大 OPAC |
| 图书馆失物招领 | 官网当前发布 `http://app.lib.stu.edu.cn/3rdmana/lost/index/`；匿名 200 | GET `q` 搜索表单和服务端 HTML 已确认；分页/详情字段尚待补证 |
| 医学院图书馆 | `http://lib.med.stu.edu.cn/`；本机匿名 200 | 医学资源目录和指南可读；读者链接指主校 OPAC 旧参数，研讨室链接指医学院门户；不能合并认证或推断本人权限 |

## 1. OPAC、读者中心、荐购与书展

官方来源：[图书馆首页](https://www.lib.stu.edu.cn/)和[FAQ](https://www.lib.stu.edu.cn/faq-page)，本轮均远端读取。

### 已观察的页面与脚本

| 请求 | 结果与证据 |
| --- | --- |
| GET `https://opac.lib.stu.edu.cn/opac.php` | `WinError 10061`，未收到 HTTP；HTTPS 读者路径也同样拒绝 |
| GET `http://opac.lib.stu.edu.cn/opac.php` | 200，1442 字节，标题“自动跳转页面”，SHA256 `08a6e614fe32d236d1b0b810a491452409c1bab32bb05b422238b269631115aa` |
| GET `http://opac.lib.stu.edu.cn/index.html` | 与上一行完全相同的壳页 |
| GET `/web/index.html`、`?type=reader`、`?type=recommend` | 各 200，1495 字节，SHA256 `cbdec4d636a979108621b3103373b5dbb5b55ade7ad5b2ab7fd9a00b4ea31905`；尚无实际列表或登录表单 |
| GET `/apps/special/index.html` | 200，794 字节，引用公开书展组件、`/apps/special/data/data.js` 和 `main.js` |

`opac.php` 内联代码先调用 `Lcs.util.checkHost()`；若为馆员分支，静态定义 GET `/isLogin?container=controlcenter&component=beans`，以 `data.success` 选择 `/library/index.html` 或 `/libLogin/index.html`；否则到 `/web/index.html` 并保留原查询。**未请求馆员分支**。

关键阻碍是公开脚本内容：

- `/static/js/initialConfigParent.3.3.js`
- `/web/static/js/web.init.js`
- `/web/static/js/app.648cf6409785e459abb3.js`
- `/apps/special/data/data.js`
- `/apps/special/static/js/main.js`

这些不同路径均返回相同 **178 字节**脚本，SHA256 `84eb3fb4bacb19c73bdb60f63ff1f71ab63c89fb398d35cd21330c3931a58e31`。脚本根据 `window.top.location.origin` 是否包含 `/h5/` 跳 `/h5/index.html` 或 `/index.html`；它不是页面引用名对应的应用 bundle。该条件本身也与 `origin` 不带路径的定义不一致。本轮没有执行它，也没有绕过、改 UA 反复重试或猜测 API。

因此 **200 是壳页/脚本响应证据，不是 OPAC 检索或读者业务已跑通**。当前不能给出可靠的检索 URL/参数、书目详情/馆藏册数接口、本人借阅列表、CAS 回调和续借/预约/荐购提交契约。

### 官方说明能确认的功能边界

FAQ 明确说明 OPAC 可供联网计算机查询馆藏；这不等于本轮查询成功。本人业务有两种登录方式：馆内读者账号（说明为一卡通卡号）与 MySTU；不能把 MySTU 已配置当成已取得 OPAC 会话。

官方列出的本人业务包括当前借阅、续借、图书预约/取消、个人信息和邮箱、荐购。FAQ 对续借给出一次/15 天、逾期或已被他人预约不可续借等规则；这只是规则来源，不能代替服务器实际校验。预约说明中的“可出借册数少于0”与“全部外借”的解释存在文字歧义，未来适配应读取实际业务判据，不能直接把这句写成客户端条件。

还缺：正常业务脚本或学校修复后的页面、一次本人登录的正向身份依据、各只读分页/空态/过期响应，以及独立写入动作的真实表单和回执证据。

## 2. 数据库资源目录

### 公开 HTML 契约

远端实读 [GET `/zy/database`](https://www.lib.stu.edu.cn/zy/database)，并非 JSON API。页面是 Drupal 7 Views，表单 `method=get`、`action=https://www.lib.stu.edu.cn/zy/database`。

| 参数 | 观察值及含义 |
| --- | --- |
| `letter` | `All`；A–Z 对应当前下拉值 `102`–`127`，不能由字母直接当参数 |
| `subject` | `All` 或具体学科 taxonomy ID；例 `75`=电气/电子/信息与通信/控制/计算机，`144`=光学/仪器，`90`=综合；完整选项在证据 JSON |
| `leixing` | `All`；`172` 已购、`173` 试用、`174` 网络、`175` 自建 |
| `lang` | `All`；`100` 中文、`101` 外文 |

默认响应有 `table.views-table.cols-3`，表头为 **资源名称、资源类型、状态**；本轮页面 **130 个 `tbody tr`**，未出现分页链接。不能把这次单页数量固定成长期总数。

- 第一列：资源名与 `/database/{published_id}` 详情链接。
- 第二列：一个或多个资源类型，分别链接 `/zy/resource_type/{published_id}`；不是单值枚举。
- 第三列：已购/试用/网络/自建状态。它不是当前用户已获订购访问权。

远端表单验证：

| 请求 | 观察结果 |
| --- | --- |
| `?letter=102&subject=All&leixing=All&lang=All` | 200，A 筛选选中，5 条目录行 |
| `?letter=127&subject=144&leixing=175&lang=101` | 200，四个合法选项均选中，目录容器存在，**无表格、无 `tbody`、无专门“无结果”消息** |

空结果应以“资源目录容器/筛选表单完整且无结果区”识别，不能把 TLS 错误、登录页或 DOM 结构缺失都当成空目录。错误输入、服务端 5xx、未来分页和页面结构改变的响应仍未取得。

### 资源详情与访问条件

仅抽查官方列表实际链接的 [CNKI `/database/275`](https://www.lib.stu.edu.cn/database/275)，没有遍历 130 个商业数据库，更没有下载资源正文。可见字段：

| HTML 字段 | 业务含义 |
| --- | --- |
| `.field-name-field-link` | 一个或多个外部访问入口，显示名与 URL 均需保留 |
| `.field-name-body` | 数据库介绍、访问范围、例外说明；结构化能力有限 |
| `.field-name-field-db-type` | 文献类型，可多值 |
| `.field-name-field-db-lang` | 数据库语言 |
| `.field-name-field--leixing` | 已购/试用/网络/自建状态 |
| `.field-name-field-db-usage` | 使用说明附件链接；本轮未下载 |

详情介绍、公共目录、全文订购权限是三层事实。CNKI 官方说明还提醒学校 IP 权限与个人登录可能冲突，因此一个普通 200 或个人账号登录不能充当学校订购权限证据。

## 3. CARSI 与校外资源访问

[官方校外访问说明](https://www.lib.stu.edu.cn/zy/xwfw)列出 CARSI 与 WebVPN。其含义是：可用学校账号经 CARSI 访问**部分**资源；WebVPN 是另一条网络访问方式，且按馆方说明权限由学校管理。两者均不等于读者中心会话或全站资源均已授权。

已读到的具体协议例子：

- CNKI：`https://fsso.cnki.net/Shibboleth.sso/Login`，参数 `entityID=https://idp-lib.stu.edu.cn/idp/shibboleth`、`target=https://fsso.cnki.net/secure/default.aspx`。
- 超星发现：`https://fsso.zhizhen.com/Shibboleth.sso/Login`，同一 `entityID`，目标 `/carsi/secure`。
- Elsevier、JSTOR、Springer、Wiley 等由官网分别给出各自 SP URL 与 `entityID`/`entityId`/`idp` 等不同参数；不能统一套一个拼接模板。
- WebVPN 官方入口为 `https://webvpn.stu.edu.cn/`；本轮未进入其登录，不复核已有适配器。

本机 **正常 TLS** 实读 `GET https://idp-lib.stu.edu.cn/idp/shibboleth`：200、`application/xml`、14586 字节，SHA256 `dbd0f065004dec16a1e0eda95d1b41d8e177a3ad81d736481afe7ec3140aff46`。公开 SAML 元数据的 `entityID` 与馆方链接吻合，列出：

| Binding | IdP 公布路径（均未发送认证请求） |
| --- | --- |
| SAML 2 HTTP-Redirect | `/idp/profile/SAML2/Redirect/SSO` |
| SAML 2 HTTP-POST | `/idp/profile/SAML2/POST/SSO` |
| SAML 2 HTTP-POST-SimpleSign | `/idp/profile/SAML2/POST-SimpleSign/SSO` |
| Shibboleth 1 AuthnRequest | `/idp/profile/Shibboleth/SSO` |

元数据还公布 8443 的 SOAP ArtifactResolution 地址；**没有访问该非标准端口**。没有构造/发送 SAMLRequest、读取 SAMLResponse、验证账号/MFA/验证码或断言特定数据库订购权限。纯 HTTP 首次 CARSI 登录的可行性仍需专门、本人授权的实证。

## 4. 空间预约（newic / Information Commons）

### 前端、后端与身份

[官方规章](https://www.lib.stu.edu.cn/article-73.html)和首页均发布 HTTP `/newic/`。本机在该公开路径读取到 Vue SPA、配置和页面直链的 JS；HTTPS 的证书链问题单列，不旁路校验。

`GET /newic/config/config.js` 当前公开配置：

- `ApiUrl: '/ic-web'`，实际 API 根为 **`http://app.lib.stu.edu.cn/ic-web`**，不能误拼为 `/newic/ic-web`。
- `loginMode: 2`，注释为 CAS/单点登录；`addressPull: true`。
- axios 默认 `withCredentials=true`。GET 的包装参数使用 axios config 的 `params`；POST 则传请求体，不能把二者的内部变量名 `params` 当作同一种编码。
- 静态响应约定 `{code, message, data, count, vals}`；拦截器将 `code=300` 视为未登录/超时并发起身份流程，`code=0` 视为业务成功。

本轮匿名 GET 的**真实结果**：

| 完整 API 路径（共同根 `/ic-web`） | 响应 |
| --- | --- |
| `/sysConfig/public` | 200，`code=0`，`data` 是 `sysKey/sysValue` 配置数组；观察名“汕头大学图书馆空间预约平台”，`versioninfo=2.0`、`resvTimeUnit=10` |
| `/auth/userInfo` | 200，`code=300`、`data=null`，提示用户未登录 |
| `/roomMenu`、`/seatMenu` | 各 200，`code=300`，不能当成无房间/无座位 |
| `/activityMenu` | 200，`code=0`，3 项：研修间、东海岸研讨室、静音舱；字段含 `kindId/kindName/kindClass/kindProp/campusId/orderNum` 等 |
| `/borrowMenu`、`/digitalReadingRoomMenu`、`/psgSeatMenu` | 各 200，`code=0,data=[]`，这是该菜单的明确空态；不证明学校永久停用这些功能 |
| `/auth/address?finalAddress={官网HTTP页面}&manager=false&consoleType=16` | 200，`code=0,data` 为学校该应用的 `/newic/authcenter/toLoginPage` 地址；附 `redirectUrl/queryParam/typeCode/extInfo`。临时状态值已删去，未跟随、未取得业务会话 |

最后一行返回的内部回调模板涉及 `/newic/ic-web//auth/token?uuid={临时状态}`；它是上游实际返回的模板，不能改写成已验证可用的回调。认证仍缺最终 SSO 路径、正常 TLS/官方网络条件、身份正向判据及独立 Cookie 范围。

### 只读契约：以下均仅为静态定义，未取本人数据

从当天可读的页面脚本确定下列语义和路径。除上表外，没有请求这些受保护或未确认权限的接口。

| 功能 | 方法与 `/ic-web` 相对路径 | 静态字段与限制 |
| --- | --- | --- |
| 空间/座位和时段 | GET `/reserve` | `sysKind,resvDates,page,pageSize`；按展示模式使用 `labIds/kindIds,kindId/labId,campusId`；还见 `roomIds,devName,adddValues,devIds`，来自真实菜单/选择，不允许猜 ID |
| 场所分类与筛选 | GET `/devKind/labDevKinds`、`/lab/devKindLabs`、`/codingTable/getAll` | 分类依赖上一步真实菜单；未验证参数必需性 |
| 座位区域/开放 | GET `/reserve/areaInfo`、`/seatRoom/openScope`、`/seatRoom/open`、`/room/openTimes`、`/reserve/seatArea` | 详情需要真实房间 ID、日期和 `sysKind` |
| 房间概况 | GET `/roomDevice/roomInfos`、`/home/page/room/idle` | 静态存在；能否匿名、范围和返回结构未验 |
| 本人预约 | GET `/reserve/resvInfo`、`/activity/resvInfo`、`/activity/custom/resvInfo` | 不能从上面公共菜单推断已获本人记录权限 |
| 本人账号/信用 | GET `/account/info`、`/creditRec/getOwn`、`/creditPunishRec/surPlus`、`/creditStarRec/own` | 身份与数据字段尚未实测 |
| 本人使用/操作记录 | GET `/reserve/operate/rec`、`/checkLog/checkInfo`、`/psgLeaveRec/rec`、`/psgSignRec/viewDefaultRec` | 静态存在；含哪些本校实际业务未知 |
| 设备借用/其他本人记录 | GET `/borrow/reserve/own`、`/borrow/device/resvDevInfo`、`/resvVisitVolunteer/own` | 编译包存在，当前相关公共菜单为空，不能宣称已开放 |
| 通知与说明 | GET `/sysInfo`、`/sysInfo/help`、`/news`、`/news/questions` | 静态存在；本轮未取正文 |

`/reserve` 页面调用中，`resvDates` 使用 `YYYYMMDD`，一周展示拼为 `YYYYMMDD,YYYYMMDD`；分页初始 `page=1,pageSize=10`，可选 10/30/50/100。前端读取 `data` 数组与 `count`，房间/座位记录至少使用 `devId,devSn,devName,labId,labName,kindName,kindProp,openTimeList,resvInfo,resvRule,onlyView`；规则含开放时段、最早/最晚预约、时长和成员限制等。**这是调用点证据，尚未通过已登录真实响应确认字段稳定性或零结果表现。**

### 写入与挑战：仅识别，不发送

静态定义包含 POST `/reserve`、`/reserve/seat`、`/reserve/bulkAdd`、`/reserve/quickResv`、`/reserve/delete`、`/reserve/update`、`/reserve/endAhaed`（上游拼写如此）、`/reserve/endReserve`、`/reserve/time/expand`、`/resvMember/operate`、暂离/取消、账号更新、信用转换等。另有坐标 POST 用于界面读取；仅凭方法不能认定业务是否写入。本轮 **对 newic 未发送任何 POST**。

普通房间表单静态字段包含 `sysKind,appAccNo,memberKind,resvBeginTime,resvEndTime,testName,resvKind,resvProperty,appUrl,resvMember,resvDev,memo,captcha,addServices`。座位路径还见公钥、随机值和 `encryptVlaue`（上游拼写）、`resvDevEncrypts`；不能把普通房间表单直接用于座位。

编译包存在滑块/图形验证码组件及 POST `/captcha/get`、`/captcha/check`。这证明**存在挑战分支**，不能证明当前普通查询或学校 SSO 必须完成该挑战，也不能保证所有预约均能全自动完成。没有取挑战或尝试绕过。

官网规章明确区分研讨室、座位及签到/暂离/违约积分；东海岸研讨室也出现在当前菜单。未来适配必须保留对象、校区和预约规则，不能把所有空间当成“普通自习座位”。页面编译包的考试座位、志愿活动、储物柜、设备借用等路由只是候选，是否本校启用未证实。

## 5. 官网检索别名

### 超星发现与读秀

官网首页静态表单显示：

- 超星发现：`action=https://ss.zhizhen.com/s`、字段 `sw`，有中文/外文按钮；处理后的 DOM 未保留其 JS，不能只靠表单断言两个按钮参数完全相同。
- 本机 GET `https://ss.zhizhen.com/s` 收到 302，目标 `https://login.zhizhen.com/findlogin.jsp?backurl={原搜索地址}`；没有跟随或登录。是否受学校 IP、CARSI 或专用订购访问影响尚未检验。
- 首页读秀标签保留 `sw` 与 `channel=goqw.jsp/search/searchJour/searchNP/searchThesis/searchCP/searchEBook`，DOM 上表单 action 仍是馆站首页；真实跳转依赖未取得的官网 JS，不可把这个 action 当成读秀 API。

### CALIS/e 读：公开元数据已实测

这是一条 **全国高校资源检索** 来源，不能替代汕大 OPAC 的在架状态或本人借阅。官网原表单：GET `http://www.yidu.edu.cn/510400/search.html?q={关键词}`。本机 301 到 `https://yidu.calis.edu.cn/510400/search.html`；当前 SPA 脚本明确处理 `q` 和学校/机构 `orgCode=510400`，并转搜索结果页。

实际 API 根：`https://yidu.calis.edu.cn/prod-api/yidu`。只发送了下面公开读取；没有认证、收藏、保存检索式、文献传递、试读或全文接口请求。

| 请求 | 真实响应 |
| --- | --- |
| GET `/resource/getSelectCriteria` | 200，`{msg,code:200,data:{search,searchType}}` |
| POST `/resource/query` | 已按页面代码的只读检索调用发送；200，`{msg,code:200,data:{total,maxTotal,show,analysis,highlighting,content}}` |

查询请求 JSON 已从实际脚本调用推导并验证：

```json
{
  "offset": 1,
  "limit": 5,
  "sort": null,
  "orgCode": "510400",
  "exp": [{"field":"title","value":"数据结构","label":"数据结构","relation":"0","op":"0","resource":"0","typeNew":"0-2"}],
  "facet": [],
  "searchJson": "{页面用于恢复条件的 condition/secondCondition/searchType JSON 字符串}",
  "refresh": ""
}
```

`searchJson` 在本轮请求中是完整有效 JSON，示例为缩短展示。题名查询返回 `total=8304,maxTotal=2000,content` 5 条；`offset=2,limit=5` 同样 5 条，与第一页 `ukey` 无重叠。其分页控件把 `offset` 当当前页，不能按名称误解成从第几条开始的 SQL offset。一个不可能匹配的字面题名检查返回 `code=200,total=0,content=[]`，其余 envelope 字段仍存在。

公开记录字段因资源类型而异：`ukey,schemacode,realdbid,dbid,score,quote`，并常见 `string_title,string_creator,string_publisher,string_publishyear,string_ISBN,multivalued_type,multivalued_holding,string_source`。**第一页已有 2/5 行没有 `string_UUID`**，所以不能把它强制当所有记录的主键；不能要求所有类型都有作者/ISBN。`multivalued_holding` 属全国联合馆藏来源，未经映射不能解释成汕大可借。题名匹配也会分词，不能把本轮“数据结构”理解为精确短语检索。

静态定义另有：GET `/resource/getInfo`、`/resource/getBookLibInfo`、`/resource/getJnlCollect`、`/resource/getJournalYVIList`、`/resource/related`；POST `/resource/queryFacet`、`/resource/dissertation/query`、`/resource/getArticleList`、`/resource/findServices`。这些详情/扩展查询尚未发送。收藏、保存检索、全文/试读和馆际互借均单列为未执行，不能由匿名搜索可用推断可自动使用。

前端以 `Authorization` 或 `IP-Authorization` 处理受限功能，且搜索代码存在 `code=504` 的挑战分支。本轮无挑战，**不代表以后任何网络/检索频率都无挑战**；未尝试生成/规避验证码。

## 6. 失物招领附属入口

官网发布的 HTTP `/3rdmana/lost/index/` 本机匿名 200，标题“图书馆失物招领”，服务端 HTML 18669 字节。表单 `method=get`、无显式 action（当前路径）、字段 `q`，占位“搜索...”。页面仅引用同目录的公共 jQuery 和 `ebox001.semantic.js`，未见内联网络调用。

本轮只保存页面哈希、表单和脚本结构，未保存物品照片、联系人或明细。查询结果、分页、详情链接和认领动作还没有取证，不能称失物招领全部接口已掌握。

## 7. 医学院图书馆补查

医学院图书馆[HTTP 首页](http://lib.med.stu.edu.cn/)本机匿名 200，标题“汕头大学医学院图书馆”，58506 字节；有 2026-10-13 等公开通知、新书推荐和馆藏地/索书号。它是独立的公开官网内容来源，但**本轮没有发现它发布独立医学院 OPAC 域名或单独的读者认证表单**。

只跟进该首页真实给出的 4 个目标：

| 页面实际发布的目标 | 本轮协议与响应 | 已知功能/不能推断的事 |
| --- | --- | --- |
| `http://lib.med.stu.edu.cn/dblist.aspx?id=1` | HTTP 200，标题“医学类数据库” | 公开 HTML 列出 15 个 `/dbdetail.aspx?id={已发布ID}` 详情链接；ClinicalKey、JoVE、Medline、CBM、FMRS 等是目录名称，未访问资源正文或验证订购权限 |
| `http://lib.med.stu.edu.cn/libdetail.aspx?id=12` | HTTP 200，标题“校外访问” | 官网说明包含 CARSI 和医学院 VPN 两种路径；说明可读不等于这两条登录已跑通 |
| `http://opac.lib.stu.edu.cn/opac.php?type=login&page=reader` | HTTP 200，1442 字节，标题“自动跳转页面”，与本页第 1 节 OPAC 壳页哈希相同 | “网上借阅服务”和“我的图书馆”使用这条旧参数别名；没有取得登录表单或本人借阅接口，不能宣称医学院独立读者登录已验证 |
| `https://yxy.med.stu.edu.cn/`（首页标“研讨室预约”） | 正常 TLS，302 `/quicklink.html`，再 200，标题“快捷导航 - 汕头大学医学院融合门户” | 实际到的是公开门户导航，未到图书馆研讨室时段/申请表；不可直接等同于主校 newic |

医学资源页还有已发布类别 `id=2/3/4/5`（综合/试用/免费/自建），本轮仅取 `id=1`，未遍历其他类别或详情。未见这个页面声明 JSON API 或专门分页，不能据此保证所有类别都一页返回。

### 首页静态搜索与读者别名

- 馆藏检索：GET `http://opac.lib.stu.edu.cn/opac.php`，表单字段 `type`、`any`；隐藏值没有保存，也没有发查询。它与主校 OPAC 的入口相同，不代表所有馆藏集合/账号权限完全相同。
- 读者入口：`opac.php?type=login&page=reader`；新书通报为 `opac.php?page=newbook`，读者指引为 `opac.php?page=guide`。后两条仅记录发布关系，没有重复请求。
- 全国高校馆藏：静态 GET `http://www.yidu.edu.cn/search.html?sf=all4reader&embedded=1`，字段 `q` 与 `db=0/1/2/3/4`。这和主校首页的 `/510400/search.html` 路径不同，本轮未把它们强行归为同一机构筛选范围，也未发送搜索。
- 读秀和百度学术是另外的外站表单，分别声明 `sw`、`wd`；本轮未跟进外部检索。

### 认证与网络条件要按路径分别判断

1. 医学院[校外访问说明](http://lib.med.stu.edu.cn/libdetail.aspx?id=12)的 CARSI 段明确写“学校校园网账号（汕大的账号）”，实际发布的 Elsevier、Wiley、Springer、Web of Science 等链接仍使用 `https://idp-lib.stu.edu.cn/idp/shibboleth`。这是官网身份指引和同一 IdP 的发布证据，**未发送账号或检验资源授权**。
2. 同一说明另一段列 `https://vpn.med.stu.edu.cn/`、预先激活地址 `http://register.med.stu.edu.cn/vpn/` 及客户端安装说明。这是医学院 VPN 的文档路线，不能用已有主校 WebVPN 会话代替。文档含旧客户端/操作系统说明，未据此保证当前服务器、平台兼容性或账号权限；没有访问激活、安装或 VPN 登录。
3. “研讨室预约”去到的融合门户公开展示 `https://sso.med.stu.edu.cn/cas/login?service=https%3A%2F%2Fyxy.med.stu.edu.cn%2Flogin`，与主校 SSO 地址不同；本轮只读其链接，没有跟进 CAS。门户另列 OA 的“会议室预约”，但没有证据证明它就是图书馆研讨室原业务，不将两者合并。

所以不能只按“医学院”或 `lib.med` 主机把所有功能指定为同一种登录：官网内容匿名可读；读者页指主校 OPAC；CARSI 指主校图书馆 IdP；医学院门户显示自己的 CAS；VPN 另有独立路径。本人实际可用范围仍需分别验证。

### 补查证据

逐请求记录在忽略目录的 `med-library-*.json/html`，新证据已加入 `evidence-manifest.json`。首页 SHA256 `6f0d488621d6db49d66e6e0db3eec57c40a02e7999259da67d3cc25a48bab460`；医学类目录 `4cfdd917d86edb5c8da1b1fc78e2c30a0aabf3460a5cd93ff7629be3f9575d04`；校外说明 `86076a9f74a302b3213b45009eaddec0953db62acf99b300862e52595ec2427b`；门户 `/quicklink.html` `89e2fd661775b326ddcc6492dca5c02e53375cb4ee9b34b615d9071ec2dca5ca`。

待补证：医学院实际读者账号与主校 OPAC 的覆盖关系、医学馆藏检索/本人借阅接口、独立预约系统的现行直达地址与只读时段/资格、各资源授权及医学院 VPN 当前认证协议。本轮不因官网首页可读而声称这些业务已验证。

## 可复查的证据清单

| 证据 | 位置/哈希 |
| --- | --- |
| 本机逐请求摘要 | 忽略目录下 `opac-*.json`、`space-*.json`、`carsi-idp-*.json`、`search-*.json`；每条有 UTC、输入路径、路由和响应/异常 |
| 远端官方读取来源元数据 | `remote-retrieval-metadata.json`，列明 8 个官网 URL、scrapeId、远端状态及缓存信息 |
| 资源表单与字段 | `remote-page-analysis.json`，含全部筛选选项、130 条公开目录行、表单/链接 |
| newic 配置 | `/newic/config/config.js` SHA256 `4225c3d3ec50844ec68c5dd154c81bfe188e5ad1f92df7c9ca9cc81ca112c40d` |
| newic 公共函数 | `/newic/js/chunk-common_1785736178197.js` SHA256 `ce50e113a2c402eaec33cd1e8eb416184f48e4a365aacda417195ff1ee4b7b76` |
| newic 本人记录/路由 | `/newic/js/index_1785736178197.js` SHA256 `366377f7313a21259586ead3f7ae8be743c8bcd45fc490149d81980db2e21072` |
| newic 普通空间调用点 | `/newic/js/chunk-7d007ac2_1785736178197.js` SHA256 `1321a7b31c06b2fa4e4ec7488d62f7bf3a036c3a5d72b6b38add095a5ff9230f` |
| newic 座位 API 定义 | `/newic/js/chunk-eda463a6_1785736178197.js` SHA256 `02e628585808d3888a3d53a68a9738768201c611b68ac480c105cca46d0b1624` |
| newic 图形挑战组件 | `/newic/js/chunk-c98f7d46_1785736178197.js` SHA256 `eaa097c48c4e3ce69b4eb7f53971f08ecfc63e0cab8f5303e332ecdcf39b8be9` |
| CALIS 当前主脚本 | `/assets/index.2c3f9c91.js` SHA256 `356c05d9a97e037849659f9ab6368f006e03c62ee260b885c22fabc9aa883c2d` |
| CALIS 查询 API 定义 | `/assets/filter.8f23d8e8.js` SHA256 `a7cc39427a98f155e30674875155864aaaae46f5d181e5250917edc10c82feb9` |
| CALIS 搜索参数/分页/字段 | `/assets/index.04b9b099.js` SHA256 `5521f91a8b21a956717dd07c94b931b62439a25da1316dcd39c6640d8df41d06` |
| CALIS 实读 | `calis-read-checks.json`、`calis-paging-empty.json`、`calis-paging-identities.json`；公开参数、envelope、分页与空态 |

`space-contracts.json` 还记录从已下载 bundle 直接提取的 **102 个去重 method/path 定义**及来源文件/字符位置。它是静态定义集合，不是 102 个已验证或当前开放的学校功能；辅助函数命中的泛化管理请求也不纳入可用性结论。

## 仍须补的证据

1. OPAC 正常业务 JS/检索结果，或学校确认其现行替代入口；不能仅靠 200 跳转壳继续设计。
2. 数据库目录在本机正常 TLS 下的读取路径；远端可读只用于本次调查佐证。错误状态、未来分页和非 CNKI 详情结构仍待抽查。
3. newic 的本人独立身份、`roomMenu/seatMenu` 实际清单，以及真实房间/座位只读响应的分页、日期/校区语义和空态；不得用公共 activityMenu 的 3 个类别代替。
4. newic SSO 的最终链及业务 Cookie 边界；本轮未提交账号，不能声称已验证纯 HTTP 首次登录。
5. CARSI 的本人认证、挑战分支和各资源 SP 权限；公开元数据不能证明订购权限。
6. 超星/读秀登录和实际检索、失物招领查询/分页细节；CALIS 详情和学校馆藏映射。

这些缺口分别需要正常服务响应或后续本人认证取证。本轮不把网络失败、静态接口发现和真实业务验证合并成“全部摸清”。


## 附录：newic 静态 method/path 清单

下列均来自当天公开 bundle，除正文匿名实测表外没有请求。它保留编译包中的候选定义；不代表本校启用、当前用户有权使用，GET 也不自动视为无副作用。所有路径共用 `/ic-web` 根。

```text
GET /account/getMembers
GET /account/info
GET /activity/custom/resvInfo
GET /activity/resvInfo
GET /activityMenu
GET /activityReview
GET /api/psg/sign/rec
GET /auth/address
GET /auth/bind/address
GET /auth/userInfo
GET /auth/webapp
GET /borrow/device/resvDevInfo
GET /borrow/reserve/own
GET /borrowMenu
GET /checkLog/checkInfo
GET /codingTable/getAll
GET /creditConversionRec/limitNum
GET /creditPunishRec/surPlus
GET /creditRec/getOwn
GET /creditStarRec/own
GET /devCoding/theme/details
GET /devKind/labDevKinds
GET /device/tips
GET /digitalReadingRoomMenu
GET /feedback/open
GET /feedback/own
GET /home/page/room/idle
GET /lab/devKindLabs
GET /login/manager
GET /login/publicKey
GET /news
GET /news/questions
GET /oauth/address
GET /oauth/unionId
GET /openApi/seat/reserveInfo
GET /pad/GetCtrlRoomInfoS
GET /pad/picture
GET /pad/updateTime
GET /photomanager/banner
GET /psgLeaveRec/rec
GET /psgLeaveRec/reserves
GET /psgSeat/open
GET /psgSeat/resvInfo
GET /psgSeatMenu
GET /psgSignRec/viewDefaultRec
GET /reserve
GET /reserve/areaInfo
GET /reserve/count
GET /reserve/endList
GET /reserve/entrance
GET /reserve/operate/rec
GET /reserve/punishInfo
GET /reserve/resvInfo
GET /reserve/seatArea
GET /reserve/time/expand/duration
GET /resvVisitVolunteer/own
GET /room/openTimes
GET /roomDevice/roomInfos
GET /roomMenu
GET /seat/common/use
GET /seatDevice/resvStatus
GET /seatDevice/tempLeave
GET /seatLockRec/ownLockRec
GET /seatMenu
GET /seatRoom/open
GET /seatRoom/openScope
GET /sysConfig/public
GET /sysInfo
GET /sysInfo/help
POST /account/password
POST /account/update
POST /account/updatePss
POST /activity/custom/delete
POST /activityReview/saveOrUpdate
POST /captcha/check
POST /captcha/get
POST /creditConversionRec
POST /digitalReadingPcRoom/coordinate
POST /feedback/save
POST /feedback/user/read
POST /login/bind
POST /login/bind/user
POST /login/signOut
POST /login/user
POST /psgLeaveRec/cancel
POST /psgLeaveRec/leave
POST /reserve
POST /reserve/bulkAdd
POST /reserve/delete
POST /reserve/endAhaed
POST /reserve/endReserve
POST /reserve/entrance/save
POST /reserve/quickResv
POST /reserve/seat
POST /reserve/time/expand
POST /reserve/update
POST /resvMember/operate
POST /resvVisitVolunteer/cancel
POST /seatDevice/coordinate
POST /seatDevice/mcoordinate
POST /seatLockRec/unlock
POST /seatOperation/tempLeave
```
