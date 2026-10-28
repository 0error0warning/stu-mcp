# 微信公众号接入可行性调查

状态：只读调查与方案，不代表功能已实现或发行。现有公众号采集没有被修改。

## 结论

后续项目对照测试已确认：**匿名读取单篇正文可行，可以优先实现纯 HTTP 阅读器**。
最初使用简化请求头的失败不能概括所有匿名 HTTP 访问。文章发现、最新列表和持续追更仍需
单独验证，不能由单篇阅读成功推导完整订阅能力。

仍应区分用户免登录与上游采集完全不依赖登录；可选的公共资讯源若依赖操作者授权，须明示。

微信公众号官方的[获取已发布消息列表接口](https://developers.weixin.qq.com/doc/subscription/api/public/api_freepublish_batchget.html)
要求 access_token 或获得授权的 authorizer_access_token；不是供匿名读取任意公众号目录的公共接口。
[WeRSS 原作者项目](https://github.com/rachelos/we-mp-rss)的微信读书采集器也明确依赖 Cookie。

## 匿名实测

最初在两个不同网络出口，使用全新 HTTP 请求、简化的 `User-Agent: Mozilla/5.0`，
不携带登录 Cookie 或 Authorization：

| 检查 | 结果与限制 |
|---|---|
| 两篇缓存中的公开文章短链 | HTTP 200，但可见内容为“环境异常”，无 DOM 正文及 content_noencode 正文；不算读取成功 |
| 一条带 `~` 的 WeRead 派生短链 | HTTP 200，但可见内容为“参数错误” |
| 上述 WeRead ID 按上游规则将 `~` 还原成 `_` | 从参数错误变为环境验证页；未验证拿到正文，不应宣称此修正已解决匿名读取 |
| 搜狗微信关键词搜索 | 返回相关文章搜索页；链接数不等于文章数，不代表最新或完整覆盖 |
| 搜狗前两条结果跳转，使用全新非登录 CookieJar | 返回 HTTP 200 的短跳转页面，尚未得到公众号正文；后续需要受限跳转解析或明确失败状态 |

这些是本轮样本的可访问性，不证明所有文章都必须登录，也不证明全部用户网络相同。
未解验证码、导入登录态或关闭 TLS 校验。一次第三方抓取服务读取文章返回内部错误，不用它推导文章状态。

## 可复用的经验与应避免的问题

- 采集、存储、健康检查、读取相互独立。上游登录异常不能阻止读取既有公开缓存，但须明确缓存时间。
- 文章发现与正文读取分别报告状态，搜索摘要不冒充正文，零结果不冒充公众号没有文章。
- 单独计算正文就绪率。题录保存成功、同步 errors 为空，不证明 content 存在；返回
  `metadata_only`、`content_ready`、`content_blocked` 等状态，不能让 agent 把标题当作已读全文。
- 对账号和文章分别隔离失败，已成功的条目仍可返回；避免一篇失败丢弃整个账号本轮结果。
- 增量获取详情，分页和请求预算明确；避免每轮重复读取全部旧文章。
- 用账号标识、文章标识和内容版本追踪变化；不要用“标题等于最新标题”作为唯一新鲜度证明。
- 保留来源 ID、原始来源 URL 和规范化 URL。WeRead 派生 ID 的转码不能套用到所有用户提交的 URL。
- 公开号名称不能独自证明身份；校园号目录应维护来源身份，并区分已核实、仅名称匹配与未知。

上游 [weread_mp.py](https://github.com/rachelos/we-mp-rss/blob/main/core/wx/model/weread_mp.py)
已处理 WeRead ID 的 `~` 转码，并为微信页面改版增加 `content_noencode` 兜底。
这些是需要针对样本验证的适配知识，不是匿名采集稳定性的保证。

## 建议接入方式

### 直接匿名访问

提供两个单一职责工具：

- `search_wechat_articles(query, account?, limit, cursor)`：公开索引发现；返回覆盖范围、来源、时间及未解析的跳转状态。
- `read_wechat_article(url, offset, max_chars)`：读取允许域名的公开文章，验证正文及来源元数据，分页输出正文。

读取适配器应同时支持已验证的 DOM 与受限 JS 字符串格式，禁止执行网页 JS。
遇到环境验证、删除、参数错误、结构变化或图片为主的内容，分别返回明确状态。
只返回 HTTP 200 或空文本不是成功。每个重定向都要校验域名/协议，限制体积、耗时与跳转次数。
不隐式启浏览器、获取用户 Cookie 或反复重试验证码；不能承诺该模式能稳定追更。

### 用户免登录的公共校园资讯源

如果优先要求校园公众号持续可查，可维护独立的公开资讯采集/缓存服务，MCP 匿名读取：

`已配置的公开校园号 → 独立采集器 → 仅公开字段的缓存 API → MCP`

上游若需授权，由服务操作者维护，必须明示，不称为“上游完全无登录”。
不把私有 Hermes、私人 School Hub 数据库、微信私聊/群聊、模型分析或个人画像变成 MCP 依赖。
公共接口仅暴露白名单公众号的公开字段，凭据与管理接口不对外；返回上游最近成功时间、
采集时间、覆盖范围和 stale/partial/blocked 状态。

正文优先按需直读；直读受限时，只有确有相应公开正文缓存才返回，并保留原文链接及缓存时间。
不把本次读到旧缓存的时间当成上游更新成功时间。
第一阶段优先固定校园号范围，避免把可用的局部搜索宣称为任意公众号的完整搜索服务。

## 候选项目实测与修正

核对版本：

- [wechat-reader](https://github.com/xiguawang/wechat-reader)，源码
  `2d590dd74b2f5ce9f2ac716a5b5571df34ea1844`，Python 0.1.0、MIT，依赖 Playwright。
- [url-md](https://github.com/Bwkyd/url-md)，发布版 v0.2.0（源码
  `d466d33040a5b775b0931df4996fc834351751d8`）；审阅 main
  `7e92aef1b9c75e2f895257fbdec96be9e55df367`，Rust、Apache-2.0。

本轮结果：

| 检查 | 结果 |
|---|---|
| url-md 官方 Windows v0.2.0，三篇文章，无登录参数 | 3/3 返回 Markdown；核对了校园样本的实际标题、作者和正文，非验证页 |
| url-md 同一校园样本，现有环境与清除代理环境变量的子进程 | 两种条件均成功；不据此推导系统所有路由均完全直连 |
| wechat-reader 原浏览器底层及原解析器，全新临时 profile、显式 headless，不 attach 任何已有浏览器 | 2/2 返回 ok，正文长度分别 891、9020 字符；未使用用户已有登录态 |
| 同一 URL、同一 urllib 直连实现，minimal → 完整桌面浏览器 UA → minimal | 正文字符数 0 → 778 → 0；说明本样本中请求头具有实际影响 |
| 广州以完整浏览器 UA 再读两个正常短链 | 无 Cookie/Authorization 也出现正文 DOM/JS 内容；探针体积上限为约 1MB，不能宣称读完全部响应 |

以上是小样本成功记录，不是长期成功率或全平台保证。wechat-reader 测试使用底层显式无头
runtime；公开 read/open API 当前硬编码 `headless=False`，不能声称其默认接口即适合无桌面服务器。

值得借鉴及缺口：

- url-md 的 HTTP 优先、按站点适配、Markdown 和结构化元数据适合默认路径；但其
  [CdpFetcher](https://github.com/Bwkyd/url-md/blob/7e92aef1b9c75e2f895257fbdec96be9e55df367/src/url-md-core/src/fetcher.rs)
  仍是占位实现，[pipeline](https://github.com/Bwkyd/url-md/blob/7e92aef1b9c75e2f895257fbdec96be9e55df367/src/url-md-core/src/pipeline.rs)
  不会在 HTTP 失败后真正完成浏览器回退。不能宣传有成熟的自动浏览器兜底。
- 两者现有解析主要依赖 `#js_content`；新适配器仍应验证纯 JS 正文、图片文章与验证页等格式。
- wechat-reader 的状态分类、已验证 tab 复用、人工验证交接值得参考；默认 auto 会尝试连接
  已有 CDP 浏览器。STU MCP 不应默认复用用户浏览器或把浏览器作为核心安装依赖。
- 两者都没有证明能提供任意公众号的账号检索、完整最新目录或持续追更。

## 建议顺序

1. 优先做 STU MCP 内的 Python HTTP 单篇阅读适配器，参考 url-md 的请求/提取设计，
   复用现有 HTTP/HTML 依赖，无需默认捆绑 Rust 二进制或 Chromium。
2. 保留 wechat-reader 式状态模型；浏览器增强仅为用户显式选择的能力，使用受控会话，
   遇验证交回用户，不自动读取已有浏览器 profile。
3. 单独验证公开搜索与校园号文章发现。之后若确需稳定追更，再评估独立公共资讯源，
   不把维护登录态预设为单篇正文读取的前提。
