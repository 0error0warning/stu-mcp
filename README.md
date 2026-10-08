# STU MCP

这个项目的前身，是我在「养」Hermes agent 时，从零搭起来的一个自用信息聚合器。学校通知、课程、作业，散在不同地方的信息，我都想慢慢接进去。自己用的版本里，甚至还接入了微信聊天记录。

我折腾它的原因，是希望 agent 在帮我做事时，能拿到足够的个人上下文：我最近在忙什么、有什么通知要看、哪些事情还没做完。和我有关的信息，如果它能在需要时自己查到，我就能少重复一些背景，也不用总在几个网站和聊天窗口之间来回复制粘贴。

后来，我把里面和汕大有关的部分整理成了 STU MCP，想让其他同学也能接到自己常用的 agent 上。它负责找信息、读信息，怎么理解和整理，交给你自己的 agent。

微信聊天记录接入留在自用版本里，公开版不包含。用这里的功能也不需要先装 Hermes，或者另外配一份模型 API key。

## 想试试的话

找一个能在你电脑上执行命令的 agent，把这两行发给它：

```text
帮我安装 STU MCP：https://github.com/0error0warning/stu-mcp
按 docs/install.md 接入当前客户端，保留已有配置并验证公开查询。需要登录时打开本地设置页，我自己来。
```

[单独复制这段 prompt](install-prompt.txt) · [安装细节](docs/install.md)

装好以后，可以直接问它：

- “最近有什么适合我报名的竞赛？把截止时间和原文找出来。”
- “整理一下 MySTU 接下来两周的作业，按截止时间排一排。”
- “树洞里有人聊过这门选修课吗？搜一下大家怎么说。”

## 现在能查些什么

| 来源 | 能查的东西 | 要登录吗 |
| --- | --- | --- |
| 学校官网、学生处 | 新闻、通知、活动预告、校园服务入口 | 不用 |
| OA | 近期通知、正文和附件，PDF / 文本附件也能读 | 先匿名读取，受限时再用 WebVPN |
| 教务 | 自己的成绩、学分加权统计、考试安排 | 需要 |
| MySTU / ELC | 课程、作业、测验、资料链接、个人日程 | 需要，ELC 可能要再登一次 |
| 雨课堂 | 课程、作业、测验、课程公告 | 需要 |
| 狐友 | 汕大树洞里的公开帖子、评论和楼中楼回复 | 不用 |

也可以记一下本地待办，或者告诉 agent 你的学院、专业和兴趣。它们都不是必填项，本地勾选“完成”也不会替你向学校提交作业。

查到的信息会带来源和缓存时间。想看最新消息时，让 agent 先刷新；没查到也可能只是这次没取全。狐友里是同学们的讨论，学校的正式要求还是要看 OA 或学校原文。[狐友怎么查](docs/huyou.md)

## 自己动手安装

先装好 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后运行。这里以 Codex 为例：

```sh
uv tool install --python 3.12 https://github.com/0error0warning/stu-mcp/releases/download/v0.4.0/stu_mcp-0.4.0-py3-none-any.whl
stu-mcp connect codex --apply
```

第二行换成你用的客户端，比如 `claude-code` 或 `cursor`。其他客户端、豆包工作和 Skill 的接法放在[这里](docs/clients.md)。已经装过旧版的话，第一条加上 `--force`，再重新接入、重启或重新加载 MCP。

想查成绩、课程或作业，再运行 `stu-mcp setup`，在弹出的学校页面里自己登录。密码不用发给 agent。登录会话和个人缓存加密保存在本机；WebVPN 自动重登可以在本地设置页按需配置。[登录说明](docs/install.md) · [存储与隐私](SECURITY.md)

教务的 HTTP 兼容需要你在设置页确认。开启后，成绩和教务会话会走 HTTP，密码仍在学校的 HTTPS 登录页输入。

喜欢用终端的话，也可以直接查：

```sh
stu-mcp refresh oa --limit 20
stu-mcp query notice --source oa --search 竞赛
stu-mcp huyou search 选课
```

## 还在慢慢补

目前是 [v0.4.0 预览版](https://github.com/0error0warning/stu-mcp/releases/tag/v0.4.0)。官网、匿名 OA 和狐友已经做过实际读取；教务、MySTU、雨课堂和 WebVPN 的真实学生账号验证还没补齐，各客户端里从安装到使用的完整流程也还需要继续试。具体测过什么、哪里还没测，记在[验证记录](docs/verification.md)里。

如果你用起来了，或者发现某个入口读不动了，欢迎开 issue 聊聊。告诉我用的版本、卡在哪一步就很有帮助，别把真实成绩、密码或登录凭据贴进去。

想自己改也可以：

```sh
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run stu-mcp setup
uv build
```

[更新记录](CHANGELOG.md) · [代码结构](docs/architecture.md) · [代码来源](docs/provenance.json)

MIT 许可。个人折腾的小项目，和学校官方没有关系。
