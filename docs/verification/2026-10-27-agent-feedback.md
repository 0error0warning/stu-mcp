# Agent feedback implementation and deployment

Owner request: implement and deploy the previously discussed lightweight feedback
feature at the supplied fixed domain `https://stu-mcp.com`. End users need only
public HTTPS access.

## Delivered

- One additive `report_feedback` MCP tool, shared by stdio/Streamable HTTP.
- Default HTTPS endpoint `https://stu-mcp.com/api/feedback`; host configuration
  override `STU_MCP_FEEDBACK_URL`. No per-call destination or embedded credential.
- A stdlib-only Python receiver, separate server-side SQLite and local list/mark CLI.
- Existing 50 tool contracts retained; contract snapshot adds tool 51. Capability
  catalog includes feedback within the existing maintenance group.
- No release/version bump or public package publication in this task.

## Live evidence

Initial server inspection: existing Caddy, activity and cost-guard services active;
Python 3.11.2; feedback port unused. Prior Caddy SHA-256:
`182d801aa5876d7149c47468163382642285efdabb4385537f9249378a409f8e`.
Installer checked this exact hash, validated the candidate and added only the
feedback handler before the existing `/api/*` rejection. Prior configuration is
retained at `/etc/caddy/Caddyfile.before-feedback`.

Installed `/opt/stu-mcp-feedback/receiver.py` and `stu-mcp-feedback.service`.
Receiver listens only on `127.0.0.1:18765`, uses a dynamic user and private
`/var/lib/stu-mcp-feedback/feedback.sqlite3`, and depends on the existing guard with
its hold-file condition. Observed memory about 12 MiB, one idle task. Existing
static website release and activity runtime were not changed.

Actual MCP `call_tool('report_feedback', ...)` against public HTTPS returned
`status=received`, `isError=false`, feedback ID
`4d505055-8e54-4414-9979-1d115cc54dfd`. The same synthetic report was independently
read from server SQLite and marked `ignored`. A restart of this new service
retained both the row and status. Test description contains no personal data.

Public checks: homepage 200, `/api/activity` 200, GET `/api/feedback` 405 (no public
read). Receiver local health 200. Caddy, activity, cost guard and receiver all active.
This proves one real submission and persistence, not delivery from every user's
network or future uptime. Installed public package clients still need a future
release/update to discover the new tool; the source checkout contains it now.

## Verification

New boundary suite: 19 tests passed, covering HTTP persistence, duplicate IDs,
conflicting reports, invalid payloads, body limits, rate limits, storage failure,
client privacy fields, unsafe destinations, redirects and mismatched receipts.
Affected existing transport/contract suites: 65 passed, plus capability catalog
11 passed. Final full regression: **2477 passed, 4 skipped** in 475.51 seconds.
Ruff and diff whitespace checks passed. `uv build --wheel` succeeded; the wheel
contains `stu_mcp/feedback.py`. No package upload was performed.

Final deployed receiver SHA-256 matches the local source:
`0d3499feb97684e7c8bad55d1e765048eda94df515f683a34a1b47ea1dbb10eb`.
Temporary deployment uploads were removed; all four services remained active.

Admin and rollback commands: [feedback operation guide](../feedback.md).
