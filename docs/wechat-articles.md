# 微信公众号文章读取

v0.7.4 提供 `get_wechat_article`。stdio 与个人服务器 Streamable HTTP
共用同一实现。无需微信账号，不依赖 Hermes、私有 School Hub 或接收服务器。

```json
{"url":"https://mp.weixin.qq.com/s/文章短链","max_chars":8000}
```

接受 HTTPS `mp.weixin.qq.com/s/<短链>`，以及含 `__biz`、`mid`、`idx`、`sn` 的 `/s?...`
公开长链。规范化时去掉跟踪参数和 fragment，保留长链定位参数；不修改短链中的 `~`。
不接收 `pass_ticket`、`uin`、`key`、token 等登录参数，不接受公众号主页或任意网站。

默认 `backend="http"`，使用正常桌面浏览器请求头匿名读取。保持 TLS 校验，忽略环境代理，
不导入凭据，也不将响应 Cookie 转发到后续 HTTP 跳转。只跟随经过同域、协议和文章路径
校验的跳转，最多 5 次；每次读操作有 30 秒预算（单次 socket 等待最多 10 秒），
解压后的 HTML 上限 4 MiB，超限不会返回截断正文。没有自动重试或持久缓存。

需要渲染时，可显式传 `"backend":"browser"`。宿主须已有可选 `browser` extra 和
Playwright Chromium：源码开发可运行 `uv sync --extra browser`、
`uv run playwright install chromium`。默认安装和默认 Docker 镜像仍不包含浏览器。
每次启动全新无头 Chromium 上下文，完成或失败后关闭；不连接 CDP、不打开已有 profile，
不复用本人浏览器或微信登录态。只允许读取所需微信域的 GET 文档、脚本和渲染请求，
阻止第三方资源、子框架、图片和媒体下载。导航超时 20 秒，正文等待最多 3 秒。
渲染后只序列化文章正文、元数据和验证提示，文章快照上限 4 MiB，不序列化整页运行脚本。
浏览器启动等待最多 10 秒。HTTP 失败不会自动启动浏览器；浏览器也不能保证绕过来源验证。

正文同时支持 `#js_content` 和受限 `content_noencode` 字符串格式。HTTP 路径不会执行
网页 JS；字符串提取拒绝拼接表达式。成功须同时识别文章标题、公众号名或发布时间，以及
至少 20 个非空白正文字符。只返回校验后的文章文字和元数据，网页脚本、导航和评论不充当正文。
公众号显示名不是账号身份认证，`identity_verified=false`；来源文字作为不可信数据处理。

| status | 含义与下一步 |
| --- | --- |
| `ok` | 正文已校验，`content_ready=true`；检查 `has_more` 继续分页 |
| `captcha_required` | 环境异常或人工验证；打开原文核对，不自动解验证码 |
| `rate_limited` | 限流；稍后再试，不连续切换后端刷请求 |
| `article_unavailable` | 删除、参数错误、链接过期或 HTTP 404/410；核对链接 |
| `insufficient_content` | 正文不足阈值，可能是图片、媒体或未加载；没有 OCR/转写 |
| `schema_changed` | 缺文章元数据、未识别页面或非 HTML；不将摘要当全文 |
| `access_denied` | 来源拒绝匿名访问；打开原文核对 |
| `browser_unavailable` | 可选依赖或浏览器不可用；检查宿主安装，或使用 HTTP |
| `network_error` / `request_timeout` | 宿主网络失败或超时；不推断文章不存在 |
| `response_too_large` / `unsafe_redirect` | 体积或跳转边界触发；不输出截断正文 |
| `invalid_article_url` / `invalid_backend` / `invalid_offset` / `invalid_limit` | 修正请求；不会联网 |

失败均为 `ok=false, content_ready=false`，带 `next_action`，不附伪正文或原始错误 HTML。
`source_url` 是校验后的文章 URL，`checked_at` 是此次读取时间，`published_at` 来自原文，
不可混为一谈。网络和浏览器都运行在 MCP 宿主。

`offset` 按正文字符计数，`max_chars` 为 1–20000、默认 8000。`total_chars` 为已校验正文
总字符数，`next_offset` 为下一段起点，`has_more=false` 表示此次正文已读完。
继续分页会重新读取来源，内容更新可能改变偏移；没有快照一致性保证。
`coverage="article_text_only"` 不代表读到了图片里的字、音视频、附件或评论。
纯图片文章不会报告全文成功；带文字的图文只覆盖已提取文字。

不包含公众号搜索、最新文章目录、订阅追更或私聊/群聊。真实公开文章的成功样本与研究
来源见[调查记录](wechat-public-feasibility.md)；小样本结果不保证每篇文章或每种网络均可匿名读取。

## 本次验证（2026-10-28）

在 Windows 开发宿主上直接运行本功能实现，未导入微信登录态，两种后端共用正文校验：

| 公开样本 | 匿名 HTTP | 全新无头 Chromium |
| --- | --- | --- |
| [舞蹈体验课程预告](https://mp.weixin.qq.com/s/RqfeRn9cCw2nxZ5ZXjbOHw) | `ok`，749 字符，17 张图片 | `ok`，同样 749 字符、17 张图片 |
| [畅销书是怎么浪费你时间的？](https://mp.weixin.qq.com/s/AMJBh90iNEZBRLY3iWsYxQ) | `ok`，8854 字符，8 张图片 | `ok`，同样 8854 字符、8 张图片 |

字符数指去除网页脚本后的文章文字，不包含图片里的字。浏览器快照只保留文章证据；直接
序列化整页会因大量运行脚本超过上限，已通过快照方式修正。时间优先使用来源 `ct` epoch，
避免宿主时区导致浏览器显示日期与 HTTP 结果不同；校园样本两条路径均为
`2026-10-27T21:01:02+08:00`。

另以原样含 `~` 的已知错误短链实测，正确返回 `article_unavailable`，不返回正文、
不擅自改写链接。合成测试覆盖验证页、限流、非 HTML、正文不足、JS 字符串、恶意跳转、
体积上限、分页、缺可选依赖、匿名浏览器关闭和现有工具契约；不使用真实账号或隐私页面。
真实容器、其他出口和长期可用性仍未由这两个样本证明。

另通过实际 stdio MCP 握手调用 `get_wechat_article`，校园样本在 HTTP 与显式浏览器两条
路径均返回 `ok/content_ready=true` 和 50 字符分页正文；Streamable HTTP 使用同一实现，
回环传输的契约与拒绝非法 URL 由合成测试覆盖。
