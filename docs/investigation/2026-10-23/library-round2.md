# 图书馆、正版软件与校园卡第二轮协议复核

本轮补齐前次的具体缺口，没有接入 MCP。**OPAC 的公开文字检索已跑通：任意字段查询、
ISBN、二段书目、馆藏与末页均有实际响应；此前异常应收窄为已测题名查询，不再概括为
“文字检索不可用”。正版软件 ms 本轮独立 HTTPS CAS 也已建立业务登录态。**

自己的实际请求为 **2026-10-23 16:58:23–17:45:29 UTC**，即北京时间 **10 月 24 日
00:58:23–01:45:29**；公开榜单、空间联系方式与校园卡公告于 17:35 后补查。ms 认证补证由
root 管理的独立临时 HTTP 会话完成，时间另列。
静态脚本解析、CSV/摘要写入和本地比较时间均不冒充新联网时间。

使用 `httpx`、`trust_env=False`、正常 TLS 校验与短超时；匿名各业务独立 jar，初始化值只留
当前业务内存。不修改代理/DNS/证书，不借中央或其他来源 cookie。只提交明确的公开查询
JSON 或原站公开公告检索表单；没有续借、预约、荐购、验证码识别/发送、软件承诺书提交、下载、激活或外部授权。
`r` 和综测本轮没有请求。

## 1. OPAC：公开文字检索与二段读取已取得正向证据

来源为当前实际发布的[移动检索页](http://opac.lib.stu.edu.cn/h5/apps/opac/index.html)和该页
引用的 `/h5/apps/opac/js/main.2fcb82f9425c0d24058b.js`。17 点前后重新读取页面及脚本，
后者 SHA-256 仍为
`94c134ebe3a0f5613143d4df81d02384d9f925a8ee04514770a8f7b8b4ed0223`。
初始调查器误取的 `/h5/apps/search/index.html` 返回 HTTP 200、正文却是 `404 page not found`；
该路径不是可用入口，不作为发现或成功证据，随后已改用页面实际发布的 `opac` 路径。

### 实际查询合同

匿名初始化仍是同一客户端 `GET /init?container=controlcenter` → `GET /rest`。
从本次响应取本业务匿名 `tenant/uid`，不把它们当本人读者身份。
文字查询为 `POST http://opac.lib.stu.edu.cn/opac`，JSON：

```json
{
  "query": {
    "type": "b1",
    "source": "book",
    "condition": {"ANY": "数据结构"},
    "pagination": {"page": 1, "pageSize": 20, "pageCount": 10},
    "sort": {"DEFAULT": "DESC"},
    "tag": {}
  }
}
```

`pageSize=20,pageCount=10` 来自当前脚本桌面查询分支的默认值；移动分支也明确传
`page/pageSize/pageCount`。不是把另一业务的分页参数套在这里。

| 本轮实际读取 | 结果 | 证据限制 |
| --- | --- | --- |
| `b1`，`ANY=数据结构`，页 1、2 | 各 20 个 `content[].CTRLNO`；`currPage=1/2,totalSize=1171` | 两页 40 个 ID 不重复，不代表全库只有这些条目 |
| 页 1 的实际 ID → `POST /lcsbehavior`，`service=queryBookInfo` | `success=true,obj[20]`；返回 ID 集合与请求完全相等，20 个题名均含关键词 | 书目字段沿用前报告；没有取读者、借阅人或全文 |
| 首个实际结果 → `queryBookAssetByCtrlNo`，`detail=false` | `success=true,obj[1]`，含实际 `assets[]` | 公开可借库存，不是本人的借阅记录 |
| 用分类二段结果中的真实 ISBN 作 `b1.condition.ISBN` | `totalSize=1,content[1]` | 只验证该实际样本，不推广所有 ISBN 格式 |
| 按当前总数推导末页 59 | `currPage=59,totalSize=1171,content[11]` | `1171 - 58×20 = 11`，末页数量吻合 |
| 末页后的页 60 | `currPage=60,totalSize=1171,content=[]` | 这是超过正常结果范围的空页，仍有匹配总数 |
| `ANY=stu-mcp-protocol-no-match-20261023` | `totalSize=0,content=[]` | 合成无匹配字面词，正常空结果 |

二段请求仍是 `POST /lcsbehavior`，
`{container:"lcsbehavior",component:"opac",service:"queryBookInfo",obj:{tenant,ctrlnos:[实际ID]}}`；
馆藏只换 `service` 并加 `detail:false`。实际结果没有落盘书目正文，只留字段结构、数量、哈希
及 ID 集合比较布尔值。第一段的 `CTRLNO` 大写、第二段的 `ctrlNo` 小写不能混用。

### 题名异常尚未确诊，但已排除“全部检索不通”和错误二段假设

同一匿名初始化、同一个 JSON 合同，`TITLE=数据结构` 仍返回字符串 `success:"true"`、
`totalSize=1154,content=[]`；把实际结果的题名作为题名字段再次查询仍观察到空行。
不能将这种“有总数、正常页却无行”的情况当作无匹配，也不能自动用 `ANY` 替换用户指定的
题名检索而不说明语义变化。仅凭这些响应还不能确诊后端索引、缓存或取行的具体故障。

当前脚本 `searchListH5/searchList` 明确先取 `content[].CTRLNO`，再调用二段书目；
若第一段没有 ID，它不会再凭总数调用隐藏的补行接口，甚至把面向界面的总数改成 0。
因此前报告看到的空行发生在第一段，不能归因于本轮尚未执行二段书目。

另检查既有 SDK `/static/js/initialConfigParent.3.1.js` 的请求分组：无 `container` 的
`/opac` 进入默认 `lcs1` 组，该组 `needTid=false`。`controlcenter` 才走 `/rest` 的队列
`tid` 维护。没有证据支持“所有 b1 失败都是漏传控制中心 tid”的猜测；没有为了猜测而重放
跨容器状态。

补齐两个前次仅静态声明的读分支：

- `POST /opac`，`query:{type:"b3",source:"book",suggest:{tag:"TITLE",text:"数据结构",size:10}}`
  → 布尔 `success=true,data.suggestContent[10]`，元素为字符串。
- `POST /opac`，`query:{type:"b4",source:"book",condition:{TITLE:"10"}}`
  → 布尔 `success=true,data.content=[]`。只是这个公开热词样本的空结果，不是没有馆藏。

`b1` 继续返回字符串 `"true"`；初始化、二段详情、`b3/b4` 是 JSON 布尔值。
正式适配不能以“非空字符串都成功”处理所有分支。

### 公开排行榜：四种 schema 与实际二段详情

此前只静态声明的读者导览榜单于 **17:35:07–17:35:10 UTC** 补查。先按已取得的官方
`readerGuide` 脚本读取配置：`POST /`，`container=controlcenter,component=beans,
service=takePersonalise`，顶层字段使用当前匿名 `tenant`、`uid=tenant`、`namespace=app`、
`item=readerGuide.json`，以及本次匿名 `/rest` 取得的本业务 `tid`。响应布尔 `success=true`，
`obj` 为 JSON 字符串；配置实际提供时间选项 7/15/30/90/180/365 天，默认 7 天，分类默认
空字符串（全部）。这里的匿名 tenant 值不是个人读者 UID。

随后 `POST /lcsbehavior`：`container=lcsbehavior,component=opac,service=querySchema`，
`obj:{tenant,schema,timeScope:7,type:null}`，实际结果：

| 官方 schema | 本轮公开书目 ID 数 | 从该结果取前 5 个 ID 的二段结果 |
| --- | --- | --- |
| `hot_loan` | 100 | `queryBookInfo` 成功返回 5 条 |
| `hot_favorite` | 75 | 成功返回 5 条 |
| `hot_click` | 100 | 成功返回 5 条 |
| `new_up_book` | 97 | 成功返回 5 条 |

均为布尔成功值和 `obj[]`；计数是这个时间/分类样本的返回量，不是全库总数，未观察到此
榜单请求的分页合同。没有取借阅人的身份或记录。脚本来自前轮已真实读取的
`/h5/apps/readerGuide/js/main.3a01bbd317e725b8c046.js`，SHA-256
`421242b92c07a2910f2d49dfe161707c3fb1b1c0d761a7df86188eee93feb615`；本轮配置与接口
请求是新请求，脚本引用/解析不冒称重新下载。安全数量摘要为 `more-public-summary.json`。

## 2. OPAC 本人读者与 newic：传输边界仍需来源级处理

本轮没有给 HTTP 发送中央票据、学校密码或读者证密码。以下均为匿名读或 TLS 诊断，
不是“登录后发现无权限”的证据。

| 检查 | 当前实际结果 | 不能推断的结论 |
| --- | --- | --- |
| `https://opac.lib.stu.edu.cn/h5/apps/opac/index.html` | 17:02:16 UTC，`ConnectError`，底层为连接拒绝 | 不代表 HTTP 的公开检索不可用，也不证明本人账号无效 |
| `https://app.lib.stu.edu.cn/newic/` | 17:02:16 UTC，`ConnectError`，底层证书校验失败 | 未绕过校验，不能以可达 TCP 代替可信 HTTPS |
| `http://app.lib.stu.edu.cn/newic/` 与其实际 `config/config.js` | 200；当前仍 `ApiUrl:'/ic-web',loginMode:2` | 模板中其他学校注释不当作汕大功能启用证据 |
| `GET /ic-web/auth/address`，原页 `finalAddress`、`manager=false,consoleType=16` | `code=0`，地址为 HTTP `/newic/authcenter/toLoginPage` | 不是已拿到本人资源列表 |
| 原样 GET 上述同业务临时地址 | 17:01:01 UTC，302 至 HTTPS 学校 SSO；`service` 仍是 HTTP `/newic/authcenter/doAuth/{临时段}` | 未跟认证回调；临时段未保存为固定接口 |

前轮 MySTU 分支的 OPAC 回调仍只有已发布的 HTTP `login1/login.html` 合同；独立读者证分支
需要本业务读者身份。已查官方图书馆首页、入口配置和有限官方站点检索，未取得可直接替代
上述路径、且能正常验证 TLS 的官方 HTTPS 登录入口。检索没有命中不是“全校不存在”的证明。

来源级传输兼容还没有完成评估；不能套用 JW 的既有 HTTP 授权，也不能改 service、关闭证书
校验或先发票据再说。本轮没有本人借阅、预约、空间资源、空闲时段或规则的成功响应，因此
这些仍未验证；阻碍描述应是具体入口/传输与独立身份条件，不能写成“学校要求浏览器”。

### newic 公共联系方式：精确参数的正常空态

**17:35:11.084862 UTC**，沿学生端已发布 `space-48240e66.js` 的 `getInfo()` 参数实际读取：

`GET http://app.lib.stu.edu.cn/ic-web/sysInfo?sysType=16&sysKind=8&status=2&sysValue=0`

响应 HTTP 200、`code=0,data=null`，另有整型 `count` 与空 `vals`。原静态 Axios wrapper 是
`get(e,i)`，其 `i.params` 对应这里四个直接查询参数，不是再包一层 `params` 的字符串。
这是学生页公共联系信息的正常空态，补正前次漏参试验，不能说整个 `sysInfo` 被拒绝。
它也不是场地规则或空闲接口；学生端 `roomInfo.resvRule` 的实际字段与本人资源仍未获取。
没有沿管理端规则路由或猜空间/座位 ID。

## 3. CARSI：保持真实本人同意边界

本轮没有重新请求 CARSI。沿用前轮 **2026-10-23T16:08:33.611562Z** 的成功认证证据：
独立 IdP/SP jar 经中央 CAS 后到达 IdP“信息释放”表单。用户尚未决定属性释放；没有代选
`_eventId_proceed` 或 `_eventId_AttributeReleaseRejected`，没有发 SAMLResponse。

这是已观察到的人类授权决定，不能笼统写“未尝试认证”，也不能把它当浏览器依赖。
CNKI secure 授权及其他 SP 的订阅仍未证明。精确表单字段与安全摘要来源见
[前轮 CARSI 证据](library-completion.md#4-carsi已到首次属性释放同意)。

## 4. 正版软件 ms：本轮 CAS 已建会话，WPS 另行判断

### 公开目录与本地登录入口

此前只静态记录的分类请求已实际补查：

| 官方实际链接及跳转 | 本轮结果 |
| --- | --- |
| `/soft/?categoryid=7` → 同站 `/soft?categoryid=7` | 301 后 200，5 个不同软件详情目标 |
| `/soft/?categoryid=13` → 同站 `/soft?categoryid=13` | 301 后 200，2 个不同软件详情目标 |
| `/soft/detail/45` | 200，题名 WPS Office For Windows；软件版本/大小的标签存在，本样本值为空 |
| `/login?logintype=2` | 200，本地账号密码表，不是 CAS 回调后的自动完成接口 |

分类页本样本未发布 `page=` 或 `page/` 分页链接，不能推广为后台永远不分页。
详情页另有 `POST /soft/download` 和软件使用承诺书界面，没有提交表单或下载。

`logintype=2` 的实际表单 `POST /login`，字段 `username/password`，`onsubmit=encrypt()`；
当前函数将密码作 Base64 编码。没有向这个本地表发送学校密码，也没有因为函数名/注释中
出现 MD5 就误写成加密算法。登录页另有通用旧验证脚本，不能用它代替真实表单绑定。

### 本轮独立 HTTPS CAS 成功，不继续沿用旧回环结论

root 于 **2026-10-23T17:02:57.469400Z** 从官方固定 HTTPS `/login` 取得新票据并在独立
ms jar 回调，实际链是 `/login` 302 → 同站根页 200。页面无密码表、出现 `/logout` 入口，
而匿名页面是 `/login`。中央 jar 没有复制给业务，记录只留 cookie 名/域/路径等元数据。

因此当前已取得 ms 业务登录态的正向证据，前轮 15:11 的回环仅保留为历史失败；不能再将
整个软件平台归为“当前认证阻断”。本页没有直接匹配到预期账号文本，不把退出链接推广成
账号资料字段已绑定、所有下载/激活权限已验收或 WPS 文档已获授权。
本轮再访问 `/login` 仍可重新发起 CAS，它是登录发起入口，不是有效的被动会话探针；
不能仅凭这一跳再次把根页已有的登录正向证据改判成失效。
root **17:05:53.888994 UTC** 再 GET 根页仍为 200，正文 SHA-256 与认证后成功根页相同，
再次保留了退出入口；这是后续实际业务复读，不是前次响应的本地解析。

安全摘要位于 root 的忽略文件 `output/campus-protocol-survey/round2/observations.jsonl`，
`source=ms,op=auth`。后续会话复读若有新结果，按新时间追加，不能用旧失败覆盖成功。

### WPS：官方链最终给出的 service 仍为 HTTP

本轮匿名新客户端按实际 302 顺序只读至学校认证发起页：

1. HTTPS `ms.stu.edu.cn/wps` → HTTPS `open.wps.cn/oauth/v1/auth`；参数名 `app_id/cb`。
2. WPS 返回 HTTPS `ms.stu.edu.cn/loginwps`；参数名 `client_id/redirect_url/state`。
   后续目标结构是 `account.wps.cn/permit/ssoafterlogin.html`，不是已取得文档权限。
3. **17:02:20.176960 UTC**，学校 `/loginwps` 302 到 HTTPS 中央 SSO，实际 `service` 却为
   **`http://ms.stu.edu.cn/loginwps`**。本轮在此停止，没有向它发送票据。

因此之前“只看到外部 OAuth 第一跳”可以补充为“先回学校，再发起学校 CAS”；仍不能说
WPS 本人授权已完成，更不能用 ms 的 HTTPS `/login` 会话把这个独立回调替换掉。
没有从本轮页面拿到需要用户同意的授权表，不能凭经验称当前已卡在外部同意页。

[官方 WPS 指南](https://ms.stu.edu.cn/help/detail/821) 本轮 200、标注更新于 2024-08-29：
说明学校 SSO、设备授信及可选手机/微信绑定。它是产品操作指引，不能覆盖本次实测的 HTTP
service，也不能用来证明当前客户端激活或个人订阅。没有打开客户端、提交承诺、申请权限、
绑定设备、手机号、微信或读取用户文档。

## 5. 校园卡：精确表单和身份适用条件已核对，不拿 CAS 密码代替

本轮当前[登录页](http://smartcard.stu.edu.cn/homeLogin.action) 200，表单 `method=post`、
`onsubmit="return doSummit();"`，校验成功后 JS 把 action 设为 `loginstudent.action`。

| 字段/提交条件 | 当前页面明确内容 | 边界 |
| --- | --- | --- |
| `name` | 登录标识 | 没有枚举账号或试探别人的标识 |
| `loginType` | `2` 学(工)号、`1` 帐号、`3` 手机号 | 账号类型 1 的 JS 约束为 1–20 个数字；不能将此约束自动套给另两种 |
| `passwd` | 密码输入、`maxlength=6`；JS 要求长度正好 6 | 页面未证明查询密码与学校 CAS 密码相同 |
| `rand` | 验证码输入、`maxlength=4`，非空检查 | 图片由 `getCheckpic.action?rand={随机值}` 生成；没有识别、破解或提交 |
| `userType` | 固定隐藏值 `1` | 是当前公开表单配置，不是本人身份已确认 |
| `imageField` | 图片提交按钮 | 标准图片按钮可能带坐标字段；服务端是否必需未用登录 POST 验证 |

[官方 FAQ](http://smartcard.stu.edu.cn/managerOneGgxxfb.action?fbxxid=4a401f3d363cedfa01363d08581d0001)
本轮 200；发布时间标签为 2012 年，不能当作全部 2026 年账号策略。指引区分正式卡与访客卡，
正式卡可用学工号/卡号，访客卡用卡号，并将查询密码、消费密码分别说明。当前页面又新增
手机号类型，但未说明绑定条件，因此没有把 FAQ 的老截图或说明扩展成所有现行账号规则。

这里的密码指**校园一卡通的查询密码**，用于该站余额、交易记录等查询；官方说明将其与刷卡消费密码分别定义，不能用学校统一认证密码或 WebVPN 动态口令代替。2026-10-24 01:25 UTC 再次匿名核对，登录页和该 FAQ 均返回 200，仍未执行本人登录，也未试用旧说明中的初始密码规则。

本人余额/流水需要实际有效的独立卡查询凭据、用户完成当前图片验证，以及可接受的来源级
传输路径。本轮没有输入独立密码或向 HTTP 发凭据，**没有执行登录 POST**，故没有上游
“拒绝此账号”的证据，也不能报告“该用户没有校园卡”或“系统无法纯 HTTP 登录”。
未确认的部分是具体本人适用性、登录成功判据、余额/流水的实际字段、日期范围和分页。
公开检索/公告已在前报告跑通；不读取失卡/寻卡个人名单，不挂失、充值、改密或发验证码。

### 校园卡公开公告：GBK 查询有结果，分页尚有具体不一致

公开公告表与个人登录分开。本轮在不登录的客户端用原公开字段执行
`POST http://smartcard.stu.edu.cn/xxsearch.action`，表单键为
`searchnotices/searchtype/lmid`，`searchtype=1` 为题名、`2` 为内容，`lmid=all`。
原页 `Content-Type` 为 GBK；用 GB18030 URL 编码发送中文，解析时按 GB18030 解码：

- **17:36:31.337861 UTC**，题名词“一卡通”：200，页摘要“共 2 页、第 1 页”，当前页
  17 个不同的公开 `fbxxid` 详情目标。
- **17:36:31.535810 UTC**，内容词“查询密码”：200，“共 1 页、第 1 页”，3 个详情目标。
- **17:45:11.301011 UTC** 重取原题名查询，隐藏检索词与本次字面词精确相等，仍为 17 个
  详情目标、2 页。只留数量/结构，没有存公告列表正文、失卡或寻卡名单。

此前 UTF8 表单和只找 `a[href]` 的解析会遗漏实际写在 `onclick` 中的详情，不能把那个
零计数当作正常无匹配。本轮已明确纠正编码及链接提取口径。

公开 `/js/page.js` 于 **17:44:46.359443 UTC** GET 200，SHA-256
`20f45f557ecd39808ad04fbb56e0052cfba3bb3a41cc2370004746e32ea8a88c`；
`locatePage()` 修改 `form.pageno` 后执行 `pageHandle`。本页实际 `pageHandle=doQuery()`；
**17:45:29.465079 UTC** 的原页内联函数明确把 action 设为
`ggxxfb.action?lmid=` 加当前 URL 的 `lmid`，然后正常提交。页面未指定 form method，浏览器
默认 GET；隐藏字段为 `searchnotices/searchtype/lmid/pageno`。

本轮保留原表单隐藏字段，把 `pageno` 改为 2，GET 原 form 的 `ggxxfb.action` 目标。
**17:45:11.550164/17:45:11.621174 UTC**，GB18030 与 UTF8 查询编码均返回 200，但摘要
成为“共 1 页、第 2 页”、详情目标为 0。这是已观察到的检索分页不一致，不能把它当作
正常末页，也不能声称两页已经完整取齐。没有进一步猜隐藏接口、改私有会话或重复试错。
表单 action 可能带匿名 URL 重写会话段，发送时仅在该匿名客户端内保留；摘要只留固定
路径和已省略标记，不把临时会话值当固定 URL。日志工具后续保留原公开查询编码；早先
UTF8 重序列化产生的替换字符属于日志表示，不能用于推断当时请求的真实字节。

证据分别为 `card-public-pagination-structure.json`、`card-paging-proof.json` 和请求回执。
这里的公开公告可读性与个人校园卡密码、验证码、余额或流水没有相互证明关系。

## 6. 证据与本轮完成边界

忽略目录 `output/campus-protocol-survey/round2/library/` 保存安全摘要、公开脚本和官方说明：

- `observations.jsonl`：请求时间、方法、脱敏 URL、状态、长度/哈希、响应形状、计数和错误阶段。
- `opac-pagination-proof.json`：两页 ID 去重、二段 ID 集合对应和题名包含词的布尔/数量证明。
- `opac-lastpage-proof.json`：按真实总数计算的末页与越界空页、无匹配样本。
- `smartcard-form-safe.json`、`public-controls-summary.json`、`final-configuration-checks.json`：
  仅公开字段、静态配置、官方入口结构，不含真实输入、密码、验证码或临时授权值。
- `evidence-manifest.json`：公开文件及安全摘要的本地 SHA-256；源请求时间另在回执中。

临时 OAuth/state/嵌套回调和不透明 doAuth 段只在内存使用；落盘摘要已省略这些值。
自己所有 HTTP 客户端均已关闭。root 的 ms 会话生命周期由 root 收尾，不能据子任务完成
声称已替 root 清除了它的内存。

可据实推进的公开合同是 OPAC 任意字段/ISBN 搜索及分页二段、四类书目榜单、
newic 公共联系方式空态、校园卡公告检索，以及 ms 目录/分类/详情；
ms 已有本轮业务登录正向证据。仍需来源级处理的是 OPAC/newic/WPS 的认证传输，CARSI
本人决定，以及校园卡的独立凭据/图形输入和本人读合同。题名搜索异常保留具体响应，不
扩成“整个图书馆接口坏了”。以上均为调查，没有改变既有工具接口、配置或产品支持状态。
