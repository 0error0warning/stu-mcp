# 狐友公开讨论（开发分支）

本功能尚未发行；v0.3.1 安装包不包含它。参考 School Hub 提交 `3986c4ae49d2ffed4e41582a4f40a2fdd8ef31fa` 中的接口与讨论分页行为，独立适配到 STU MCP，不依赖 School Hub、Hermes 或其数据库。

默认圈子为汕大树洞，ID `905956136904237440`。圈内字面关键词搜索不是全站搜索。公开读取无需账号、Cookie、模型 API key 或系统密钥库；本版不实现登录、私密帖、发帖或评论。

## MCP 和 CLI

| 目标 | MCP | CLI |
| --- | --- | --- |
| 按关键词搜公开帖子 | `search_huyou_posts` | `stu-mcp huyou search 原问题 --keyword 选课 --keyword 给分` |
| 公开正文与讨论 | `get_huyou_post` | `stu-mcp huyou detail FEED_ID` |
| 发现圈子 | `search_huyou_circles` | `stu-mcp huyou circles 汕大` |
| 离线关键词查询 | `search_huyou_posts(local=true)` | `stu-mcp huyou search 选课 --local` |
| 离线单帖 | `get_huyou_post(refresh=false)` | `stu-mcp huyou detail FEED_ID --local` |

自然语言问题先由当前 agent 选择 1–6 个字面短词，MCP 使用 `keywords` 字符串数组，CLI 重复 `--keyword`。`query` 保留原问题，返回 `plan` 和每词 `keyword_runs`。没有显式列表时将整个输入原样搜索，不自动拆词、扩同义词或调用另一个模型。多个关键词的结果取并集、按帖子 ID 去重，轮流选择不同词的候选，避免第一个词占满上限。

搜索默认返回有界片段，不会对每个候选补正文、抓评论。`with_discussion=true` / `--with-discussion` 可补充小范围上下文，每帖最多请求 5 条主评论、5 条回复。需要更多内容时调用单帖工具，默认 20 条主评论、10 条回复；可用 `comment_limit` / `--comment-limit`（1–40）和 `reply_limit` / `--reply-limit`（0–20）。回复上限由同帖所有主评论共享。内嵌回复先复用，再按服务器游标补缺页。

搜索一次返回 1–20 帖，每个词最多 1–3 页；单帖主评论最多 3 页，每个楼中楼最多补 2 页。整轮读取包含重试最多 40 次 HTTP 请求、45 秒，每次间隔至少 0.25 秒，网络错误或临时错误最多额外重试一次。持续限流、较长 `Retry-After`、登录要求或预算耗尽停止整轮，保留已有结果。只允许固定接口的 HTTPS GET，不跟随跳转、不复用响应 Cookie。未知字段和错误响应不会当作成功空列表。

## 证据和缓存

每条帖子保留原帖 URL、时间、公开昵称、匿名标记、关键词命中片段；评论保留 ID、时间、作者回复标记和回复目标，不存账号 ID 或头像。图片仅提供公开 HTTPS 地址，不下载或 OCR。社区讨论标为 `source_type=community`、`official=false`，以独立 `post` 类型保存；`search_notices` 不会把它当作 OA 通知。政策、截止时间和正式要求需结合学校官方来源判断。

离线搜索匹配标题、正文、命中片段及评论/回复文字，历史搜索关键词本身不产生匹配。`local=true` / `--local` 完全不联网。轻量搜索不会覆盖此前取得的正文或讨论。完整讨论快照能清理已消失的评论；主评论页或某个楼中楼未完整读取时，只保留该层尚未确认的旧内容，标为 `retained_from_cache` 并提供 `previous_fetched_at`。重新获取完整正文后更新正文时间。

检查顶层 `limited`、`errors`、来源时间，以及讨论的 `complete`、`comments_complete` 和各楼的 `replies_complete`。搜索响应另有 `body_preview_truncated`、`response_truncated`，只裁剪输出预览；较多内容仍可通过单帖缓存读取。覆盖完整只描述本轮可见范围，不能保证之后没有新增讨论。空结果只说明本次所读范围的匹配情况。

## 接口来源与验证

2026-10-06 核对[狐友官方网页](https://hy.sns.sohu.com/)及其公开[请求签名代码](https://hy.cdn.sohucs.com/hy-web/prod/_nuxt/BWwMEoFL.js)、[圈内搜索代码](https://hy.cdn.sohucs.com/hy-web/prod/_nuxt/tSGqOUgs.js)、[详情和讨论代码](https://hy.cdn.sohucs.com/hy-web/prod/_nuxt/DJGa3ueV.js)。接口基址为 `https://cs-ol.sns.sohu.com`，请求路径为圈子搜索 `/circle/search/v20`、圈内搜索 `/circle/search/feed/v22`、详情 `/v7/feeds/show`、评论 `/v8/comment/list`、回复 `/v8/comment/replylist`。

签名常量属于公开网页客户端，和用户凭据无关。它使用网页的 `appid=330012`、版本 `6.22.0`、毫秒时间戳与 MD5 参数签名；不转用 School Hub 的可选 Cookie 功能。上述是网页内部接口，不是稳定的第三方 API 承诺，站点更新可能需要适配。

STU MCP 的匿名实测在临时缓存中完成：圈子搜索返回 3 个圈子，限定一页的“选课”搜索返回 2 帖，无错误；读取其中一帖正文、1 条主评论、1 条内嵌回复成功，讨论在所读范围完整。搜索为 `partial`，表示有界范围，错误数组为空。未打印或提交真实帖文、昵称或账号信息，未使用原项目缓存/登录态。
