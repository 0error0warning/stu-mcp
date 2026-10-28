# Agent feedback

`report_feedback(message, tool_name="", category="bug")` submits a short report to
the STU MCP maintainer. Categories: `bug`, `data_error`, `suggestion`.
The agent should report concrete tool problems, source disagreements or useful
improvements, avoiding routine missing-login states and repeated reports.

This is an external write. The tool sends only the explicit message, tool name,
category, package version and a randomly generated report ID. It does not read
campus records, logs, conversations, credentials or device/account identifiers.
Do not include private course/grade information, student IDs, contact details,
credentials, login URLs or complete tool results. Common credential-paste patterns
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
