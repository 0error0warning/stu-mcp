# 校团委公开信息

v0.7.7 起将 [共青团汕头大学委员会](https://xtw.stu.edu.cn/) 接入既有 `public` 来源，无需新增账号或配置。发行内容见[v0.7.7 说明](releases/v0.7.7.md)。

## 读取范围

| 栏目 | 学校原站 |
| --- | --- |
| 通知公告 | <https://xtw.stu.edu.cn/index/tzgg.htm> |
| 团学动态 | <https://xtw.stu.edu.cn/index/txdt/xwzx.htm> |
| 挑战杯 | <https://xtw.stu.edu.cn/index17X/cxcz/tzb.htm> |
| 中国国际大学生创新大赛 | <https://xtw.stu.edu.cn/index17X/cxcz/zggjdxscxds.htm> |
| 攀登计划 | <https://xtw.stu.edu.cn/index17X/cxcz/pdjh.htm> |
| 规章制度 | <https://xtw.stu.edu.cn/bszy/gzzd.htm> |
| 办事流程 | <https://xtw.stu.edu.cn/bszy/bslc.htm> |
| 资料下载 | <https://xtw.stu.edu.cn/bszy/zlxz.htm> |

每次刷新，各栏目最多返回 `limit` 条、最多读 3 页，沿学校页面的“下页”链接读取。学校的历史页码倒序编号，程序不自行拼出页码。官网和学生处保持原有首页读取范围。

`coverage.listings` 列出各栏目地址、成功解析页数、返回条数、页数上限、是否还有未读结果和状态；`has_more=null` 表示无法确认。翻页失败保留先前成功读到的记录，标为部分失败。达到条数或页数上限不代表全部历史已读完；`public` 仍返回有界读取的 `limited=true`。

## 查询方式

让 agent 先调用 `refresh_source(source="public", limit=20)`，再用 `search_notices(query="校团委", source="public")` 查本地缓存。按标题、摘要或栏目中的关键词搜索，也可以查询“挑战杯”“攀登计划”“规章制度”。选择记录后，调用 `get_notice(item_id=返回的ID, refresh=true)` 读取正文和附件列表。

CLI 使用相同的读取与缓存实现：

```sh
stu-mcp refresh public --limit 20
stu-mcp query notice --source public --search 校团委
stu-mcp notice <返回的通知ID> --refresh
stu-mcp attachment <返回的通知ID> --index 0
```

列表摘要是原站提供的截断预览，不能代替正文。发布日期来自列表专用日期块和正文“发布日期”字段，不从摘要中的活动日、报名日或落款推测。正文只取文章容器，不混入侧栏、上下篇导航和页脚。

通知搜索另提供至多1200字符的已缓存正文预览；`get_notice` 默认返回8000字符，按 `next_offset` 续读缓存。`metadata_only` 与附件状态的统一处理见[Agent 调用约定](agent-usage.md)。

## 附件与限制

支持列出正文内链接，以及学校 VSB 文章表单中放在正文外的附件。PDF、Word、Excel、PowerPoint、文本及压缩包均可保留附件链接；文字提取仍只支持现有 PDF / 文本范围，列出 DOCX、XLSX、PPTX 或 RAR 不表示已读到文件内容。

2026-11-15 的真实 PDF 样本返回学校下载验证码页。`read_attachment` 遇到这类页面保留 `interaction_required` 状态，同时返回通知正文地址 `source_url`、通知标题 `title`、附件名称 `name`、`content_ready=false` 和 `next_action=show_source_link`。Agent 应直接把通知正文链接发给用户，由用户在原网页自行查看附件；本次附件读取结束，不索要验证码，也不要求用户验证后回来续读。

给用户的说明可以是：“这个附件下载需要学校验证码，可以打开[通知原文](https://xtw.stu.edu.cn/info/1073/28651.htm)，在页面里查看附件。”该入口是通知正文页，便于用户同时查看上下文和附件列表。其他下载错误网页返回 `attachment_unreadable`。图片和扫描件不做 OCR。

本功能按需匿名读取，复用现有 HTTPS、主机范围、请求大小与时间预算，不新增后台同步。只覆盖上表的栏目及本地缓存。真实验证与未验收项见[2026-11-15 记录](verification/2026-11-15-xtw.md)。
