# STU MCP

This is an independent open-source product for Shantou University students.
The source baseline is School Hub commit `13f1b216ac35269d9840b6854ccff64c1e25e548`.

## Product constraints

- Obtain, cache and normalize campus information on demand. The user's agent does the analysis.
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
- Preserve user configuration; installation and connection must be idempotent and reversible.
- Do not modify the original School Hub checkout or production services for this project.

## Validation

Run `uv run --extra dev pytest` and `uv run --extra dev ruff check .`.
Use synthetic accounts and fixtures for automated tests; never export production credentials/data.
Document which live school flows have actually been validated. Cached data is not live evidence.
