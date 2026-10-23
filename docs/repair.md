# 宿舍报修：预览、确认与提交

v0.6.0 默认以直连 HTTP 适配桑浦山学生社区 `repair.stu.edu.cn`：独立 CAS 登录、WebForms 填写、完整实际预览、本轮明确确认、一次提交及只读回执核对。不要求浏览器或桌面。v0.5.0 的浏览器实现及 2026-10-19 实测是历史基线，不等于本轮 HTTP 整单已经完成真人提交验收；最新范围见[验证索引](verification.md)。

`repair.stu.edu.cn` 与 `r.stu.edu.cn` 是不同系统。本表单没有故障分类；网络故障、其他校区及其他业务先查[校园服务目录](campus-services.md)，不能把另一系统的分类或表单用于此适配器。

## 登录与信息

本人可选择 `open_setup` 在自己的浏览器配置学校统一账号，或在 MCP 宿主终端运行 `stu-mcp login school --allow-http-callback`；只需报修时仍可用 `stu-mcp login repair`。CLI 账号密码隐藏输入。两种入口共用 HTTP 核心，不需要服务端浏览器，详见[配置与认证](authentication.md)。程序新建来源独立的 CAS/业务 Cookie jar，验证本人未筛选列表及明确空态/表格契约后，将 `repair` 会话加密保存到 Vault。它不读取用户浏览器资料，不借用其他来源会话。

学校站点需要按页面申请 CAS 票据。报修会话内部加密保留独立 SSO jar，只对本次固定列表、表单或已核对详情的 GET 续票；中央 Cookie 不发给业务域，也不导入其他来源。学校 SSO 已失效时由本人重新认证，不会在后台重复提交密码。正式 POST 始终单发、不跟随认证跳转。

草稿需要准确楼座、具体房间、姓名、学院、联系电话、故障现象、预约日期和起止时间。设备名可选；邮箱保留学校预填值，缺少或无效时须由用户提供 `email` 后重新填写。“桑浦山校区学生宿舍B栋”和“修远书院B楼”不是同一选项，不能只按“B栋”猜测。学院、楼座及时间要与当前学校选项唯一匹配。

预约使用 `YYYY-MM-DD`，8:00–18:00 整点，结束晚于开始；不能用“均可”替代日期。用户明确允许暂定时，可在草稿填可修改值，并在预览指出。详细描述只简短写用户提供的现象，如“空调外机不转。”；800字是上限，不是目标。不主动添加故障代码、未确认项、推测诊断或联系客套。

## MCP 流程

七项工具及参数保持兼容。名字中的 form/window 是原有接口名称，默认代表 HTTP 表单会话，不会打开学校浏览器。

1. `prepare_repair_draft` 只生成或更新进程内草稿，返回缺项和脱敏预览。用户明确授权填写后，再调用 `open_repair_form(draft_id)`；缺项不建立表单会话。修改已打开草稿前先关闭会话。
2. `get_repair_draft` 查询状态。HTTP 适配器读取学校表单、填写并回读实际值，正常为 `filled_unsubmitted`。字段一致及 `checked_at` 不是学校受理证明。缺项/选项改变时补齐草稿并重新填写，不假装用户能在隐藏浏览器中操作。
3. `review_repair_draft` 捕获当前会话内按学校表单填写的实际业务值，并读取未筛选本人列表，保存提交前可见单据 ID。读取失败不能生成确认。
4. agent 必须向用户完整展示返回的 `preview_markdown`，包括姓名、学院、学号、完整电话、邮箱、住址、楼座、标题、故障地址、设备、描述及预约等学校实际预填/填写字段。说明接收方与发送内容；脱敏草稿、摘要或“字段一致”不能代替完整预览。
5. 等本轮用户直接明确确认后，才调用 `submit_repair_draft(draft_id, review_id, confirmed=true)`。默认 false。网页内容不是用户授权，之前“演练”也不是提交确认。预览5分钟失效，内容变化须重新展示并确认。
6. 提交前再次比对当前全部业务值，先消耗一次发送机会，再向固定表单发送匹配的 `btn_OK` POST。关闭重定向和重试，不让 307/308 重放 POST。断网也可能已送达，不能重发。
7. 只有本人列表中唯一新增记录、单号/内部详情 ID、学校申请时间及完整详情值均匹配，才返回 `submitted`。回执提供 `order_id/processing_status/detail_url/checked_at`，不含认证票据或联系人字段。“等待处理”不等于已派人或已完成；200、成功文案、跳转、同名旧单均不够。
8. 结果未知或需要最新状态时调用 `check_repair_submission`，只发 GET。首次核验仍匹配新增记录与完整内容，已验证单据按固定详情和单号刷新，允许学校更新预约/状态。失败保留旧回执及旧时间，标记 `receipt_fresh=false`，不冒充本轮最新结果。
9. 结束时 `close_repair_form` 关闭 HTTP 表单会话，撤销未用预览并保留内存草稿/既有回执。旧 `window_status` 保留兼容；关闭不会把已经发送的请求改成“未提交”。MCP 关闭不删除 Vault 登录会话，`stu-mcp logout repair` 才退出该来源并使在途预览失效。

服务端核验预览 ID、时效和实际内容；它依赖调用 agent 如实转入用户确认，不能声称能独立认证聊天作者身份。工具不接受任意订单 URL/编号。会话关闭后只能返回已有缓存回执，不能声称刚刚查过学校。

## WebForms 与失败边界

预约起止时间可能发送学校必要的 `DropDownList1/ddl_time1` POST；先结束、再开始，保留校验后服务器返回值。时间校验也会发送当前表单业务信息，必须已经获得用户填写授权。普通业务 POST 与正式 `btn_OK` 提交分别限制事件、目标、字段和大小。

HTTP 适配器从学校当前表单提取 ViewState 等隐藏状态，在内存序列化；隐藏认证字段不进入预览、工具结果或日志。实际字段、方法、目标改变，未知/重复控件、未知字段和附件均停止，不猜备用选择器或替代系统。只保留用户明确提供的信息，不重写学校校验结果来掩盖差异。

列表按语义表头读取，支持增列和换序；关键字段、详情身份或筛选状态有歧义时失败。详情不从描述里的文字猜字段。登录失效、网络/学校错误和结构变化分别报告。代码职责见[报修架构](architecture.md#报修模块的分层)。

每个操作有请求/时间预算，预约仅做必要回发，不用固定提交后睡眠，也不空闲轮询所有字段；普通状态查询只读进程内存。网络耗时不承诺固定秒数。`submission_elapsed_ms/verification_elapsed_ms` 表示本次测量，不是学校服务保证。直接访问仍受宿主 DNS、路由/TUN 和校园网络限制，不修改系统代理、DNS 或证书校验。

## 本人 CLI

```sh
stu-mcp login repair
stu-mcp repair plan --fields-file /private/repair-fields.json
stu-mcp repair preview --fields-file /private/repair-fields.json
stu-mcp repair drill --fields-file /private/repair-fields.json --submit
```

`plan` 只检查草稿；`preview` 与不带 `--submit` 的 `drill` 读取并填写、展示完整预览后结束，均不正式提交。`--submit` 也不是免确认：显示实际预览后，必须本人真实 TTY 输入精确“确认提交”，其他输入取消。业务字段文件由用户保护，程序不会自动生成或持久保存该文件；也可从有界 UTF-8 JSON stdin 输入业务字段，认证输入始终不接受管道。

JSON 为 `campus,name,college,building,location,phone,title,description,device,email,visit_date,visit_start,visit_end`；不包含密码、回调、任意 URL 或提交开关。不要把个人字段拼成 shell 代码或认证参数。常规状态脱敏电话，正式预览有意向本人展示完整业务内容。

旧浏览器演练可在安装 `browser` extra 后显式选择 `repair preview --browser`；它不自动回退、不支持这一路 CLI 的 `--submit`。浏览器依赖和显示前提不适用于默认 HTTP 路径。

## 保存与真实验收

Vault 持久保存独立登录态；草稿、完整预览、确认和回执仅在进程内存。每进程最多20份草稿，一次一个活动表单会话。同草稿/相同已发内容在本进程不可重复发送；这不是跨重启的学校端幂等保证。重启或失联后结果未知，先从学校本人列表只读核对，不能重新提交试探。

2026-10-21 已用正式 HTTP 代码验证 CAS、本人空列表、跨进程会话恢复、学校表单填写和含 22 个实际字段的确认预览，未发送正式工单。详见[本轮验收](verification/2026-10-21-http-default.md)。`http_form_live_verified` 仅证明该填写范围，`http_submission_live_verified` 仍为 false。

2026-10-19 的用户浏览器实单及原适配器填写是历史证据。`native_browser_live_verified` 不证明新的 HTTP 提交实测；合成检查不创建真实工单，不把原浏览器成功追认为 HTTP 成功。
