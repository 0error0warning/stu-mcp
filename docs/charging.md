# 独立充电查询

当前开发版 STU MCP 可直接查询充电平台的设备状态，不需要学校账号、微信登录、自建网站、域名或服务器。用户的 agent 调用本机 MCP，由 MCP 处理请求签名、状态解析和本机缓存。该功能尚未包含在已发布的 v0.4.1 安装包中。

## MCP 用法

先调用 `get_capabilities`，确认存在 `charging` 来源。两个工具均读取第三方平台，属于只读查询。

| 工具 | 参数与用途 |
| --- | --- |
| `get_charging_overview` | `location=""`、`limit=4`、`offset=0`、`refresh=true`；按位置关键词查询设备摘要 |
| `get_charging_device` | `device_code`、`refresh=true`；查看一台已核验设备的逐口状态 |

例如，用户问“思源哪台设备有空闲插座”，可先用 `get_charging_overview(location="思源")`。返回编号后，用 `get_charging_device(device_code="4GR00008490")` 查看具体插座。

位置支持名称、设备编号和常用别名，例如“图书馆”“TSG”“思源”“SY-1”。空关键词从已核验清单分页读取，每页最多 4 台。`has_more=true` 时，将 `next_offset` 传给下一次查询。总览的合计仅覆盖当前页返回的设备。

## 命令行

在开发目录中执行：

```sh
uv run stu-mcp charging overview 思源
uv run stu-mcp charging overview --limit 4 --offset 4
uv run stu-mcp charging device 4GR00008490
uv run stu-mcp charging overview 图书馆 --local
```

`--local` 与工具的 `refresh=false` 都只读本机缓存，不发网络请求。缓存尚无成功样本时，设备仍可列出，但 `ports` 和 `counts` 为 `null`；CLI 在本次没有可用状态数据时返回退出码 1。

## 数据时间与范围

设备清单来自 2026-10-16 的公开接口核验，共 14 台，位置包括思源书院、图书馆、运动场中路、明德书院、至诚书院、敬一书院、文南楼和水电中心。`registry_verified_on` 是清单核验日期，不代表插座状态刚刚刷新。平台另一次返回的 15 台汇总不能作为缺少一台实体设备的证据，因此运行时不据此补编号或扫描相邻编号。

每台设备返回 `collected_at`（本机成功读取时间）、`last_attempt_at`、`cache_age_seconds`、`cached`、`stale`、`retained_from_cache` 和结构化错误。平台没有返回设备硬件上报时间；成功读取插座也不被转换成明确的硬件在线标志。

同一设备两次实际读取至少间隔 60 秒，`refresh=true` 也遵守这一间隔；这是本机策略，不是平台的限频承诺。成功数据超过 120 秒，或最新尝试失败时，会标记 `stale=true`。发生失败时保留上次成功数据及原采集时间；没有历史样本就保持未知，不能显示为零空闲。多个本机 MCP 进程通过 SQLite 租约去重同一设备的刷新；读取正在进行时可返回 `refresh_running`，稍后重读缓存。

插座保留原始 `num` 和 `state`，并附中文状态。`counts` 包含总容量、实际观测口数、空闲、占用、故障和未知数量；未返回的插座与未识别的状态都计入未知。总览合计只采用未过期且最新尝试未失败的样本，其他设备的容量计入未知；本页没有可用于当前统计的样本时，合计为 `null`。各设备旧样本仍保留，供按原采集时间参考。空闲表示平台报告的插座状态，不保证现场有停车空间。

客户端仅调用设备类型和两个协议的插座状态路径；签名失败最多重新读取一次公开配置后重试。拒绝访问、限流或入口结构变化会停止本轮后续读取，并在本机保留冷却状态。不会启动/停止充电、绑定卡、提交故障、读取用户订单或调用支付接口。协议证据和历史核验范围见 [充电平台研究](charging-platform.md)。
