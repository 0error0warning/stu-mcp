# 学生就业、宣讲会与职位：匿名 HTTP 补查

日期：2026-10-23，**15:03:42–15:09:50 UTC**（北京时间 23:03:42–23:09:50）。本轮接续[学生就业入口初查](other-business.md#学生就业-gdc)，只研究 `gdc.stu.edu.cn` 的公开读取协议，**没有接入 MCP**，没有修改工具、认证白名单、产品代码或配置。

使用全新匿名 `httpx` 客户端，`trust_env=False`、正常 TLS 校验、连接 5 秒/读取 8 秒、正文 2 MB 上限及流读取时间检查；不自动跟随重定向，不重试。共 **30 次 GET、23 个不同 URL**，29 次 HTTP 200、1 次 302，达到预算后停止。没有 POST、学校/就业账号登录、注册、验证码请求、报名、投递简历、收藏、举报或退出操作。没有改变代理、DNS、hosts、证书或网络；忽略环境代理不证明绕开系统 TUN，也不推断校园/校外位置。

只保存安全请求元数据、结构/字段名、计数、公开业务 ID 和四份公开 JS。未保存原始 HTML/JSON、Cookie、反伪造值、个人联系信息或任何学生名单；页面内公开联系人的实际值也没有提取或记录。忽略目录为 `output/campus-protocol-survey/employment-followup/`，其中 `requests.jsonl` 是逐请求证据，`observations.jsonl` 是结构观察，`derived-checks.json` 是仅本地比较结果。

## 1. 已实测的读取入口

| 方法与精确路径 | 本轮真实结果 | 适配边界 |
| --- | --- | --- |
| GET [首页](https://gdc.stu.edu.cn/) | 200，公开职位、企业、宣讲会及日历链接 | 学生就业站；公开入口不证明本人就业手续或简历可读 |
| GET [`/JobFair/GetDiaryJobFair?month=2026.10`](https://gdc.stu.edu.cn/JobFair/GetDiaryJobFair?month=2026.10) | 200 JSON，`Code=0,Total=28,Data` 28 项 | 本月日历索引；本次全部 28 项 `Title/Place` 为 `null`，不能因此丢弃活动 |
| GET [`/Home/get_event_data?month=2026.10&day=23`](https://gdc.stu.edu.cn/Home/get_event_data?month=2026.10&day=23) | 200 JSON，`Code=0,Total=1,Data` 1 项，标题/地点为字符串 | 当天详情补充；`day` 来自日历格，`month` 来自当前月份文本 |
| GET [`/Home/get_event_data?month=2026.10&day=1`](https://gdc.stu.edu.cn/Home/get_event_data?month=2026.10&day=1) | 200 JSON，`Code=0,Total=0,Data=[]` | 月历未列出该日期后，按同一公开日期参数核实的**正常空态**，不是请求失败 |
| GET [`/Home/get_index_job?edu=60`](https://gdc.stu.edu.cn/Home/get_index_job?edu=60) | 200 JSON，**顶层裸数组，16 项** | 首页“本科以上”数据值 60；没有 `Code/Data` 包装或分页证明，不是全部职位接口 |
| GET [`/Home/get_index_jobfair?type=1`](https://gdc.stu.edu.cn/Home/get_index_jobfair?type=1) | 200 JSON，**顶层裸数组，6 项** | 首页“宣讲会”控件的 type=1；与日历包装不同，也不代表全量宣讲 |
| GET [`/JobFair/InnerTalk`](https://gdc.stu.edu.cn/JobFair/InnerTalk)、`/JobFair/InnerTalk/2`、`/JobFair/InnerTalk/3` | 200 服务端 HTML；第 2/3 页各 20 个 `.articleitem`，两页公开宣讲 ID 无重叠；显示共 43 页 | 已验证有限的分页推进，未读取全部 43 页 |
| GET [`/Search/SearchJob`](https://gdc.stu.edu.cn/Search/SearchJob)、`?pageindex=2`、`?pageindex=50` | 200 HTML；三个请求的 10 个公开职位 ID 集合相同，详见第 3 节 | 页面分页链接不等于实际推进；不能声称已经支持完整分页 |
| GET [`/Search/SearchJob?pageindex=1&educationlevel=60`](https://gdc.stu.edu.cn/Search/SearchJob?pageindex=1&educationlevel=60) | 200 HTML、10 个职位，身份集合相对默认列表发生变化 | 证明本次学历筛选能影响结果，不证明其他全部筛选组合 |
| GET [`/JobFair/CareerTalk?id=5486`](https://gdc.stu.edu.cn/JobFair/CareerTalk?id=5486)、[`/Job/27166`](https://gdc.stu.edu.cn/Job/27166)、[`/Ent/12288`](https://gdc.stu.edu.cn/Ent/12288) | 三个首页已发布目标均 200 HTML | 宣讲介绍、职位与企业详情是不同路径；只抽查这些公开 ID，不遍历或探测其他 ID |

## 2. JSON 合同与字段差异

月历与当日日历的外层实际为：

```text
Code:int, Msg:str, ExtMsg:null, Total:int,
PageIndex:int, PageSize:int, PageCount:int, Data:list
```

本次 `Code=0`；月历、当天与空态的 `PageIndex/PageSize` 都为 0，`PageCount=1`，不能据字段名认定它们支持常规分页。条目字段实见 `JobFairId:int,Day:int,Date:str,Title:str|null,Place:str|null,ShowDate:str,Type:int,IsOuter:int,SchoolArea:null`。`SchoolArea` 本次为空，不能据此推定校区。

`index.js` 的公开分支把 `Type=1/4` 链到 `CareerTalk`，`Type=2/3` 链到 `DualOption`；这是客户端分支，不是完整业务枚举证明。月份接口的空标题/地点应通过原生日历交互补取当天信息，不能用字符串强转、标题哈希或页面标签替代 `JobFairId`。`Date/ShowDate` 与数字 `Day` 分开保留；官方脚本有 `/Date(...)/` 解析函数，未在本轮确定所有日期字段的时区合同，不按 MCP 宿主时区重解释。

首页职位接口的 16 项裸数组至少观察到这些字段：

```text
Id, Name, EntId, EntName, Logo,
IndustryCode, ShowIndustry, Property, Scale, DepartmentId,
MinMoney, MaxMoney, Money, EducationLevel, EducationLevelText,
UpdateTime, WorkCity, WorkCityCode, CategoryId, JobKind, Category,
Status, StatusText, EntStatus, PageView, CreateTime,
FailMsg, CheckMember, CheckTime
```

抽样中 `Id/EntId` 为整数，`Name/EntName/Money/EducationLevelText/WorkCity` 为字符串，`Logo/ShowIndustry/Property/Scale` 可为 `null`。只保留字段名与类型，未记录 `CheckMember` 等审核字段的值；未来适配应白名单选择用户所需的公开职位信息，不透传整份对象。薪资文本 `Money` 和 `MinMoney/MaxMoney` 不自动合并成同一保证薪资，也不由 `Status` 数字推断岗位仍可投递。

首页宣讲接口的 6 项裸数组与日历条目使用相同一组字段；本次六项标题、地点均为字符串。顶层数组与 `Code/Data` 包装必须分别识别，不能强套一份信封解析器或把未知外层转换为空列表。

## 3. 职位列表：已验证筛选，分页与空态有阻碍

搜索页原生链接发布 `pageindex`、`jobkind`、`educationlevel` 和 `sort`：工作性质包括全职/兼职/实习，学历值包括 `0/50/60/70/80`，页面对应不限/大专以上/本科以上/硕士以上/博士以上；排序链接为 `updatetime/maxmoney`。本次仅实际验证 `educationlevel=60`，其他选项仍是发布合同。

`SearchJob.js` 的搜索按钮构造 GET `/Search/SearchJob?pageindex=1`，另声明 `keyword,jobKind,city,educationLevel,jobCategory,minMoney,maxMoney`。字段大小写按原声明记录，不能据静态代码保证所有参数组合都生效。城市与职位分类来自选择器，未取得完整合法代码表，不猜编码。脚本对 `jobKind`、`educationLevel` 的长度判断写成 **`lenght`**，且关键词用旧 `escape()`；这些是本次脚本事实，不是已经执行和验证过的前端交互。

**分页阻碍**：按页面实际给出的 `?pageindex=2` 与尾页 `?pageindex=50` 读取，公开职位集合与默认页相同。15:09:50 UTC 再读尾页时 `.Pager .Current` 实际仍为 **1**，虽仍显示“共 50 页”。不能把页码参数已发送、HTML 200 或尾页链接存在当作翻页成功，更不能计算 50×10 个职位。本轮没有猜其他参数名或继续翻页，原因仍未确定。

**不能当空结果的样本**：按已声明的 `keyword` 输入不可能匹配的 ASCII 字面词 `STU_NO_MATCH_20261023`，真实 GET 返回 **302 到同站 `/Home/Error`**；另取该实际跳转目标返回 200 HTML。没有正常列表或零结果合同，不能报“0 个职位”，也不能误判为登录过期。没有加入 SQL、脚本或特殊字符测试。

## 4. 宣讲列表、正常空态与详情

宣讲列表使用路径分页 `/JobFair/InnerTalk/{页}`，不是职位搜索的 query 分页。结果在 `.articleitem`，详情地址由该元素的 `onclick` 发布，例如 `window.location.href='/JobFair/CareerTalk?id=...'`；只提取 `<a href>` 会漏掉列表记录。`.Pager .Current` 在第 2 页实为 2，页 2/3 的各 20 个身份无重叠，本轮只证明这一段分页。

列表内联搜索代码从 `#innerkey` 取词，构造 `/JobFair/InnerTalk/1/{关键词}`。同一 ASCII 无匹配词的真实请求返回 200、正确“宣讲会”标题、`.articleitem=0` 且没有 `.Pager`，与职位搜索的错误跳转不同；这是本轮可确认的**正常 HTML 空态**。

抽查的宣讲详情公开可读，页面含宣讲介绍和岗位要求；职位详情使用 `.EntInfoBox`，可见 `.JobName/.Money/.Tag/.JobContent` 等结构，以及发布时间、职位描述/诱惑、企业性质/行业/规模和联系方式标签。仅记录字段/结构，不保存招聘联系人实际值。企业详情 `/Ent/{ID}` 与职位 `/Job/{ID}` 分别可读，不能把企业 ID、职位 ID 与 `JobFairId` 混为同一身份。详情机器字段的完整对应、截止/撤回状态与更多详情样本仍待补证。

## 5. 独立认证及写入边界：仅静态声明

本轮没有认证。公开 `Main` 脚本声明学生邮箱与用人单位手机是两个站内分支：

| 方法/路径 | 静态字段与效果 | 本轮行为 |
| --- | --- | --- |
| POST `/Login/StudentLogin` | `StuEmail,Password,ValidCode,Key,IV`；客户端加密后发送，成功分支 `Code==0` | 未发送账号、密码或验证码；不能认定可复用学校 CAS |
| POST `/Login/EntLogin` | `mobile,Password,ValidCode,Key,IV`；用人单位账号 | 未登录或注册；不是学生权限 |
| GET `/Home/StuApplyJob?job=...`，可带 `jobfairId` | `JobInfo.js` 在学生登录后打开“投个简历”窗口 | **未打开**；GET 界面属于投递流程，不能当普通职位读取 |
| POST `add_view_log`（相对路径） | `jobfairid,entsn,jobid,timestamp`；脚本注释明确添加记录 | 未调用；不自动按任意当前页补绝对地址 |
| 页面 AJAX `/Jw/StuApply`（方法/参数未完整记录） | 宣讲页内联代码发布的调用路径，具体业务效果仍待补证 | 未调用，不按名称认定为公开只读接口 |
| POST `/Jw/StudentReport` | `Type,Id,Content`；职位举报 | 未调用，属于写入 |
| POST `/Home/SendValidateCode`、`/Home/ResetPassword`、`/Login/Logout` | 验证码、重置密码和退出 | 未请求或执行 |

详情有 `__RequestVerificationToken` 隐藏字段，脚本检查学生登录 Cookie 的名称；这些只证明客户端预期，不是服务端鉴权或首次登录成功。未提取、保存或输出任何相关值。页内“记住密码”、职工招聘旧站的注册说明和学校 CAS 是不同边界。

`job.stu.edu.cn` 面向学校招聘工作人员，不是学生找工作。本轮没有重复访问或尝试其认证；其独立邮箱注册、岗位与应聘限制只引用[此前招聘调查](other-business.md#学校招聘-job)，不借 `gdc` 成功更新它的核查时间。

## 6. 公开脚本证据与下一步

| 本轮实际 GET 的官方脚本 | 响应字节 SHA256 |
| --- | --- |
| [`/Scripts/Search/SearchJob.js`](https://gdc.stu.edu.cn/Scripts/Search/SearchJob.js) | `97141a93e8e66415dc6773793b7bec573fc7701a91b64328e421527e05523705` |
| [`/Scripts/index.js?v=21`](https://gdc.stu.edu.cn/Scripts/index.js?v=21) | `8d84700c40826c4ec7a17f707be498ade1e89b5d6580e77165cbafd3b6d67f44` |
| [`/js/Main?v=1`](https://gdc.stu.edu.cn/js/Main?v=1) | `30bac802c26a9d5b17819a16377934a0d44aa27aae7374b3869e379b82e5cfc1` |
| [`/Scripts/Home/JobInfo.js`](https://gdc.stu.edu.cn/Scripts/Home/JobInfo.js) | `dbcf7c30bef47b2d0fa5f5b587bc8ddab9c367af4ab62bdf0ea709a5de667a51` |

四个本地公开脚本文件均已按原响应字节校验 SHA256；本轮没有执行这些脚本。HTML 散列只是各次响应指纹，不用其变化推断业务变化或当作稳定版本号。

后续优先解决职位分页与关键词错误，补真实详情字段和撤回/截止判据；再补合法城市/分类表、其他学历/性质/排序和查询错误。宣讲需更多类型、校区与时区样本，不能把月历或首页摘要当完整历史。可以先评估匿名就业信息适配，但应保留局部覆盖、空态与失败的区别；本人就业手续、简历、预约/投递和所有认证仍不在本轮已验证范围。
