# r 校园服务台：真实页面与 V3 接口调查

调查日期：2026-10-23，北京时间约 20:10–20:47；21:06–21:43:23 补做认证页面、公开脚本及纯 HTTP 交接诊断；进一步**业务网络复核截至 14:11:52 UTC／北京时间 22:11:52**，14:16:59 UTC 另匿名读取校方公开使用指南，见第 8 节。本机网络路径、忽略环境代理、TLS 正常校验；业务接口调用为短超时 GET。已认证页面证据来自初轮 root 在 Chrome 调查标签页的只读核查，后续纯 HTTP 认证交接结果另列，没有导出 Cookie、票据、CSRF、个人预填信息或认证存储。

**业务边界：`r.stu.edu.cn` 是本报告对象，不是已接入的 `repair.stu.edu.cn` 宿舍报修。**未实现新 MCP 功能，也未创建、保存草稿、提交、更新、关闭、删除、评价或签到任何请求。

证据标签：**响应实测**是匿名 HTTP 实际结果；**页面实证**是 root 已认证浏览器实际可见页面；**客户端声明**是本轮官方脚本中的功能/参数/响应使用方式，不能冒充 API 成功返回。没有将厂商产品的所有管理功能当作汕大学生权限。

## 1. 业务入口与认证路径

| 路径 | 本轮证据 | 含义与限制 |
| --- | --- | --- |
| `GET https://r.stu.edu.cn/` | 响应 200，title `ManageEngine ServiceDesk Plus`，页面标 SDP 13.0/build 13001 | 443 是业务登录/请求系统；不是学校 CAS 本体 |
| 首页普通登录表单 `POST /j_security_check` | 静态 action/字段：`AUTHRULE_NAME/sdplogincsrfparam/j_username/j_password/dname` 和域选择/本地认证开关 | 没有向该表单提交学校密码，不能推断本地/AD 密码与 CAS 等价 |
| 页面给出的统一登录 `https://r.stu.edu.cn:6443/` | 匿名 GET 302 到 `https://sso.stu.edu.cn/login?service=https://r.stu.edu.cn:6443/` | **6443 是 CAS 入口，443 是业务站点**；不能把端口丢掉或用宿舍报修 CAS service 替代 |
| `GET /HomePage.do`、`GET /WOListView.do`、`GET /SolutionsHome.do?action=view` | 认证后页面实际导航 | 首页、请求、知识库；不是接口字段枚举 |
| `GET /WorkOrder.do?woMode=newWO` | root 认证后读取空白新请求表 | 只观察标签、字段名和选择器，没有保存或提交 |

root 已完成本轮正常 CAS 页面进入并读到请求列表，证明**现有浏览器正常统一认证可行**。本轮没有用直接 HTTP 完成首次登录、6443→443 的会话交接和账户正向证明，因此不能写“r 的纯 HTTP 首次认证已验证”。

2026-10-23 20:47 的独立 HTTP 研究进一步跟进官方 6443→443 `approval/Login.jsp`→`HomePage.do` 后，实际落在 **普通用户名/密码登录表**（`password_form=true`、title 为 ManageEngine ServiceDesk Plus），不是已认证请求页。因此本轮纯 HTTP 的业务会话交接**尚未成功**；前述浏览器只读成功与这次 HTTP 失败分别保留。没有重放含登录参数/嵌套认证内容的 URL，也未记录其中任何值。

HTTP-first 后续验证起点已明确：从官方 6443 GET 入口跟 HTTPS CAS，限制来源/端口，查明成功后如何进入 443、身份判据和两个服务端会话的边界。不得直接复制另一个来源的 SSO/Cookie，也不需要先生成技术员 API key。

## 2. 本人请求列表与空表实证

root 在 `/WOListView.do` 实际读到“**我的未解决的请求**”、`0 - 0/0`、“没有请求”。这是该筛选的本轮空列表，**不证明历史请求总数为 0，也不证明其他筛选或所有人的列表为空**。

`/WorkOrder.do?woMode=newWO` 可见必填标签：请求人、校区、详细故障地址、电话、预约时间、分类、主题；另见联系人、资产、紧急度、状态、描述、附件（显示上限 15MB）。表单默认 `Assigned` 只是新建表单默认值，不是已提交单据或派工事实。

| 已观察的 DOM name | 标签关联与证据状态 |
| --- | --- |
| `requester` | 请求人 |
| `assets` | 资产 |
| `udf_fields.udf_pick_304` | 校区，root 关联已确认 |
| `udf_pick_306` | 隐藏/自定义选择组件，具体标签尚未确认 |
| `udf_sline_307` | 疑似详细故障地址，仍需标签与控件容器对应验证 |
| `udf_sline_301` | 疑似联系人，仍需对应验证 |
| `udf_long_302` | 疑似电话，仍需对应验证；不得从字段 long 推断电话适合数值计算 |
| `udf_date_305` | 预约时间，格式/时区/时间窗口尚未验证 |
| `urgency/category/service_category/status/subject/description/files` | 请求基本字段、服务分类和附件；具体必填随模板/分类变动 |
| `sdpcsrfparam` | CSRF 字段名；未读取或保存值 |

这份字段清单只记录名称与已见标签，未记录本人姓名、联系方式、地址预填或隐藏字段值。`udf_*` 是该实例定制配置，不应提升为所有部署固定 schema。

## 3. 共同请求封装与响应合同

官方 `tableComponent.js?13001` 提供：

- `sdpAjaxInputData(value)` → `input_data=` + URL 编码的 `JSON.stringify(value)`。普通 GET 将它作为 query 参数，**不是直接把 JSON body 发 GET**。
- `sdpAjax` 默认 `type=GET`、`dataType=json`、`Content-Type: application/x-www-form-urlencoded; charset=utf-8`；默认 GET `cache=false`。
- 封装默认添加 `SUBREQUEST=XMLHTTP`；非 GET 另加 `sdpcsrfparam`，CSRF helper 的 cookie 名为 `sdpcsrfcookie`。仅记名称，没有读取任何值。
- 部分路径用 `Accept: application/v3+json`，兼容分支另用 `vnd.manageengine.v3+json`。不能把两者或所有直接 `jQuery.ajax` 调用强制归成同一种 header。
- `response_status` 在客户端同时处理 **对象或数组**：对象 `.status`，数组 `[0].status`，再检查 `messages[]`。成功、警告和失败分别存在，不只检查 HTTP 200。
- 客户端识别响应体 `__SDP__LOGIN` 切回 `/HomePage.do`；会话/认证错误还可用 `messages[0].status_code==401`。不能把登录 HTML 当 JSON 空列表。

### 匿名读接口实际错误

2026-10-23 对脚本原样声明的 `GET https://r.stu.edu.cn/api/v3/categories/get_csi_model` 做一次不带身份的请求，得到 **HTTP 400**、JSON：

```json
{
  "response_status": {
    "status_code": 4000,
    "messages": [{
      "status_code": 401,
      "type": "failed",
      "message": "该请求中的技术员密钥无效，不能认证。"
    }],
    "status": "failed"
  }
}
```

该错误说明匿名调用未通过，不证明“只有技术员 API key 才能调用”，也不是分类列表为空。root 浏览器可打开新表单；后续应验证其正常会话下只读 API 的认证方式，不要求用户新建管理员凭据。

## 4. 已发现的读取 API

除上述匿名分类失败外，以下均为 **本轮官方客户端声明**，没有导出浏览器会话重放。ID 只能从本人获准列表/模板读取，未猜 ID 或查看他人请求。

| 方法与路径 | 输入/过滤/分页 | 声明的响应内容和用途 |
| --- | --- | --- |
| `GET /api/v3/requests` | `input_data.list_info`：`start_index/row_count/get_total_count/sort_field/sort_order/search_fields/search_criteria/filter_by` 等 | 请求数组和 `list_info`；列表、本人未解决计数。脚本有 `filter_by:{name:"All_Pending"}` 和 `search_fields:{"requester.id":<当前请求人>}` 分支，不能据此任填别人的 ID |
| `GET /api/v3/requests/{id}` | 已取得的请求 ID；详情脚本可能根据 includes 改用 request_detail | `request`，包含 `id/subject/requester/status/...`；禁止把草稿默认状态当详情状态 |
| `GET /api/v3/requests/{id}/request_detail` | `input_data.includes` 指定各组成部分 | 脚本兼容 `request_detail` 数组，再读第 0 项中的 request、元信息、自助设置、关联项等 |
| `GET /api/v3/requests/newform` | `input_data` 包括 `template:{id:<所选模板>}`、`includes:["template","metainfo","self_service_portal","status","_links","priority_matrices","csi_model","get_connected_nodes","status_mandatory_fields"]` | `newform` 组合：模板、字段元信息、允许状态、分类模型、动态约束。换模板时 includes 可缩为 template/metainfo |
| `GET /api/v3/requests/template` | `input_data.list_info.row_count=100`；`sort_fields` 服务分类名/模板名；`search_criteria` `is_service_template is false/true` | `template[]`，`id/name/service_category`，故障/服务模板选择；编辑已有单时路径为 `/requests/{id}/template` |
| `GET /api/v3/requests/service_category` | `row_count:"100"/start_index`；`filter_by.name=hasMergedTemplates/hasIncidentTemplates/hasServiceTemplates`；fields_required | `service_category[]` 的 `id/name/description/image/sort_index/templates`；`list_info.has_more_rows` 控制每次 +100 |
| `GET /api/v3/categories/get_csi_model` | 脚本无参数 | `csi_model.categories[]`，每类有 `sub_categories[]`，再处理分类/子分类/项目依赖。匿名本轮失败，真实类别标签尚待 root UI/认证只读核查 |
| `GET /api/v3/requests/site` | `list_info.row_count=100/start_index`；编辑单可用 `/requests/{id}/site` | `site[]`；与校区自定义 `udf_pick_304` 的关系未证实，不能合并为同字段 |
| `GET /api/v3/requests/status` | `input_data={list_info:{row_count:100}}`；编辑单有 `/requests/{id}/status` | `status[]`，当前模板/生命周期允许状态 |
| `GET /api/v3/requests/status_mandatory_fields` | `input_data={status_id:<状态ID>,template_id:<新建/已换模板ID>}`；已有单有 request-scoped 版本 | `status_mandatory_fields`，不同状态必填字段；不能只按初始红星判断全流程 |
| `GET /api/v3/requests/{id}/metainfo` | 本人合法请求 ID | `metainfo`，字段定义/类型/动态关联 |
| `GET /api/v3/requests/{id}/self_service_portal_settings` | 本人合法请求 ID | `self_service_portal_settings[]`，脚本取第 0 项；当前账号 UI 权限等 |
| `GET /servlet/SDAjaxServlet?action=GetAllowedValues&module=INCIDENT&templateId=<模板ID>` | 固定 action、实际模块/模板 | `FIELDOBJECT/REVFIELDOBJECT` 允许值；现行页面同时有 servlet 与 V3，不能遗漏其一 |
| `GET /api/v3/requests/requester` | 选择器 searchOptions/criteriaCallback、分页 | `requester` 选择数据；涉及身份，不批量遍历用户 |
| `GET /api/v3/users/{id}/associated_assets` | `input_data={list_info:{row_count:"100"}}`，当前本人 ID | `associated_assets`；不以静态代码能拼 ID 推断可查全校资产 |
| `GET /api/v3/request_closing_rules` | 无固定输入 | `request_closing_rules[]`、mandatory_fields；仅记录规则，不执行关闭 |

脚本还有 `on_behalf_of`、空间（`space_campuses/space_structures/space_floors`）、优先级矩阵、生命周期、任务/备注/附件、知识库和管理对象的请求声明。它们是厂商通用包的一部分，本轮没验证学校是否给学生启用，不混入已确认能力。

### 可复用的请求模板

请求列表模板（静态；`<本人ID>` 必须来自该业务的正向身份/本人数据，不可从其他来源借用）：

```text
GET /api/v3/requests?input_data=<URL编码的下方JSON>
```

```json
{
  "list_info": {
    "start_index": 1,
    "row_count": 20,
    "get_total_count": true,
    "filter_by": {"name": "All_Pending"},
    "search_fields": {"requester.id": "<本人ID>"}
  }
}
```

模板列表模板（静态；故障模板，与服务模板 false/true 区分）：

```text
GET /api/v3/requests/template?input_data=<URL编码的下方JSON>
```

```json
{
  "list_info": {
    "row_count": 100,
    "sort_fields": [
      {"field": "service_category.name", "order": "asc"},
      {"field": "name", "order": "asc"}
    ],
    "search_criteria": [{"field": "is_service_template", "condition": "is", "value": "false"}]
  }
}
```

响应分页关键不是页码：客户端 `start_index` 从 **1** 开始，按 `row_count` 递增，检查 `list_info.has_more_rows`、`total_count`。不同 UI 默认 10/20/25/100 均存在，不能统一猜成 0-based offset。

当前唯一认证后空集证据是浏览器列表显示；没有实测 JSON 的 `requests:[]/list_info.total_count=0`，因此 JSON 空集字段与无权限/过期错误需在后续只读认证验证中补证。

## 5. 写入接口只记录

- 新建表单静态配置 `save.url=/api/v3/requests`，已有单为 `/api/v3/requests/{id}`；表单 serializer 为 `$req.form.reviseUpdateInfo`，不是把 DOM input 原样提交。
- 属性修改明确有 `PUT /api/v3/requests/{id}`、`Accept: application/v3+json`、表单字段 `input_data`；客户端兼容 success/warning，同时更新 request。**未执行。**
- 重开为 `PUT /api/v3/requests/{id}/reopen`；关闭、指派、合并、删除、评价、附件上传等都有独立操作，不能自动遍历“查看每个接口”。
- 列表刷新频率/布局/筛选偏好也有 POST/PUT，是账号配置写入；本轮未改变。
- 草稿页 GET 可能创建服务端临时页面状态，但本次没有点“添加请求/更新/保存”等按钮，没有测试任何一发一次事务。

后续若接入，应先完成只读列表、分类/模板、本人详情与状态，独立验证本来源身份和401/登录HTML处理，再决定是否做真实用户确认的提交能力。不能复用 `repair` WebForms adapter 或其单号/字段协议。

## 6. 原始脚本指纹与未完成项

脚本都是 root 在实际认证页面观察到的 URL，再由本调查无 Cookie 匿名 GET 获得，响应均 200。保存于 Git 忽略的 `output/campus-protocol-survey/repair-r/`；`?13001` 是本轮 build 参数，不是永久版本约束。

| 官方资源（`https://r.stu.edu.cn/scripts/`） | 原始内容 SHA256 |
| --- | --- |
| `sdp-requests.js?13001` | `6387d76d884c260361b4018f0f100aa92934375f2c3530592c6381618695ebf7` |
| `FormComponent.js?13001` | `9927b0c9e117f35cc4c3a2ffc98c8c744ea791af52f6d38387b4b7d3fb3c1092` |
| `servicedesk.js?13001` | `4239585c0af4ccf4f1c13e4ba3edeeef39f3f42ba18b213e0b8f98e5d91cbf52` |
| `ae-sdp.js?13001` | `76c4c3ea39a7e00d26adbd55dbe77a06962c0b6747a7a4f1c5375fb13df1a21e` |
| `tableInfo.js?13001` | `34daffa3201acaa2bada7bbb4b1d161ac9556b8de4ecc2ec1f7f0086b589da96` |
| `tableComponent.js?13001` | `33b6e38e7c81b3679ac1aea0574be2eb0e0c9137f1cd1613a91fce7e4a0d47d1` |
| `resource_common.js?13001` | `86d89e96dbc10731dc73c3d5a744c1f8a00865d2e2b294b854e2c0e474aa7b0d` |
| `ajax.js?13001` | `264896c85b43ac60ffbe93aa40464aba0a9b74f83fc40f6de97fac085634ddf0` |
| `FieldFormRules.js?13001` | `152b61fa7d57dfe36b802cd04336ccf117fce344c744219c602b8dc86e239bad` |
| `spa.js?13001` | `acb3627614f9f58deb31d25509c106e8f59b94d5ebde7a2a4826677ff28b5a4e` |

仍待补证：真实分类/子类/项目标签，`udf_*` 精确标签关联和日期格式，认证后 V3 列表/详情/空集/权限错误原始合同，模板权限，知识库检索字段，HTTP 首次登录/6443→443 的正向证明，附件读取权限与下载范围。当前没有“r 全部接口已验证”的结论。

## 7. HTTP 交接的自动表单分支补查

2026-10-23 `13:06:58Z`（北京时间 21:06）匿名实读页面本身引用的 `GET https://r.stu.edu.cn/scripts/Login.js?13001`：200，39615 字节，SHA256 `5996241a89dec4fcc233e3d61230f19a1e22d82765260921c6fc509ae5188fea`。这轮只读公开脚本，没有向本地登录表发送学校密码或任何认证 POST。

### 已确定的客户端逻辑

公开 `Login.js` 定义 `loadLoginAndEncryptPassword(uName, pwd, domain, publicKey, token)`：

1. `uName` 非空时，把传入材料放入当前登录表的 `j_username/j_password`。
2. `publicKey != null` 时调用 `encryptPassword`，即只排除 JS `null/undefined`，不排除空字符串。后者在需要时先给 `pwd` 拼固定分隔符和页面提供的 `token`，再以页面公钥调用 JSEncrypt 的 RSA 加密，结果替换 `j_password`。
3. `domain` 既不是 `null/undefined`、也不是 `"-"` 时，调用 `createDomain_NameForLogin` 生成相应域字段。
4. 最后选中登录表的记住登录复选框，并调用原生 `document.login.submit()`。

这是一个**自动表单提交**分支。直接使用 `httpx` 跟重定向只会拿到 HTML，不会执行它。原生 `form.submit()` 也不经过普通按钮调用的 `checkForNullInLogin`，因此不能把手动登录按钮的全部字段改写直接套进这个分支。

但是“函数在发行脚本里存在”不证明它在这次学校桥接页面被调用，也不证明其中 `pwd` 是派生材料而不是原密码。匿名初始登录 HTML 中**没有调用**这个函数。后续必须只在内存中检查实际桥接后 HTML 的调用、参数是否非空/占位以及表单是否完整；不能打印、保存或重新拼接认证材料。

### 匿名 Cookie/页面对照

`2026-10-23T13:10:01Z` 至 `13:10:06Z` 使用一个全新的、来源专用的匿名 HTTP 客户端顺序执行 3 个 GET，正常 TLS，不跟随学校 SSO：

| 请求 | 实际结果 | 仅保留的 Cookie 元数据 |
| --- | --- | --- |
| `GET https://r.stu.edu.cn/HomePage.do` | 200，普通登录表，`j_username/j_password` 都为空；包装调用也没有用户名材料，不会自动提交 | 设置 host-only `SDPSESSIONID`，`Path=/`、HttpOnly |
| `GET https://r.stu.edu.cn:6443/` | 302 到 HTTPS 学校 SSO | 未设置或替换上一步 Cookie |
| 无参数 `GET https://r.stu.edu.cn/approval/Login.jsp` | 302 到同业务 `HomePage.do`，包含用户名/密码参数名；没有有效身份材料 | 设置 host-only `sdpcsrfcookie`、`_zcsr_tmp`（Path=/，后者 SameSite=Strict）；临时 `priority` 也在响应头中出现 |

Cookie 值只在请求客户端内存里按服务器正常处理，没有输出、散列或保存。匿名对照**没有支持**“6443 和 443 的同名会话 Cookie 覆盖导致失败”这一猜测；不能把它当成已确诊原因。认证后 6443 是否另有会话 Cookie、域/路径冲突或是否需先初始化 443，还需 root 持有的当次业务 jar 元数据验证。

### 下一步的有限诊断顺序

- 保持学校中央 SSO 与 `r` 的业务客户端隔离；业务的 6443 和 443 路径按服务器自身 Cookie 域/路径处理，不复制中央整份 Cookie jar，也不任意改 Cookie 域。
- 从官方 6443 完成当次 CAS 后，精确跟随服务器返回的同业务桥接，保留认证参数在进程内；摘要仅输出路径、参数名称和布尔判据。
- 若最后 HTML 含 `loadLoginAndEncryptPassword` 调用，先确定参数来源、有效性和是否来自这次正常桥接，再讨论如何还原它；禁止拿学校 SSO 原密码填 `/j_security_check`，也禁止拿旧返回 URL 重放。
- 若没有自动调用、材料为空或参数语义未证实，就继续保留未成功结论；不能因为通用函数存在便补发手动登录。
- 只有建立了该业务身份正向证据，再调用本人列表/分类等只读接口；不以“密码框消失”或 HTTP 200 当作最终身份依据。

新的匿名元数据保存在忽略目录 `repair-r/auth-anonymous-metadata.json`；公开脚本与静态分析在 `library/r-auth-login-js.*`、`library/r-auth-login-static-analysis.json`。这只是调查文件归属沿用，不新增产品依赖。当前尚未执行该自动表单，也没有新增纯 HTTP 认证成功结论。

### 全部登录页脚本对照

`2026-10-23T13:15:29Z`（北京时间 21:15）按实际匿名 HTML 的引用顺序，逐个匿名读取 13 个脚本，均为正常 TLS 的 200。清单、时间、字节数和各自 SHA256 保存在忽略目录 `repair-r/login-script-manifest.json`，原文为 `login-script-00.js` 至 `login-script-12.js`。没有用认证 URL 或账号参数请求这些资源。

- 13 个脚本都没有 `isSSOLogin`；`Login.js` 本身没有 `ready`、`DOMContentLoaded` 或解析查询参数的自动登录入口。
- `Login.js` 还定义 `loadLogin(username,junkVal,domainname,publicKey,token)`，它包装前述自动函数。因此实际 HTML 必须同时查这两个函数的**调用**，不能只查长函数名或脚本中的定义。
- ESAPI 发行脚本确有通用 `getRequestParameter`，内部读取 `window.top.location.search`；其他已读脚本和匿名 inline 未见它用于认证，也没有读取 `isSSOLogin` 的逻辑。通用工具定义不能算已执行的认证分支。
- `getCustomHtml(login_logo,prodName,prodLink,prodVersion,cssClass)` 另取 `/custom/login/Login.html`。复核全部 inline 后，匿名页和当次 CAS 交接页都确有调用，不能漏查其他 inline 块。五参数仅用于本地品牌、版本和显示替换，函数的 HTTP GET 不携带这些参数；不能把品牌参数当成认证材料。
- 匿名 HTML 的 `changeLoginHtml` 仅处理外部聊天窗口、消息和显示内容，没有 URL 解析或认证提交。

root 随后重新取得当次 CAS 交接页面，在内存中检查最终 `HomePage.do` HTML：11215 字节，仍有 `/j_security_check` 普通表单。完整调用检查发现 `loadLogin` 调用的五个参数**全为空字符串**；按公开函数，这只会聚焦用户名输入框，不会加密或提交。`getCustomHtml` 的显示参数与匿名页不同，但表单用户名/密码仍为空。重定向全程直接跟随官方 Location 原串，没有先解析参数再重建 URL。以上仅保存结构、长度/非空布尔摘要，没有保存认证参数或完整认证 HTML。

因此，在当前实际 HTML 中，自动提交缺失不是简单“HTTP 客户端没有执行现有 JS”即可解释：可见包装调用没有收到有效参数；服务端桥接或账号映射等原因仍未证实。现阶段**既未证实 HTTP 登录成功，也未证实必须执行浏览器 JS**。

`2026-10-23T13:19:19Z` 实际匿名读取已启用的 `GET https://r.stu.edu.cn/custom/login/Login.html`：200，3325 字节，SHA256 `114f239cbce0abdd4023e8ceb87e614dce7c7ff57d633aa46ce2f82d07e598a1`。该 HTML **没有 script、事件处理器、查询参数解析或自动登录代码**，仅包含外观占位和“SSO单点登录”链接，指回 `https://r.stu.edu.cn:6443`。它不会补上隐藏的认证提交。安全摘要在忽略目录 `repair-r/login-custom-metadata.json`；没有保存 Cookie 值或认证 URL。

对 URL/参数检查只输出名称、长度和布尔判据，不能输出或散列认证值。正常 UA、Accept、语言头对照仍返回同类登录表，`loadLogin` 五参数仍为空；没有证明这些正常头能恢复认证。不得伪造身份，不把学校 SSO 原密码发往本地登录表。

### 普通按钮的字段合同

继续逐行检查公开 `checkForNullInLogin(btn,form,pubKey,token)` 和已有匿名表单，得到以下**当前页条件下**的可还原逻辑，不代表已经认证成功：

| 页面事实 | 当前普通按钮实际行为 |
| --- | --- |
| `onclick=checkForNullInLogin(this,this.form,null,null)` | 公钥为 JS `null`，不会调用 RSA；不能把空字符串误当成 `null`，因为代码判据为 `pubKey != null` |
| `AdEnable=false`、`LDAPEnable=false`、`enableDomainDropdown=true`、`DomainCount=0` | 不创建 `DOMAIN_NAME`，不选择或改变域，保留页面现有其他域字段 |
| 默认 `AUTHRULE_NAME=RememberMeLoginModule` | 函数最后仍设为同一个值；不需要试探其他认证模块 |
| 输入 `id=username`、`name=j_username` | 提交前将用户名转小写；这两个名称指同一控件 |
| 无 `captcha_text`、记住登录默认未选 | 无验证码分支，不提交未选复选框，不擅自开启记住登录 |
| `form method=post action=/j_security_check` | 按原表单的 successful controls 提交，保留当页 CSRF 和当前业务 Cookie jar |

公开表单合同可以说明正常按钮如何提交，但**不能据此认定网关 URL 中的材料就是可用凭据**。完整前置检查必须先验证材料不为空、不为占位且确属当次正常交接，不能仅排除 `null/undefined`，也不能只因与学校原密码长度不同便当成有效派生凭据。当前实际检查结果见下节；本轮没有进入提交阶段。

若最新页出现验证码、公钥或域选择变化，则本段简化条件失效，须按实际页面继续分析；不得用明文、默认域或其他认证模块试探。只有从同来源页面得到本人身份正向证据，再继续本人列表等只读 API；302、200、Cookie 变化或密码框消失都不是充分判据。

### 前轮预检停止点：材料语义尚未证实

root 已实现普通表单等价验证的**前置检查**，当次表单枚举、按钮参数、RSA 条件与 CSRF 均符合上述分析；但材料命中了研究客户端的通用布尔/占位类别，触发安全停止。这个**字符串形状判据不等于服务端协议语义**：不能仅凭它就断言网关缺失了真实密码，也不能把它直接当成可用于普通密码表单的凭据。先前将“命中占位类别”写成“密码材料确定无效”过于肯定，现收窄为用途未证实；具体值没有输出或保存。

因此在认证 POST **之前**停止，安全摘要原因为 `gateway_material_missing_or_placeholder`。本轮没有向 `r` 的 `/j_security_check` 或其他认证接口发送任何 POST，也没有用学校原密码代填、猜测材料或切换域。已在正确的 443 业务基址观察到分类 GET 的认证错误；早先误向 6443 发送业务 API 造成的 404 是调查器基址错误，不是该业务接口不可用的证据。

当前具体结论是：**本次网关交接未建立可用业务身份，其返回材料尚未被证明适用于普通密码表单，纯 HTTP 首次认证仍未跑通。** “网关丢失密码”“旧 GET 交接与当前版本不兼容”、账号映射或其他服务端原因都未确诊。后续需要校方实际 SSO 流程的有效协议证据，或以全新浏览器会话首次登录作正常流程对照；这种对照是调查方法，不能据此宣称业务必须依赖浏览器。

## 8. 进一步定位：公开入口、匿名控制与桥接材料结构

本节为后续真实检查，不以第 7 节旧缓存冒充新请求。仍未向 `r` 发送认证 POST，不尝试普通学校密码，不读取用户 Cookie 或私密浏览器存储，也没有接入 MCP。

### 重新联网的公开入口对照

`2026-10-23T14:05:12Z` 至 `14:05:18Z`（北京时间 22:05）以全新的匿名业务客户端顺序 GET，正常 TLS、`trust_env=False`、不自动跟随 SSO：

| 实际请求 | 新响应与可得结论 |
| --- | --- |
| `https://r.stu.edu.cn/` | 200、10962 字节，普通 `/j_security_check` 表单、输入为空；仍引用原 13 个脚本 |
| `https://r.stu.edu.cn:6443/` | 302 到 HTTPS 学校 SSO，没有新增公开交接页面 |
| `https://r.stu.edu.cn/custom/login/Login.html` | 200、3325 字节，SHA256 与第 7 节一致；没有 JS/事件处理器，仅原 6443 SSO 链接及外观占位 |
| `https://r.stu.edu.cn/scripts/Login.js?13001` | 200、39615 字节，SHA256 与第 7 节一致；未出现新的 URL 解析或桥接逻辑 |

只记录 Cookie 名称/域/路径等元数据：主页设置 `SDPSESSIONID Path=/`，定制页另有同名 `Path=/custom`。按正常路径规则，后者不随根路径 `/j_security_check` 发送；它与根路径 Cookie 并存，不足以证明整站 Cookie 冲突。原文 HTML 没有保存，安全结构摘要在忽略目录 `repair-r/public-bridge-recheck.json`。

随后**仅本地重新分析** 33 份先前已获取的公开 JS；它们不是本轮重新联网取回的 33 份响应。对 `6443/approval/isSSOLogin/requestContent/IMuserid` 的静态检索未找到桥接处理，只有 `Login.js` 的通用 `SamlRequestServlet` 分支。通用分支存在不代表当前实例已经启用或浏览器另有成功认证路线。

### 不带身份材料的对照

`14:08:24Z` 以独立匿名 jar 请求无参数的 `GET /approval/Login.jsp`，真实返回 302，生成 `HomePage.do` 的 `username/password` 参数；只保留长度、空值和类别布尔，不保存值。两参数即使非空且不命中上述通用类别，正常跟随这个**匿名服务器重定向**后仍为普通登录表，字段为空，包装函数没有用户名材料。没有提交或试验其中的材料。

这说明 **HomePage URL 存在非空用户名/密码字段，不构成有效身份或可用密码证明**。匿名控制也不能证明真实 CAS 返回材料无效；二者必须按各自来源和实际语义分别判断。安全摘要为 `repair-r/anonymous-approval-control.json`。

`14:11:28Z` 又以独立匿名客户端仅请求已观察参数 `GET /HomePage.do?isSSOLogin=true`，不带用户名、密码或票据。结果仍为 200、10962 字节普通表，`getCustomHtml` 的显示参数长度为 0，`loadLogin` 为三空字符串加两个 `null`。因此**单个显示标志不足以重现真实交接页面的渲染分支**，不能用它证明身份已交接，也没有据此组合或猜测凭据。安全摘要为 `repair-r/anonymous-sso-flag-control.json`。

### 当次 CAS 交接的字段流向与业务认证结果

主任务另行管理已获授权的 HTTPS 学校 SSO 内存会话，各业务 jar 独立。`14:08:22–23Z` 的真实 HTTP 链路与前轮一致，以下只保留结构，不记录任何材料值：

| 阶段 | 当次安全元数据 | 能证明与不能证明什么 |
| --- | --- | --- |
| 6443 根路径 → `/approval/Login.jsp` | 302；参数为 `loginName/IMuserid/token/requestContent`。`loginName` 非空，`IMuserid` 已为可识别的 JSON 布尔形状，`token` 呈 UUID 形状；`requestContent` 原样不能按 JSON 解析 | 已取得官方网关发布的交接结构；不能因字段名或形状推定它们分别是账号/密码或可用认证令牌 |
| approval → `/HomePage.do` | 302；`username/password/isSSOLogin`。用户名为数字串，不直接等于学校账号字符串；`password` 为同类布尔形状 | 数字串不同不证明账号错误；布尔形状也不证明本应存在的真实密码被丢失 |
| 最终业务页 | 200，普通表；用户名/密码输入为空，`loadLogin` 五个参数为空 | 没有建立可用于本人请求读取的业务身份，不能当作登录成功 |

`14:10:43Z` 只做**当次内存材料的本地关系检查**：`HomePage.password` 与前一跳 `approval.IMuserid` 逐字相等。由此可将现象定位到：**布尔形状材料在 6443 发出的交接中已经存在，approval 将它传入 HomePage 的 password 参数；并非有证据证明 approval 把真实密码丢失了。** 这个相等关系仍不能决定它的协议用途或作为普通密码是否有效。

`14:16:41Z` 进一步拆分**本地编码分类**，没有新联网：`loginName` 严格 Base64 解码有效，解得 16 字节，但不是有效 UTF-8；不能把它硬解成明文用户名，也不能仅凭长度断定密码算法。`requestContent` 在正常 query 解码之后，再作一次 URLdecode 没有变化，不是严格 Base64、无法按 JSON 解析，也未识别出批准的协议 query 键。材料仍不透明，没有查找密钥、尝试解密或请求由它拼出的目标。该细分更正了早前联合检查无法区分失败阶段的摘要，记录为 `r_bridge_encoding_only`。

`14:11:52Z` 在**正确的 HTTPS 443 业务基址**真实 GET `/api/v3/categories/get_csi_model`，得到 HTTP 400；响应为 `response_status.status_code=4000/status=failed`、`messages[0].status_code=401/type=failed`。`14:12:39Z` 是对该已获取响应的本地解析，仅确认错误消息包含认证/登录/会话相关词，不是新的联网请求。这与普通登录表共同支持**当前业务未认证**，不同于把错误当空分类；没有再次误用 6443 API 基址。

当次链路与本地关系摘要位于忽略目录 `followup/observations.jsonl`（`r_bridge_structure` 及后续关系/错误摘要）；没有保存完整认证 URL、材料值、Cookie 或个人字段。全程未发送 `/j_security_check` 或其他 `r` 认证 POST，也未对任何材料试密码、换域、重放旧 URL 或改变权限。

目前可确认的失败终点是 **CAS 网关重定向已到 443 页面，但业务身份尚未建立**；尚不能确定是网关协议、集成兼容性、账号映射或其他服务端条件。对材料用途的继续判断需要可验证的官方协议或正常首次登录流程对照；公开脚本和这些错误本身不能推出学校必须使用浏览器。

### 校方公开说明的边界

`14:16:59Z` 另以独立匿名客户端实际 GET [东海岸校区报修系统使用指南](https://stuecc.stu.edu.cn/info/1032/1139.htm)，返回 200、28036 字节，SHA256 `3a330558d5b7ffc25f031d77e7c0679fcd9c3d8c5b7167d4be899b27b428fcc7`；这是公开说明读取，不是业务认证复核。页面发布日期为 **2023-03-06**，发布 `https://r.stu.edu.cn/` 并指导点击 SSO 后输入校园账号，未指示向普通 SDP 登录表直接提交学校密码。该旧指南能佐证正式入口和正常使用方式，不能证明 2026 年接口、材料含义或当前首次登录仍成功。

本轮没有获取该页截图的本机图像内容；远端 Web 工具读取两张登录图超时，未用截图猜测协议。安全元数据为 `repair-r/public-guide-recheck.json`。

厂商官方 KB [Login with username and password in URL param](https://pitstop.manageengine.com/portal/en/kb/articles/login-login-with-username-and-password-in-url-param) 经本轮远端 Web 工具读取，描述需要服务器配置配合、读取公钥并以 RSA-OAEP/SHA-256 加密后进入 `/ESM.do` 的另一套本地认证流程；页面未给出可将它用于本实例 **13001／HomePage.do** 的明确版本依据。这不能替代学校当前 CAS 交接协议，本轮没有照此请求学校的 `ESM/app_resources`、修改配置或另试凭据，也不能据它确诊旧 GET 兼容问题。
