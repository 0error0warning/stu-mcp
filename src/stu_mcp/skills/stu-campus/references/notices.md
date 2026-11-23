# 通知与附件读取

## 刷新与搜索

1. 用 `search_notices(query=..., source=..., limit=..., offset=...)` 搜索本地缓存（`query_scope="local_cache"`），支持 `all`、`public`、`oa`、`yuketang`。每次 `limit` 为 1–100（默认 20），`offset` 为 0–10000；搜索返回最多 1200 字符预览（`body_truncated=true` 表示仍有全文）、`detail_call` 与 `next_offset`。
2. 结果为空时读取 `empty_reason` 与 `next_calls`，区分尚未刷新、缺少配置、缓存不可读或已查范围内无匹配；多来源查询优先使用免登录或已配置来源。
3. 需要更新时用 `refresh_source(source=..., limit=...)`（支持 `public`/`oa`/`jw`/`mystu`/`yuketang`，1–100 条/课程）。来源仍受原站页数和请求预算限制，按 `coverage`、`limited` 与 `errors` 报告实际范围。

## 正文与附件读取

- 调用 `get_notice(item_id=..., refresh=..., offset=0, max_chars=8000)`，其中 `item_id` 必须来自已有通知结果，不接受任意网址。
- 返回 `status="metadata_only"` 或 `detail_available=false` 时按 `next_call` 补齐：`public`/`oa` 传 `refresh=true`，雨课堂公告通过 `refresh_source(source="yuketang")` 刷新。
- 正文默认每页 8000 字符（`max_chars` 1–20000，`offset` 0–60000）；`has_more=true` 时沿 `next_offset` 或 `next_call` 传 `refresh=false` 读取已缓存全文，不重复抓取。
- `attachment_options` 列出附件名称与从 0 开始的序号；调用 `read_attachment(item_id=..., index=...)` 提取 PDF 或文本（上限 8 MiB、100 页，扫描件不做 OCR）。区分三种结果：
  - `attachment_not_cached`：先按 `next_call` 获取通知详情与附件列表。
  - `no_attachments`：详情已读但无可用附件，结束本次附件读取，不重复刷新。
  - `invalid_attachment_index`：按 `attachment_options` 重选合法序号。

## 验证码交接与来源通道

- 遇到下载验证码页、登录/错误页、扫描或空 PDF、超页或不支持格式时，返回 `handoff_required=true` 与 `next_action="show_source_link"`。此时当前附件的自动获取已结束：立即交付 `title`、可点击的 `source_url` 与 `user_message`，保留“正文已读、附件未读”的区别。
- 不得为补齐该附件继续调用工具（包括重试下载、刷新 OA、遍历缓存、换来源或借其他工具取全文），也不索要验证码或要求用户验证后回来续调。用户要求“总结条款”不等于授权寻找替代版本；只有用户已明确要求寻找替代公开版本时才继续检索。用户后续主动提供内容时可继续分析。
- `public` 包含官网、学生处与校团委，属于匿名公开入口；当 `source_access.login_required=false` 且 `source_access.user_network_checked=false` 时，不因学校域名推断用户必须处于校园网或开启 WebVPN。
- OA 原站公开路径可匿名读取；受保护 OA 通过 `webvpn` 访问（教职工 `/login/cas.jsp` 业务未适配）。不得将 OA 登录问题与 `public` 混为一谈。
