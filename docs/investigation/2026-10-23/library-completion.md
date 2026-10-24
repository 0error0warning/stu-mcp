# 图书馆剩余业务补查：公开馆藏、读者、空间与资源

本报告补充 [library.md](library.md)，只做协议调查，没有修改或接入 MCP。此前 OPAC“壳页可读、主要脚本返回跳转”的观察仍属实，但不能继续扩大成“没有可用馆藏接口”：本轮沿页面实际发布的移动端入口、脚本和动态配置，已经读到公开分类、分页书目和具体馆藏。

本机实际请求时间为 **2026-10-23 15:57:15–16:16:10 UTC**，即北京时间 **10 月 23 日 23:57:15–10 月 24 日 00:16:10**。CARSI 本人认证补证由 root 的独立临时 HTTP 会话完成，时间为 **16:08:33.611562 UTC**。文档整理、脚本解包和哈希计算的时间不算新联网核查时间。

本机均为 `httpx`、`trust_env=False`、正常 TLS 校验，连接 5 秒、读取 9 秒、顺序有界请求，不修改网络设置。HTTP 仅用于学校实际发布的公开地址和这些页面派生的匿名查询，不给 HTTP 发送学校密码，不复用其他业务或浏览器的 Cookie。没有续借、预约、荐购、论文上传、评价、绑定或资料修改，也没有读取借阅人名单。

## 1. 本轮结论与访问边界

| 业务 | 本轮实际证据 | 仍未证明的部分 |
| --- | --- | --- |
| OPAC 公开馆藏 | JSON POST 分类树、偏移分页、二段书目详情、馆藏册和状态可匿名读取 | 旧 `b1` 文字检索总数大于零却返回空 `content`，不能据此交付完整检索；未验证筛选后所有组合 |
| 本人读者业务 | 当前动态配置确实启用借阅、预约、收藏、荐购等入口；读接口和两种登录路线已定位 | 未完成本人 OPAC 认证，不能用匿名初始化的 `uid` 当登录证明 |
| newic 空间 | 公开 FAQ 8 条、通知显式空数组；公开菜单；认证路线已追到中央 SSO | 空间、空闲、预约查询当前要求业务登录；官方回调为 HTTP，HTTPS 当前证书链校验失败，未发送认证票据 |
| CARSI | 正常 HTTPS、纯 HTTP 客户端已通过中央认证，走到实际“信息释放”同意页 | 没有代用户同意属性释放，没有发送 SAMLResponse，没有证明 CNKI 资源授权 |
| CALIS e读 | 图书/期刊/学位论文查询、详情、馆藏机构、卷期、期刊文章、分面及同导师论文均有匿名响应 | 不是汕大 OPAC 库存，不证明全文、文献传递或个人收藏权限 |
| 汕大学位论文 | 官方指引分别给出检索站和论文提交站，两者均实际请求 | 检索站 HTTP 500；提交站 HTTP 502；未获得可用认证或查询接口 |
| 医学院图书馆 | 其余四类资源目录、相关检索/论文检测指引可匿名读取 | 商业数据库订阅权限、独立医学院门户认证、研讨室实际接口未验证 |
| 失物招领 | 正常 GET 搜索以及无匹配页面已验证 | 未抓取证件、人名、照片、联系方式；未验证逐条详情和翻页 |

本机 `https://www.lib.stu.edu.cn/zy/database` 仍因证书过期失败；`https://app.lib.stu.edu.cn/newic/` 仍为 `unable to get local issuer certificate`；`https://opac.lib.stu.edu.cn/h5/apps/login1/index.html` 为连接拒绝。三者不能合并成“校园网络不可用”，也不能因某个 HTTP 入口能读而关闭 TLS 校验。

`http://www.lib.stu.edu.cn/` 和旧 `/dbExplorer.aspx` 本轮均 301 到各自 HTTPS 地址；没有取得 `dbExplorer.aspx` 的正常页面，也没有证据断言它已迁移到 `/zy/database`。

## 2. OPAC：公开馆藏的实际协议

### 2.1 从跳转脚本继续找到可读的应用

[`/web/index.html?type=reader`](http://opac.lib.stu.edu.cn/web/index.html?type=reader) 仍是 1,495 字节壳；其 `app.648cf6409785e459abb3.js` 仍是相同的 178 字节跳转脚本。沿脚本声明的 [`/h5/index.html`](http://opac.lib.stu.edu.cn/h5/index.html)，再沿实际引用的 `extra.js`，找到：

- [`/h5/apps/opac/index.html`](http://opac.lib.stu.edu.cn/h5/apps/opac/index.html)：图书检索，主脚本及其 4 个路由分块均可读。
- [`/h5/apps/readerCenter/index.html`](http://opac.lib.stu.edu.cn/h5/apps/readerCenter/index.html)：读者中心外壳。
- 当前配置进一步指向 [`/h5/apps/readerCenterApps/index.html`](http://opac.lib.stu.edu.cn/h5/apps/readerCenterApps/index.html) 的 `#/loan`、`#/order`、`#/collection`、`#/info`。
- [`/h5/apps/login/index.html`](http://opac.lib.stu.edu.cn/h5/apps/login/index.html) 和其实际链接的 [`login1/index.html`](http://opac.lib.stu.edu.cn/h5/apps/login1/index.html)：读者证与 MySTU 登录路线。

`initialConfigParent.3.3.js` 是跳转响应，但 **同一登录页明确引用的 `initialConfigParent.3.1.js` 是完整 SDK**。这是实际链接派生的检查，不是猜文件名。完整 SDK 明确默认 POST、`application/json`、`JSON.stringify`，按容器维护临时 TID；读取方要解析正文，不能仅按响应 MIME 判断：这些 JSON 经常标成 `text/html;charset=utf-8`。

### 2.2 匿名初始化、动态配置与真实启用项

本轮直接读 `/rest` 的首次独立客户端得到 `success=false, code=redirect, err=/index.html`；不带初始化上下文的配置请求得到 `need session`。按页面已声明的初始化后跑通：

1. `GET /init?container=controlcenter` → `success=true, tid, obj:{uid,tids[]}`。
2. 同一匿名客户端 `GET /rest` → `success=true, tid, obj:{tenant,uid,tids[]}`。
3. SDK 将本次匿名返回的 `tenant/uid` 和本容器 TID 用于后续请求；没有借用既有用户会话。
4. `POST /` JSON：`container=controlcenter, component=beans, service=takePersonalise, namespace=app, item, tenant, uid, tid`。

实际读取 `item=opacConfig` 与 `Flyread_h5_index_config` 均成功；`obj` 是 **JSON 字符串**，需再解析一次。TID、匿名 UID 和 Cookie 值没有落盘。初始化成功不等于读者已登录；本轮 `GET /isLogin?container=controlcenter&component=beans` 明确返回 `success=false, code=login`。

当前搜索配置实际给出：

- 字段 `ANY/TITLE/AUTHOR/SUBJECT/PUBLISHER/CLC/ISBN/ISSN/CALL_NO/DONOR`。
- 馆藏地：桑浦山校区图书馆、东海岸校区图书馆、特色文献室、汕医图书馆、CILL、文学院资料室及“全部”。这是配置值，未逐馆筛选实测。
- 文献类型：图书、非书资料、期刊、报纸；排序 `DEFAULT_DESC/PUBDATE_ASC/PUBDATE_DESC`。
- 借阅、预约、收藏、读者资料、荐购等当前菜单；`opac_v3`、微阅读和一个外部帮助链接标记为隐藏，不能按脚本打包内容宣称启用。

编译包包含多家图书馆的模板及旧默认值，不能把其中的 `sdu` 模板当作汕大当前设置；本报告使用上述运行时公开配置判断实际菜单。

### 2.3 已实测的公开查询

基址为 `http://opac.lib.stu.edu.cn`，以下均为 **POST JSON**，没有认证凭据。

| 方法/路径 | 请求体关键字段 | 实际响应与边界 |
| --- | --- | --- |
| `POST /opac` 分类树 | `query:{type:"classify",source:"book",facet:["nclc"],condition:[{field:"clc",keyword:""}]}` | `success=true, data:{id,type,nclc[]}`；22 个分类；行 `facet,id,level,subCnt,total` |
| `POST /opac` 分类书目 | `query:{type:"classify_data",source:"book",facet:["nclc"],condition:[{field:"clc",keyword:""}],limit:{offset,rows}}` | `success=true, data:{id,type,total,opacs:[{ctrlNo}]}`；`offset=0/5,rows=5` 各 5 条、CTRLNO 无交集；本轮 `total=1070496`，只是该接口报告值，不是实体馆藏册数 |
| `POST /lcsbehavior` 二段书目 | `container:"lcsbehavior",component:"opac",service:"queryBookInfo",obj:{tenant,ctrlnos:[实际分类返回的CTRLNO]}` | `success=true,obj[]`，5 条完整书目。缺少上述匿名初始化/tenant 的前一次为 `query book assets failed`，不能误记成该接口恒不可用 |
| `POST /lcsbehavior` 馆藏 | 相同容器，`service:"queryBookAssetByCtrlNo",obj:{tenant,ctrlnos:[实际CTRLNO],detail:false}` | `success=true,obj[]`；单条书目包含 3 个 `assets`，未请求借阅人信息 |
| `POST /opac` 旧文字检索 | `query:{type:"b1",source:"book",condition:{TITLE:"数据结构"},pagination:{page,pageSize,pageCount},sort:{DEFAULT:"DESC"},tag:{}}` | 原移动端契约的 `page=1/2` 均回 `currPage` 对应值、`totalSize=1154`，**`content=[]`**；按原页 `pageSize=10,pageCount=10` 及正常匿名初始化后仍如此，原因未确诊 |
| `POST /opac` 无匹配检索 | 同上，仅换不匹配的字面标题 | `totalSize=0,content=[]`。这才是已证实的无匹配样例；不能把上一行的异常当空结果 |
| `POST /opac` 分面 | `query:{type:"b2",source:"book",condition:{TITLE:"数据结构"},sort:{DEFAULT:"DESC"},tag:{}}` | `data:{size,tagContent,type,id,hashid}`；`tagContent` 有 `DISK/LANGUAGE/ORGNIZATION/PUBLISHER/PUBYEAR/TYPE` 数组。注意 **ORGNIZATION** 的实际拼写 |

二段书目行包括 `ctrlNo,isbn,isbnValue,title,author,titleAuthorInfo,publocale,publisher,pubdate,ubsn,clc,lccsa,language,medium,edition,series,subject,cover,journalFlag,containCD,collectionCnt,unlendableCnt,lendCnt,summary,catalog,preview,callNos,authors` 等。馆藏 `assets[]` 的实际字段包括 `price,barcode,callNo,assetId,status,orgId,orgName,bookType,bookTag,assetNo,yearVal,yearNo,yearNoVal,shelfNo`。

`b1/b2` 的 `success` 本轮是字符串 `"true"`；分类和二段详情是 JSON 布尔值。不能用“非空字符串都成功”通吃。错误体还可能是 `{success:false,code,err,tid}`。本轮把查询对象改成表单字符串的对照仅得到 `query args not json struct parse error`，不作为可用契约；最初误用 `currentPage` 的试探亦不作为分页证据，已按原脚本 `page` 更正。

未实测但已定位的公开读候选：同 `/opac` 的 `b3` 联想（`suggest:{tag,text,size}`）、`b4` 热词，及 `/lcsbehavior` 的 `querySchema`（`hot_loan/hot_favorite/hot_click/new_up_book`，`obj:{tenant,schema,timeScope,type}`）。本轮没有为补齐数量而执行全部分支。

### 2.4 本人读者登录与只读接口：静态合约，不冒称已读

MySTU 分支的页面实际协议为：

1. 登录入口 GET `/third/grant`，参数名 `rand,state,container`；实测返回 `{success,tid,obj:{code,state}}`。临时值只留内存。
2. 页面构造 HTTPS 中央 SSO，`service` 为 **HTTP** `/h5/apps/login1/login.html`，携带 `container,code,rand`。
3. 回调页把原回调查询和同一个 `service` 交给 GET `/ssolocal`；其代码以 `success && obj.uid` 再跳回首页。

这不是现有 MySTU 会话已经可用于 OPAC 的证据。OPAC HTTPS 当前拒连；本轮停在匿名协议，不发送中央票据到这个 HTTP 回调，也不把 JW 的历史兼容授权套过来。

独立读者证分支先 GET `/login?container=controlcenter` 取得 RSA 公钥，再调用 `/verify?container=controlcenter&component=beans`，字段 `memType,loginType,loginValue,passwd`；密码由官方 `JSEncrypt` 加密。这里只读了页面，没取私人证件、没猜默认密码、没发送验证请求。

以下来自当前实际引用的 `readerCenterApps` JS，**未调用本人读接口，未验证其登录后响应**：

| 读取目的 | 路径/关键请求字段 | 前端读取的结果 |
| --- | --- | --- |
| 本人信息 | `POST /lcs1`，`SERVICE_ID:[0,1,0]` | `success,data` |
| 当前借阅 | `POST /lcs1`，`SERVICE_ID:[13,10,1000]`，`loanStatus:["lent"],offset,rows,orderSort:"ASC",orderType:"due_time"` | `success,data` |
| 历史借阅 | 同服务，`loanStatus:["normal_retu","expire_retu","damage_retu","exp_dam_retu","lost_retu"]`，按 `return_time` | `success,data` |
| 借阅 v2 | `POST /lcsbehavior`，`service:"getReaderLendAsset"`，相同状态/分页放在 `obj`，`tenant` 属本业务 | `success,obj`，`rows` 在该分支转字符串 |
| 当前/历史预约 | `POST /lcs1`，`SERVICE_ID:[13,10,1010]`，`resvStatus` 分别为 `wait/ready/wait1` 或 `cancel/expire/lent`，`offset,rows` | `success,data` |
| 个人收藏 | `POST /lcsbehavior`，`service:"queryFavorite"`，`obj:{tenant,type:"book"或"shelf"或"case",offset,size}` | `success,obj`，图书另取二段书目 |

续借 `[13,10,1060]`、预约/取消、收藏写入、挂失、停用、密码/资料修改均只有静态证据，**没有执行**。个人成功判据至少要结合真实业务登录检查与当前本人只读资料，不能拿匿名 `uid`、CAS 302 或 HTTP 200 代替。

荐购页的当前前端走 `POST /lcs2`，`container:"recommendation",component:"detail"`，读取 `search-1.0`，提交 `recommendation-1.0`；也打包了 MARC/Z39.50 与用户搜索分支。这里只取公开脚本，不调用用户搜索、不荐购。书展移动页则直接读取公开 `data/data.js`：3 个展览条目，日期为 2022 年；它不等于实时书展 API，也不等于潮汕特藏库。

## 3. newic：公开读与认证边界补齐

基址 `http://app.lib.stu.edu.cn/ic-web`；`/newic/` 只是前端目录，不能错误拼成 `/newic/ic-web`。

| 实际匿名 GET | 本轮结果 |
| --- | --- |
| `/auth/userInfo` | HTTP 200，`code=300,data=null`，未登录 |
| `/activityMenu` | `code=0`，3 类；沿用原报告的研修间、东海岸研讨室、静音舱，行有 `kindId/kindName/kindClass/kindProp` 等 |
| `/news` | `code=0,data=[],count=0`，显式空列表 |
| `/news/questions` | `code=0,data[8],count=8`，`sid,title,content,kind,status,sort,top,gmtCreate/gmtModified` 等字段；不是 8 个可预约空间 |
| `/sysInfo` | 不带参数时 `code=1`，请求参数缺失；没有把它记成不存在或空公告 |
| `/sysInfo/help`、`/roomDevice/roomInfos`、`/home/page/room/idle` | 均 `code=300`，不能当无房间/无帮助内容 |
| `/reserve` | 按公开菜单真实 `kindId=1`，`sysKind=8,resvDates=20261024,page=1,pageSize=10` 查询，仍 `code=300`；没有预约写入 |

FAQ 的 `content` 是正文 HTML，原前端还会对文本做转换；正式适配前需要用真实内容验证转换规则，不能只见字段名就断言正文已可直接展示。当前没有登录后的空间行、完整规则、空闲时段或本人预约响应证据。

本轮进一步追了真实 `/auth/address` 返回地址：`GET /auth/address?finalAddress={官方HTTP前端}&manager=false&consoleType=16` → `code=0`，给出 `/newic/authcenter/toLoginPage` → 302 HTTPS 中央 SSO；其 `service` 是 HTTP `/newic/authcenter/doAuth/{临时不透明路径}`。没有导出路径随机值、令牌或 Cookie，没有继续认证。此前示例 `/newic/ic-web//auth/token` 是返回地址模板的一部分，不能当作已经跑通的业务 API 基址。

当前阻碍具体是：HTTPS 校验失败，发布的业务认证回调却为 HTTP；需要修复学校证书链或另行明确评估这一来源的传输兼容，不能关校验、借 JW 授权或断言“学校要求浏览器”。

## 4. CARSI：已到首次属性释放同意

本机匿名沿[官网 CNKI SP 地址](https://fsso.cnki.net/Shibboleth.sso/Login?entityID=https%3A%2F%2Fidp-lib.stu.edu.cn%2Fidp%2Fshibboleth&target=https%3A%2F%2Ffsso.cnki.net%2Fsecure%2Fdefault.aspx)实测：SP → `idp-lib.stu.edu.cn/idp/profile/SAML2/Redirect/SSO` → `/idp/Authn/ExtCas` → HTTPS 学校 SSO。SAMLRequest、RelayState、execution 和 conversation 只作临时流程状态，不写进通用配置。

root 后续使用独立 IdP/SP 临时业务 jar、中央 SSO 独立 jar，在 **16:08:33.611562 UTC** 完成中央认证并返回 IdP，得到 HTTP 200、标题 **“信息释放”**，表头 **“将向服务机构提供如下信息:”**。实际表单是 POST 当前 IdP 路径，字段名为 `_shib_idp_consentIds`、`_shib_idp_consentOptions`，按钮 `_eventId_AttributeReleaseRejected` 与 `_eventId_proceed`。

**当前止点是用户尚未决定属性释放同意，不是 HTTP 技术失败或必须用浏览器。** 没有代选同意/拒绝，没有提交该表单，没有发送 SAMLResponse；没有证明 CNKI secure 页面或任何资源的授权。其他 SP 的订阅和属性要求仍不能由 CNKI 这次链路推广。

对应安全摘要：忽略目录 `output/campus-protocol-survey/entry-completion/observations.jsonl`，`source=carsi,op=read,checked_at_utc=2026-10-23T16:08:33.611562+00:00`。只引用该条，未复制任何凭据或断言包含个人会话的材料可发布。

## 5. CALIS e读：补齐各类查询与字段差异

入口沿 [CALIS e读](https://yidu.calis.edu.cn/510400/search.html)；接口基址 `https://yidu.calis.edu.cn/prod-api/yidu`。本轮 16 次查询都为匿名 HTTP 200、业务 `code=200`，无浏览器或账号。这里的馆藏机构是联合目录数据，不能当本校可借册数。

主查询仍为 `POST /resource/query` JSON：`offset,limit,sort,exp[],facet[],searchJson,orgCode,refresh`。`orgCode=510400`；`offset` 的页语义由前轮独立分页实测确认。本轮 `limit=5`，标题分别“数据结构/图书”“计算机/期刊”“机器学习/学位论文”；资源类别来自 `/resource/getSelectCriteria` 的 `28/1/2`，`typeNew` 与原前端拼接规则对应 `28-2/1-2/2-2`。`searchJson` 是包含 `condition,secondCondition,searchType` 的 JSON **字符串**，不能直接换成对象。

| 已实测方法/路径 | 参数来源与字段 | 实际结果 |
| --- | --- | --- |
| `POST /resource/query` | 如上；`exp` 的 `field,value,label,relation,op,resource,typeNew` | 图书总数 1971、期刊 141、学位论文 365，均 5 条；只是所用标题与类别的当次匹配数 |
| `GET /resource/getInfo` | 对当次真实结果传 `ukey,type=schemacode` | 三种资源详情成功，`data:{show[],concat[]}`；每次 `concat` 1 条 |
| `GET /resource/getBookLibInfo` | 当次图书的 `ukey` | `data:[{code,name}]`，1 个机构；未推断为 STU 可借库存 |
| `GET /resource/related` | 同详情 `ukey,type` | `data:{total:0,content:[]}`，已验证相关资源空态 |
| `POST /resource/queryFacet` | 与该次主查询同一个 JSON 请求体 | `data.facet[6]`，行 `code,name,count,childNodeList,tree` |
| `GET /resource/getJnlCollect` | 实际期刊 `ukey` | `data.eLibrarys=[]`；本样本没有 `pLibrarys` 键，不能把缺键当非法响应 |
| `GET /resource/getJournalYVIList` | 实际期刊 `string_UUID` 作为 `uuid` | `data[10]`；行 `pyear,mapData[]`，子项 `year,volume,issue` |
| `POST /resource/getArticleList` | 该期刊 UUID 与上述真实卷期，`limit,offset,journal_uuid,publishyear,volume,issue` | `data:{total:6,maxTotal:2000,concat:[5]}`；是文章元数据，没下载文章 |
| `POST /resource/dissertation/query` | 真实学位论文详情的 `ukey,schemacode,contributorsearch=string_contributorsearch,grantor=string_grantor`，加 `offset,limit` | `data:{total:1,maxTotal:2000,conent:[1]}`；**conent 拼写原样如此** |
| `POST /resource/findServices` | 实际期刊 `uuids:[ukey],services:["coverImage","lholdings"]` | `code=200,data={}`，已验证空映射；没有请求 `fulltext` 服务或跟进资源 URL |

响应顶层 `{msg,code,data}`；列表字段分别有 `content/concat/conent`，不同接口不可硬合并。详情 `show` 指示字段展示，不能强制每种资源都有相同属性。期刊文章含 `string_journal_UUID/string_journal_title/string_volume/string_issue`；学位论文详情多出 `string_grantor/string_degree/string_contributorsearch`；图书详情有 ISBN/分类/出版等。

原前端有 `code=504` 人工挑战、`429/502` 等错误分支；本轮未触发，不能声明无需挑战。没有试读 PDF、全文、收藏、检索历史保存、文献传递或资源下载。

## 6. 学位论文检索与提交是两个地址

这两页因本机主馆 HTTPS 证书过期，采用 **远端 Firecrawl** 读取官方指引，明确设置 `maxAge=0,skipTlsVerification=false`，工具回执 `statusCode=200,proxyUsed=basic`。不是本机直连成功，也不能由工具成功推断本机 TLS 没问题。

| 官方指引 | 实际发布的目标 | 本机匿名结果 |
| --- | --- | --- |
| [汕头大学学位论文数据库](https://www.lib.stu.edu.cn/database/297) | `http://192.168.64.114/Usp/apabi_usp/?pid=own.search&dt=TASIMETA400&db=dlib&dbtype=1&cult=CN` | **HTTP 500 Runtime Error**，未取得检索表/脚本；只请求官网明确给出的该地址，未扫描内网 |
| [学位论文电子版在线提交注意事项](https://www.lib.stu.edu.cn/article-554.html) | `http://app.lib.stu.edu.cn/tasi/paper_post` | **HTTP 502 Bad Gateway**，未取得认证表单 |

指南说明前者收集本校学位论文，部分早期记录仅文摘；后者接收最终论文 PDF、后续可查看审核状态，身份数据由研究生管理部门导入。网页说明不能替代当前认证成功或接口契约。没有上传、验证毕业生身份、输入身份证信息或联系管理员。

## 7. 医学院资源、失物招领与读秀

### 医学院公开目录

前轮已读 `dblist.aspx?id=1` 医学类；本轮沿既有公开菜单补齐：

| GET 页面 | 标题/目录功能 | 当前公开详情链接数量 |
| --- | --- | --- |
| `http://lib.med.stu.edu.cn/dblist.aspx?id=2` | 综合类数据库 | 21 |
| 同路径 `id=3` | 试用数据库 | 30 |
| 同路径 `id=4` | 免费数据库 | 7 |
| 同路径 `id=5` | 自建数据库 | 1 |

均 HTTP 200、HTML 链接列表，条目链接是 `dbdetail.aspx?id={页面给出的ID}`；没有把 ID 做连续枚举。它们不是 JSON 资源授权接口，未发现这些页面自身的分页契约。详情抽查实际发布的 `id=187/34/102`，分别是潮汕文献、CNKI 博士论文、读秀；可读数据库简介及“在线访问”链接，不证明订阅或个人可下载。

潮汕文献详情的目标是 [`http://cstc.lib.stu.edu.cn/`](http://cstc.lib.stu.edu.cn/)，本轮读取超时，未继续重刷；没有发现可验证的检索接口。它与主馆 OPAC 的静态书展不是同一业务。

`libdetail.aspx?id=15` 的当前页面标题为“大学生论文检测”，菜单却标“学位论文检测”；说明线下表格与邮件处理，不能包装成论文查询接口。`id=11` 的外文论文检测页明确写 iThenticate 服务暂停、恢复另行通知；`id=13` 文献收录/引用/发表检索页说明委托单及邮件办理。只读指引，不发送邮件或申请。

医学院“网上借阅/我的图书馆”仍链接主校 OPAC；当前 OPAC 搜索配置也确含“汕医图书馆”。这可证明入口/过滤关系，不能推断医学院所有服务都接受主校账号。前轮研讨室链接 `yxy.med.stu.edu.cn` 只取得门户，实际预约与独立 `sso.med.stu.edu.cn` 认证仍未验证；没有向它发送主校凭据。

### 读秀与失物招领

医学院读秀详情发布 `http://www.duxiu.com/`，本轮匿名链为 HTTP 首页 → HTTP `/login.jsp` → HTTPS `/login.jsp` → `/passportoauth/openauth.jsp` → `passport2.chaoxing.com/api/checklogin`。停在最后这个重定向，未发账号、未调用手机号/用户搜索、未跟进临时签名参数；不能称为已验证机构资源检索。与原报告的 `ss.zhizhen.com` 登录重定向分别记录，不能相互替代。

失物招领 [`http://app.lib.stu.edu.cn/3rdmana/lost/index/`](http://app.lib.stu.edu.cn/3rdmana/lost/index/) 的 GET 表单字段为 `q`。用不匹配字面词只读查询得到 HTTP 200、6,049 字节正常页面：保留类别与认领说明、没有物品结果；没有额外“无结果”文案。没有导出含证件或联系方式的列表、图片和详情。

## 8. 可复核证据与后续仍缺的证据

忽略目录 `output/library-completion/` 保存本轮安全元数据及公开 JS，没有账号、密码、Cookie、CAS 票据、SAMLResponse、借阅人或私人借阅记录。

- `observations.jsonl`：普通匿名请求时间、脱敏路径、状态、长度、哈希、表单字段名和响应形状；临时授权参数及嵌套 URL 均省略。
- `opac-reads.json`、`opac-asset-reads.json`、`opac-pagination-summary.json`：正常匿名初始化后的配置/二段馆藏与分页；无实际匿名 UID/TID 值。
- `calis-reads.json`、`calis-extra-reads.json`：上述 16 次匿名 CALIS 读，保存响应形状而非全文或个人资料。
- `remote-dissertation-guide.json`、`remote-thesis-submission-guide.json`：远端官方指引来源及回执；其中落盘时间是工具调用后本地记录时间，不冒充服务器取数时间。
- `evidence-manifest.json`：证据文件与公开脚本的 SHA-256；`opac-h5-unbundled.js` 等是本地解包分析物，来源哈希另列，不能当成新的服务器资源。

关键公开脚本来源及哈希：

| 原始公开脚本 | SHA-256 |
| --- | --- |
| OPAC `/static/js/initialConfigParent.3.1.js` | `b32e9aeb92bd456e6c1baee2591939f4b5bc3c95ddb0c51a01a15719879d2bed` |
| OPAC `/h5/apps/opac/js/main.2fcb82f9425c0d24058b.js` | `94c134ebe3a0f5613143d4df81d02384d9f925a8ee04514770a8f7b8b4ed0223` |
| OPAC `/h5/apps/readerCenterApps/js/main.66ebabd08c0a82192872.js` | `544c0be8e9f8af11dbe1ba03c4f02e7d56483b1cf9aed2290046b1f4a7021ebd` |
| OPAC `/h5/apps/bookDetail/umi.3256bc09.js` | `ecff70c4076e1a9ab9c52bfa90342c8dc46fadad66db2c865efdb9e6034de6a7` |
| CALIS `/assets/index.ebf50ebd.js` | `9f0e866ea7d67bd7163bdb9bfe4921edbfa48172655e5e6ec949c852c7efcfc2` |

还缺的具体证据：旧 `b1` 正常文字检索为何缺行及其可用新版替代合约；OPAC 本人认证后只读空态/分页；newic 可校验的认证传输和登录后空间/规则；CARSI 用户本人是否授权属性释放及 SP 资源证明；两个学位论文站的正常响应；潮汕特藏当前检索协议；医学院门户实际预约入口及独立身份；各商业资源实际订阅边界。本报告没有把静态接口、指南描述、远端页面读取或匿名初始化写成这些业务已经接入、可用或认证成功。
