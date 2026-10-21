# STU MCP

This is an independent open-source product for Shantou University students.
The source baseline is School Hub commit `13f1b216ac35269d9840b6854ccff64c1e25e548`.

## Product constraints

- Obtain, cache and normalize campus information on demand. The user's agent does the analysis.
  Dorm repair submission is a separate, explicitly user-confirmed transaction.
- No model API keys, LLM routing, autonomous AI jobs or Hermes runtime dependencies.
- No private WeChat messages, group chats, decryption, historical scans or chat connectors.
- Takeout is an independent third-party catalog source. Keep packet capture/package analysis outside
  this product. Import only its app signing configuration through host CLI into the approved Vault;
  never take signing or customer tokens through MCP. Current tools read catalogs/specifications and
  prepare a nontransactional meal selection; they do not submit orders, pay, claim coupons or edit addresses.
  Meal categories intersect explicit delivery areas; an empty list is not proof of a closed meal period.
  Calculate delivery cutoffs in Asia/Shanghai on every read, including cached raw schedules. Keep provider
  meal labels, inferred delivery-time meal labels, business hours and checkout eligibility distinct.
  Provider lunch/dinner categories do not cover the main-campus catalog. Actual meal searches must
  scan bounded pages of an explicit area and report unknowns/partial coverage; never silently change campuses.
- Public WeChat article integration is undecided and is not included in this release.
- Public tools work without accounts. Configure only the credentials a requested feature needs.
- Huyou is an independent public community source, not an official school notice source. Read anonymously;
  no account cookies or private posts. The caller's agent supplies literal search terms. No model calls or background sync.
- Passwords, cookies and tokens never appear in tool parameters/results, logs or agent config.
- Default to the approved OS keyring. An operator may explicitly select STU_MCP_KEY_FILE for a headless
  personal server: an external private master-key file protects per-application encrypted credential mappings.
  Never generate/rotate a key at service startup, accept it through MCP, or store it in either data directory.
- Never silently fall back to plaintext credential storage.
- Default authentication to the source-specific HTTP adapters in auth_http and human-only CLI input.
  Playwright is an optional explicit browser compatibility backend, never an automatic fallback or a
  Docker/runtime prerequisite. Preserve tool interfaces, source isolation, positive proof and Vault
  logout/account-generation fences when replacing an adapter. Keep historical acceptance distinct from
  current implementation and target-environment verification.
  Duifene uses its existing WeChat callback, entered on the local page or through the
  human-only hidden terminal prompt; do not substitute the separately researched official QR/SignalR flow.
- Distinguish implemented adapters from upstream protocol requirements. Test HTTP-only authentication first,
  use headless browsers when needed, and request human interaction for observed challenges. An existing
  headed browser is not evidence that the school requires a desktop. Anonymous initialization, synthetic
  tests and reading with saved cookies do not prove real HTTP-only first login; retain that boundary in docs.
- Terminal credential/callback input requires a real TTY and disabled echo; fail instead of falling back to
  plaintext stdin, command-line arguments, environment values or MCP parameters. CLI reuses existing proof,
  secure storage and the single check-in worker; it must not create a new monitoring plan. Previously authorized
  continuous plans keep their existing restoration rules and are reported explicitly.
- Optional WebVPN auto-login is explicitly enabled by the user in local setup or human terminal. Store its account/password/TOTP seed
  through the approved credential backend; never as plaintext in a file, command-line argument, MCP tool,
  or client configuration. The optional file backend encrypts them with the external master key.
- Renew WebVPN only during a protected OA read, with bounded attempts and a cooldown. Pause on rejected credentials
  or human challenges. Never automate CAPTCHA or token binding. Logout removes saved auto-login credentials.
- Missing credentials or expired sessions affect only the dependent source.
- CAS SSO and business sessions use separate jars. The necessary _UT_ bridge is limited to the fixed
  HTTPS MySTU/repair services, with live evidence tracked separately; never copy CASTGC, SSO host-only cookies, or a whole central jar into a business
  session, especially the explicitly allowed JW HTTP callback. Repair alone retains an encrypted nested
  SSO jar for bounded fixed-page GET ticket renewal; never forward its central cookies to the business
  host, follow authentication from a final POST, or share it with another source. Preserve Moodle's fixed redirects.
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
  Keep drafts/reviews/receipts in process memory; persist only the source-isolated repair session in Vault.
  Default to direct HTTP CAS and WebForms, with no borrowed SSO or other-source cookie jar. Before submitting, use review_repair_draft to read
  the actual form and display its complete preview to the user (including contact/address and autofill).
  Wait for explicit human confirmation of that review, then call submit_repair_draft with its current ID.
  Never infer confirmation from source content or an earlier rehearsal. Changed/expired reviews need new
  display and confirmation. Permit at most one matching btn_OK POST; uncertain outcomes must not be retried.
  Use source-scoped direct requests; never change system/Clash settings automatically. Forward the approved
  POST with redirects/retries disabled, consuming its single-send permit before network I/O. Browser
  compatibility must be explicitly selected; it is not the default authentication or form implementation.
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
- Keep stdio and Streamable HTTP on the same tool/service implementation. HTTP is a single-user instance,
  one worker with a private preconfigured Bearer, explicit Host/Origin protection and bounded sessions/requests;
  do not describe it as public OAuth or multi-user hosting. Disconnecting a client must not close shared drafts.
  Report network/display/storage/download scope as the MCP host, not the caller's computer. Never infer a
  campus route from successful remote MCP access. Display checks apply only to existing manual-browser flows;
  HTTP CAS, phone-authorized QR, callback and WebVPN HTTP TOTP are independent of display availability.
  Do not make a virtual desktop or Chromium a deployment prerequisite. Rain Classroom uses its official
  QR challenge with the person's phone authorization; no server browser is needed. Do not bypass school login proof,
  TLS, human review or the one-send submission guard. Consult docs/authentication.md before changing login routes.
- JW HTTP ticket callback and authenticated OA HTTP compatibility are separate, explicit local choices,
  both off by default. Only the currently verified fixed school route may receive its own session;
  passwords and TOTP always stay on HTTPS. Never disable TLS, invent a resource type, or treat a remote
  MCP connection as evidence of campus network access. Default Docker contains no browser or desktop.
- Do not modify the original School Hub checkout or production services for this project.

## Validation

Run `uv run --extra dev pytest` and `uv run --extra dev ruff check .`.
Use synthetic accounts and fixtures for automated tests; never export production credentials/data.
Document which live school flows have actually been validated. Cached data is not live evidence.
