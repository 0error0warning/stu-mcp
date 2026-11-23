# 对分易后台与签到（`duifene`）

1. 先调用 `get_checkin_status()` 查看状态，它只读本地后台状态，不会启动服务或打开浏览器。准确区分 `service_not_started`、`not_logged_in`、`paused`、`monitoring`、`query_error`、`starting` 与 `stopping`；`monitoring=true` 时仍可能有 `failed_courses`，需读取 `status_reason`、`failed_courses` 与 `last_read_at`。
2. 缺登录时，本机桌面实例调用 `open_checkin_page()` 启动或复用本地后台并打开网页，由用户在浏览器完成原微信回调授权（或在宿主终端运行 `stu-mcp login duifene`）；远程 HTTP 按 `next_action` 引导本人操作。不索要或传递微信回调链接，不用官网扫码替代原流程；登录本身不会创建新监听计划（原已授权持续计划按原规则恢复）。
3. 调用 `list_checkin_courses()` 列出课程与已选状态；调整选课调用 `select_checkin_courses(course_ids=..., all_courses=...)`（若正在监听，须先暂停，本操作不直接开启监听）。
4. **仅在用户明确要求时**调用 `start_checkin_monitor(course_ids=..., minutes=90, all_courses=...)` 启动监听与自动签到。`minutes` 支持 `30`/`60`/`90`/`120`/`180`，`0` 表示持续监听并在后台重启后自动恢复；需保持电脑与本机后台运行。定位签到仍需用户在对分易完成。
5. 后台独立于 MCP 生命周期，退出聊天/MCP 不会停止监听。暂停使用 `pause_checkin_monitor()`（保留后台、登录与历史记录，取消自动恢复）；仅在用户明确要求退出共享后台进程时调用 `stop_checkin_service()`。
6. 调用 `get_checkin_results(course_id="", limit=20, offset=0)` 读取本机最近最多 200 条已观察签到活动。明确区分 `signed`（本程序提交成功）与 `already_signed`（平台原本已记录出勤），以及 `failed`/`error`/`waiting`/`manual_required`/`skipped`；`results_available=false` 或空列表不等于未签到。
