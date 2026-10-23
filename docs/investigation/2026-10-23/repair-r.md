# r 校园服务台：真实页面与 V3 接口调查

调查日期：2026-10-23，北京时间约 20:10–20:47；本机当前网络路径、忽略环境代理、TLS 正常校验。接口调用为短超时匿名 GET；认证后页面证据来自 root 在 Chrome 调查标签页的只读核查。后续纯 HTTP 认证交接尝试另列结果，没有导出 Cookie、票据、CSRF、个人预填信息或认证存储。

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
