# 对分易本地后台

STU MCP 与 `stu-checkin` 的本地网页控制同一个独立进程。后台和网页源码位于本仓库 `src/stu_checkin`，随 STU MCP 安装；MCP 不承载轮询线程，退出聊天或关闭 MCP 不会停止监听。两者需运行在同一台电脑、使用同一个 `STU_CHECKIN_HOME`；所有系统默认使用 `~/.local/share/stu-checkin`。Windows 打包客户端会重定向 AppData，该用户目录路径用于统一桌面启动和 MCP 启动。若已有旧目录，用 `STU_CHECKIN_HOME` 指向它的物理绝对路径继续使用。电脑关闭或休眠期间无法监听；没有自动安装开机任务。

## 安装和发现

已有后台时直接读取 `runtime.json`，校验回环地址、服务名、进程编号、随机实例标识与协议版本。不会执行发现文件里的命令，也不根据残留 PID 结束进程。发现文件由后台原子替换，服务进程持有 `worker.lock`；并发 MCP 启动通过 `launch.lock` 串行。正在运行但无法连接的后台报告查询异常，不再启动另一个进程。

Windows 的 MCP 客户端会使用进程作业组回收子进程，普通 `DETACHED_PROCESS` 仍可能在客户端退出时被回收。本扩展通过本机 WMI 以当前用户启动隐藏后台，与 MCP 作业组分离；不创建系统服务或计划任务，不申请管理员权限。仅传运行所需的环境变量，不继承无关 API 密钥。使用的启动接口和隐藏窗口配置见 Microsoft 的 [Win32_Process.Create](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/create-method-in-class-win32-process) 与 [Win32_ProcessStartup](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processstartup)。本机禁止 WMI 启动时会明确报告启动失败，不降级为依赖 MCP 存活的子进程。POSIX 使用独立会话启动。

当前源码版本为 `0.5.0.dev0`，此功能尚未发布到 v0.4.1 安装包。在本仓库运行：

```sh
uv sync --extra dev
uv run stu-checkin
```

也可以直接让 MCP 调用 `open_checkin_page`，按需启动后台。安装开发版到客户端时，先在本仓库运行 `uv build`，再运行 `uv tool install --force dist/stu_mcp-0.5.0.dev0-py3-none-any.whl` 和 `stu-mcp connect <客户端> --apply`，最后重新加载 MCP。后续发行版本按 [安装说明](install.md) 升级。

启动优先复用已运行的同协议后台；没有后台时使用当前安装的 Python 环境，不自动寻找相邻源码目录。高级用法可将 `STU_CHECKIN_PYTHON` 设为已安装兼容后台的 Python 解释器绝对路径。工具参数不接受路径或任意命令。

升级安装包不会替换正在运行的后台。要加载新后台代码，先暂停并退出服务，再重新打开网页；登录和已选课程保留，重新开始监听即可。

## 微信登录与使用

1. 在本地网页点「登录」，复制授权链接，发送到**电脑微信的文件传输助手**。
2. 在微信内点开链接，等待跳转，再点微信浏览器右上角「··· → 复制链接」。
3. 将刚复制的页面链接粘贴回本地网页，点击「登录」。回调链接只交给本地网页，不发给 agent。
4. 勾选课程或全选，选择时长后开始监听；「持续监听」持续到手动暂停。

关闭网页后后台继续运行。手动暂停取消自动恢复；持续监听计划会加密保存，仅在同账号恢复登录后自动恢复，限时监听不会跨服务重启恢复。更换账号不继承原计划。没有选中的新课程不会自动加入已有计划。

单独运行 `stu-checkin` 时，保持启动它的终端开启，或通过 MCP 启动隐藏后台。退出全部后台可在网页「更多操作 → 退出服务」操作，或调用 `stop_checkin_service`。

## 工具

| 工具 | 行为 |
| --- | --- |
| `get_checkin_status` | 只读状态；不会启动后台、打开网页或触发学校查询 |
| `open_checkin_page` | 启动或复用后台并打开网页；未登录时展开登录面板 |
| `list_checkin_courses` | 获取课程 ID、名称、已选课程和查询状态；按需启动，缺少登录打开网页 |
| `select_checkin_courses` | 传 `course_ids` 或 `all_courses=true`；运行中须先暂停，选择会同步到网页 |
| `start_checkin_monitor` | 传课程或使用已选课程；`minutes` 为 30/60/90/120/180，0 为持续监听 |
| `pause_checkin_monitor` | 停止下一次查询/提交，取消持续监听的自动恢复，保留服务与登录 |
| `get_checkin_results` | 本机结果分页；可按 `course_id` 筛选，`limit` 1–100，`offset` 从 0 开始 |
| `stop_checkin_service` | 先暂停并取消自动恢复，再正常退出后台；仅在用户要求退出服务时调用 |

同课程与时长重复启动是幂等操作，不新建线程或延长原截止时间。更换运行中的监听方案需先暂停。调用超时不自动重发修改请求，返回 `operation_uncertain`，先查询状态再决定。暂停后 `stopping` 表示仍在结束在途请求；已经发出的提交无法撤回。

缺少登录的操作直接打开本机网页，30 秒内抑制重复自动开页；主动调用 `open_checkin_page` 随时可重新打开。登录前的启动/选课请求不会排队在登录后执行，用户完成登录后重新发起。此前保存的持续监听计划仍按后台的同账号校验规则恢复。

## 状态约定

| `status` | 显示 | 含义 |
| --- | --- | --- |
| `service_not_started` | 服务未启动 | 未发现运行后台，或旧地址无法连接且进程锁已释放 |
| `not_logged_in` | 未登录 | 后台已启动，但没有会话或已确认会话过期 |
| `paused` | 已暂停 | 登录有效，监听已停止，包括尚未开始 |
| `monitoring` | 监听中 | 监听线程运行，未发现当前查询错误；查看 `last_read_at` 判断是否已有成功样本 |
| `query_error` | 查询异常 | 部分课程失败、数据过期、后台无响应、会话暂时无法验证或监听异常退出 |
| `starting` / `stopping` | 正在启动 / 正在暂停 | 恢复连接或结束请求中的过渡状态 |

`status` 描述业务状态，`monitoring` 描述监听器是否仍在运行；部分课程失败时可同时是 `query_error` 与 `monitoring=true`，其余课程继续。`failed_courses`、`course_statuses` 提供失败课程、上次尝试/成功时间和重试时间。成功重试后解除异常。主动暂停后保留历史查询信息，但不再宣称正在重试。

离线恢复不能判断登录失效，因此是 `query_error` 和 `auth_state=unknown`，不会冒充未登录。后台无法响应时 `monitoring`、`logged_in` 为 null，不能推断已暂停；确认服务未启动时 `service_running=false`、`monitoring=false`。状态观察时间是 `observed_at`，不能当成平台数据的采集时间。`ok` 表示本次读取/操作是否完成，判断业务状态必须看 `status`。

## 签到结果和凭据

最近 200 条已观察活动加密保存于后台，按课程与活动 ID 去重。`signed` 是平台对本程序提交的成功确认；`already_signed` 是读取到平台已有出勤，不证明由本程序提交。`failed` 是提交未获得成功确认，不证明平台最终未接收；`error` 表示处理发生异常，结果尚不明确。后续成功或读取到出勤会更新结果。其余状态为 `waiting`、`manual_required`、`skipped`。每条包含证据来源、活动时间和观察时间，不含签到码、汉字答案或位置坐标。

结果查询不触发新签到或新的平台查询；无结果不能推出未签到。后台未启动或无法读取时返回 `results_available=false`，不伪造空结果。断开登录会清除本机登录与记录。

微信授权及回调只在本机网页输入；MCP 不接收它们，也不输出 cookie、令牌、完整授权地址或后台内部浏览器会话。HTTP 客户端禁用环境代理与重定向，只访问验证后的 127.0.0.1 地址。后台继续使用系统密钥库和加密文件，无明文凭据回退。定位签到未启用。

## 验证范围

自动化验证使用合成账号和平台响应，包含真实 stdio、HTTP、独立后台进程和 MCP 断开后重连。覆盖并发启动复用、陈旧发现文件恢复、停机清理、状态转换、单课失败恢复、网页暂停同步、成功与已有出勤的区别、记录加密以及凭据过滤。

Windows 额外验证由 MCP 本身启动的新后台，在客户端关闭整个作业组后仍然存活，并核对后台与调用者使用同一个系统用户。该验证与“先从外部启动后台再连接 MCP”的测试分别执行。

这些验证不等于真实新课堂签到成功；数字码、二维码、汉字的新活动自动提交仍待本人课堂实测。

后台使用原生 HTML/CSS/JavaScript，无前端构建、远程字体或 CDN。上游引擎来源与改动见 [NOTICE](../src/stu_checkin/vendor/NOTICE.txt) 和 [许可说明](../src/stu_checkin/vendor/LICENSE.txt)。
