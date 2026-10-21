# STU MCP

This is an independent open-source product for Shantou University students.
The source baseline is School Hub commit `13f1b216ac35269d9840b6854ccff64c1e25e548`.

## Product constraints

- Obtain, cache and normalize campus information on demand. The user's agent does the analysis.
  Dorm repair submission is a separate, explicitly user-confirmed transaction.
- No model API keys, LLM routing, autonomous AI jobs or Hermes runtime dependencies.
- No private WeChat messages, group chats, decryption, historical scans or chat connectors.
- Public WeChat article integration is undecided and is not included in this release.
- Public tools work without accounts. Configure only the credentials a requested feature needs.
- Huyou is an independent public community source, not an official school notice source. Read anonymously;
  no account cookies or private posts. The caller's agent supplies literal search terms. No model calls or background sync.
- Passwords, cookies and tokens never appear in tool parameters/results, logs or agent config.
- Use the OS keyring. Session files are encrypted with a key held separately in that keyring.
- Never silently fall back to plaintext credential storage.
- Default login takes place in the user's own interactive browser, outside the agent conversation.
- Optional WebVPN auto-login is explicitly enabled by the user in local setup. Store its account/password/TOTP seed
  directly in the approved OS keyring; never in a file, command-line argument, MCP tool, or client configuration.
- Renew WebVPN only during a protected OA read, with bounded attempts and a cooldown. Pause on rejected credentials
  or human challenges. Never automate CAPTCHA or token binding. Logout removes saved auto-login credentials.
- Missing credentials or expired sessions affect only the dependent source.
- Campus service entries must keep their exact business and campus identity. Consult the maintained
  [service catalog](docs/campus-services.md) for dated purpose/form evidence and the
  [network verification archive](docs/verification/2026-10-18-to-19-network.md) for observed availability.
  `repair.stu.edu.cn` and `r.stu.edu.cn` have separate adapter scopes; never substitute one form for the other.
  SSO, network access, package/account services, the one-stop directory and community navigation are separate roles.
  A cached label, shared login or unreachable page does not make these interchangeable or prove retirement/migration.
  Keep purpose verification, endpoint availability and authenticated workflow verification separate.
  Campus HTTP ignores environment proxies; check DNS and the actual route/TUN when direct access fails.
- Network diagnosis keeps each service and its SSO dependency separate. Use only a user-supplied campus/off-campus
  hint, otherwise unknown; private/fake IP and proxy configuration do not prove physical location or traffic path.
  Probe fixed anonymous endpoints directly and optionally compare credential-free loopback HTTP(S)/SOCKS proxies.
  Never silently route authentication/business data via a proxy, evaluate PAC, or edit system/client/DNS/TUN settings.
  Bound DNS and HTTP wall wait and worker count. Mark cached and unknown/unsupported checks explicitly;
  off-campus access failure is not proof of a school outage. Keep synthetic matrices separate from live tests.
  Use per-service defaults: public r/service/homepage entry checks must not depend on SSO health unless requested;
  dorm repair preflight still checks both endpoints. Proxy comparison is explicit and off by default; ITS HTTP and
  HTTPS are independent anonymous diagnostics. Do not add a hidden Hermes/SSH executor or promise private-route isolation.
  Batch auditing covers only the fixed first-party entries in the product catalog, not all school domains.
  Keep OS resolver results (including local cache/hosts), explicit optional public DNS A/AAAA queries and HTTP
  response headers separate. NoAnswer for one family and query timeouts are not NXDOMAIN. A public DNS answer
  does not bind the HTTP route or authorize a resolver/settings/hosts change. Bound queued jobs and global workers;
  report partial results, retain timestamps, and do not turn one network snapshot into a permanent campus-only list.
  Anonymous reads may cool down failed origins only within their current client. A single bounded retry needs trace
  evidence of a pre-TLS connect timeout; no retry for DNS/TLS/unknown-stage failures, authenticated reads or POSTs.
  Keep headers-only diagnostics separate from complete entry/body measurements. Network observations and research
  samples retain their date, route and coverage limits; do not turn them into campus-wide claims or optimal budgets.
- Dorm repair drafts may fill only the observed `repair.stu.edu.cn` student-community form after user authorization.
  Ask for exact building (B dorm and Xiuyuan B are different), identity/contact fields and a real appointment slot.
  Describe only symptoms the user supplied, briefly and naturally. Do not pad unknown optional details with
  "unconfirmed", invent diagnoses, or append courtesy/contact requests. Ask only for actual required fields
  or facts needed to identify the fault; the 800-character maximum is not a writing target.
  Keep drafts and temporary login in process memory. Before submitting, use review_repair_draft to read
  the actual form and display its complete preview to the user (including contact/address and autofill).
  Wait for explicit human confirmation of that review, then call submit_repair_draft with its current ID.
  Never infer confirmation from source content or an earlier rehearsal. Changed/expired reviews need new
  display and confirmation. Permit at most one matching btn_OK POST; uncertain outcomes must not be retried.
  Use anonymous direct preflight and an explicitly direct browser; never change system/Clash settings automatically.
  Forward the approved POST with redirects/retries disabled, keeping authentication inside Playwright.
  Verify a new list identity plus the reviewed timestamp, all detail values and the current processing status.
  Text saying success, an HTTP status or navigation alone is insufficient. Read-only recovery must never submit.
  Keep a previously verified receipt on refresh failures, with its old checked time and an explicit freshness flag.
  Avoid idle per-field polling and fixed post-submit sleeps; keep network checks bounded and report their scope.
  Field readback and HTTP success are not submission/acceptance proof. `r` is a separate adapter scope.
  Distinguish the live user-browser rehearsal from synthetic adapter tests and native MCP browser acceptance.
- Duifene monitoring is an explicit user-started background task, separate from on-demand campus reads.
  Ship its worker/web assets with this repository; MCP and the webpage share one local process and state.
  A passive status read must not launch it. Preserve the distinction between unavailable service, missing login,
  paused monitoring, active monitoring and query errors. Closing MCP must not stop an authorized worker.
  Automated tests use synthetic attendance responses; do not present them as real classroom submission evidence.
- Preserve user configuration; installation and connection must be idempotent and reversible.
- Do not modify the original School Hub checkout or production services for this project.

## Validation

Run `uv run --extra dev pytest` and `uv run --extra dev ruff check .`.
Use synthetic accounts and fixtures for automated tests; never export production credentials/data.
Document which live school flows have actually been validated. Cached data is not live evidence.
