# STU MCP for DeepSeek Harness

Optional thin UI bundle, verified against DSH **0.2.1-rc.3**. It adds a left
sidebar entry, a right sidebar tab, and a bundle configuration view. No build
step, extra React copy, school adapter, credential form or MCP process is added.

First connect the common STU MCP service with `stu-mcp connect dsh --apply`.
Download `dsh-stu-mcp-0.1.0.tgz` from the
[v0.7.4 release](https://github.com/0error0warning/stu-mcp/releases/tag/v0.7.4).
Then use the CLI belonging to the same DSH desktop installation, passing the
absolute path to the downloaded file:

```powershell
& '<DSH installation>/resources/runtime/cli/bin/dsh.cmd' plugin --profile desktop add '<download directory>/dsh-stu-mcp-0.1.0.tgz'
```

Restart DSH. Open **STU MCP** in the left sidebar, or choose **STU MCP** from
the right sidebar's new-tab guide. The installed package is `dsh-stu-mcp`.
It is distributed as a GitHub release asset; it is not listed in the DSH marketplace.
Developers may instead pass an absolute checkout path ending in `integrations/dsh`.

The panel starts with a short public-query summary, four common account rows,
and **登录与设置** / **刷新** buttons. WebVPN, takeout and utility features are
under **更多功能**; version and diagnostic details are under **连接信息**.
Account state still comes from the shared MCP catalog. “已设置” means saved
configuration, rather than a live check of the school service.

To remove only this optional UI:

```powershell
& '<DSH installation>/resources/runtime/cli/bin/dsh.cmd' plugin --profile desktop remove dsh-stu-mcp
```

The separately managed official MCP connection and shared credentials remain.
On DSH 0.2.1-rc.3, restart after disabling/removing to clear already loaded
client surfaces. A saved right-sidebar tab can remain as an unavailable-view
placeholder; close that tab normally. Re-enabling restores the viewer.
The UI invokes only the existing `get_capabilities` and `open_setup` tools via
DSH's authenticated Connection/Gateway source-mode Remote service. No generic
tool-execution endpoint is exposed. Local configuration status does not imply
live school availability. HTTP-hosted MCP setup remains on the MCP host.

`client.js` is the complete plain-JavaScript browser artifact. The host's React,
Slots and lifecycle APIs are reused; client unload removes entries and aborts calls.
The exact engine constraint is intentional: widen only after testing another
DSH release. Standard MCP clients do not depend on this bundle.
