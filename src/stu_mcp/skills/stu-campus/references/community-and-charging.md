# 狐友讨论与充电查询

## 狐友公开讨论（`huyou`）

- 狐友是独立公共社区来源，公开读取无需登录或 Cookie，不获取私密帖、不发帖或评论。
- 将自然语言问题保留在 `query`，由当前 agent 先提炼 **1–6 个字面短词** 传入 `search_huyou_posts(query=..., keywords=[...])`；未传 `keywords` 时工具只按原句字面搜索，不自动拆词或调用模型。
- 默认圈子为「汕大树洞」；查询其他圈子先用 `search_huyou_circles(query=...)` 获取 `circle_id` 再显式传入。每次每页 1–20 帖，每词 1–3 页；先看返回的 `plan`、`keyword_runs`、`limited` 与 `errors`，按命中内容调整关键词。
- 搜索默认返回片段（`with_discussion=true` 仅附有界讨论预览）；完整正文与评论用 `get_huyou_post(target=..., refresh=true, with_discussion=true, comment_limit=20, reply_limit=10)`，其中 `target` 为数字 `feed_id` 或官方 `feedDetail` 链接。离线只读缓存传 `local=true`（搜索）或 `refresh=false`（详情）。
- 注意读取 `complete`、`truncated`、`response_truncated`、`errors` 与 `retained_from_cache`，不得把有界或保留的旧缓存说成刚抓到的完整讨论。引用时附原帖链接，涉及评论附评论 ID、时间与回复关系；狐友返回 `official=false`，校规、选课与截止时间须结合 OA 或学校正式通知核对。

## 充电设备与插座查询（`charging`）

- 直接读取第三方平台（`provider="isfdz"`），无需账号或自建服务。使用 `get_charging_overview(location=..., limit=4, offset=0, refresh=true)` 按位置关键词筛选已核验设备；留空可按页列出全部已核验清单，每页最多 4 台，按 `has_more` 与 `next_offset` 翻页。
- 用总览返回的 `device_code` 调用 `get_charging_device(device_code=..., refresh=true)` 查看插座编号、状态码与说明。`refresh=false` 只读本机缓存；联网刷新仍受 60 秒最小间隔保护。
- 逐台读取 `collected_at`、`last_attempt_at`、`stale` 与 `error`。离线或读取失败不能说成零空闲；过期样本按原 `collected_at` 引用。总览 `counts` 与清单仅覆盖当前页已核验设备，不代表全校完整覆盖；占用不等于确实正在充电，空闲插座也不保证现场停车空间。工具只读状态，不启停充电或支付。
