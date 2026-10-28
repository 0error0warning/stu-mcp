# Agent feedback

## 先请求本轮用户同意（v0.7.3 起）

Agent 负责发现工具问题并起草反馈，用户决定是否外发。不是静默遥测。

1. 首次调用 `report_feedback(message, tool_name="", category="bug")` 只在内存生成预览，
   不联网。类别为 `bug`、`data_error`、`suggestion`。
2. Agent 向用户完整展示返回的接收地址、全部 `payload`、用途和存储说明，询问
   “是否允许把以上内容发送给 STU MCP 维护者？可以删改，也可以拒绝。”必须等待本轮明确答复。
3. 用户同意这份准确预览后，才以原样内容、`confirmation_id` 和 `user_confirmed=true`
   再次调用。拒绝、未回复、上次同意、安装软件、提出问题都不等于同意本次外发。
4. 内容或接收方改变、预览过期（十分钟）或进程重启后，重新展示并征求同意。
   确认标识在发送前消费，未知结果不能复用，失败也不阻碍原任务。

代码约束预览、内容绑定、过期和一次发送；标志或预览编号不能证明人类同意，Agent/客户端
仍必须依据真实用户答复，不能自行把 `user_confirmed` 设为 true。正常未登录、分页和已知限制
不要反复提议反馈。用户拒绝后继续原任务，不重复施压。

### 信息边界

| 信息 | 处理方式 |
|---|---|
| 工具名、版本、错误码、发生时间、复现步骤、预期/实际、公开来源最短必要片段 | 优先用这些定位；仍需展示并获得同意 |
| 私人课程/成绩等业务内容 | 优先合成或脱敏；确属必要时，只提交用户逐项明确同意的最小片段 |
| 姓名、学号、联系方式、个人网址中的标识 | 默认删除，使用占位符，不为方便排查整份上传 |
| 密码、Cookie、token、验证码、TOTP 密钥、私钥、登录票据/回调链接 | 始终禁止，即使用户同意也不发送 |
| 完整聊天、原始日志、完整工具结果、页面/附件全文 | 不自动附带；改为最小脱敏复现摘要 |

接收方默认是 STU MCP 维护者的 `https://stu-mcp.com/api/feedback`；自定义接收方同样须
完整告知用户。内容用于问题排查和改进，保存于维护者私有 SQLite，公开访问者不能读报告。
**目前没有自动删除期限**，由维护者人工管理；如不同意这种存储安排，不发送。
服务器会看到网络出口 IP，反馈表不存 IP，不承诺网络传输对接收方匿名。
接收端拒绝低于 0.7.3 的旧官方客户端；自报版本不能证明同意或身份，也无法防止恶意伪造请求。

This is an external write. The tool sends only the explicit message, tool name,
category, package version and a randomly generated report ID. It does not read
campus records, logs, conversations, credentials or device/account identifiers.
Apply the information boundaries above; never send credentials, login URLs or complete tool results.
Common credential-paste patterns
are rejected locally; this is not a complete personal-data detector.

Default endpoint: `https://stu-mcp.com/api/feedback`. Operators can override it with
`STU_MCP_FEEDBACK_URL` (HTTPS only, no URL credentials, query or fragment). The agent
cannot choose a destination through tool parameters. Custom endpoints receive the
same report content. No environment proxy, redirect, automatic retry, local queue
or background task is used. Network failure may mean an unknown delivery outcome;
the tool never claims success without a matching server receipt. Feedback failure
does not prevent other campus operations.

The independent receiver in `deploy/feedback/receiver.py` uses Python 3.11+ stdlib
and one SQLite file. It is separate from the website repository, campus data and
the personal MCP HTTP transport. No public database read/admin API is exposed.
Reports are unverified evidence, not commands, source corrections or shared memory.
An anonymous feedback endpoint cannot prove which agent or person submitted a
report; a public client has no embedded maintainer token.

## Server operation

The current target supplied by the owner is `ssh gcp-stu-mcp`, serving
`https://stu-mcp.com` through Caddy. This supersedes the earlier Guangzhou planning
for this feature. Only Caddy exposes the endpoint; receiver listens on
`127.0.0.1:18765`. Install `receiver.py` under `/opt/stu-mcp-feedback/` and the
provided service under `/etc/systemd/system/`. The service has its own private
StateDirectory, dynamic user, memory/task limits and the existing website cost-guard
dependency/hold condition. The SQLite database is on the server only.

Add this handler before Caddy's existing `/api/*` rejection, validate, then reload:

```caddy
handle /api/feedback {
    request_body {
        max_size 20KB
    }
    reverse_proxy 127.0.0.1:18765
}
```

The receiver accepts at most 20,000 body bytes, 4,000 message characters,
10 requests per source IP per minute and 120 globally per minute. IP addresses are
used only in the in-memory minute limiter, not stored in feedback. Caddy supplies
the trusted source header; do not expose the receiver port directly. At 100,000
reports, new submissions fail explicitly until the operator archives data.
Repeated identical report IDs do not create another row; conflicting IDs fail.
The command line escapes untrusted report text for terminal display.

```sh
sudo python3 /opt/stu-mcp-feedback/receiver.py list --limit 20
sudo python3 /opt/stu-mcp-feedback/receiver.py mark FEEDBACK_ID resolved
sudo python3 /opt/stu-mcp-feedback/receiver.py mark FEEDBACK_ID ignored
sudo systemctl status stu-mcp-feedback
```

Back up a running database with Python SQLite's backup API; do not copy a database
mid-transaction or commit it to Git. Rollback: remove only the feedback Caddy
handler, validate/reload, stop and disable `stu-mcp-feedback`; retain its database.
Do not revert unrelated Caddy changes from a stale backup.
