# STU MCP

这个项目的前身，是我在「养」Hermes agent 时，从零搭起来的一个自用信息聚合器。学校通知、课程、作业，散在不同地方的信息，我都想慢慢接进去。自己用的版本里，甚至还接入了微信聊天记录。

我折腾它的原因，是希望 agent 在帮我做事时，能拿到足够的个人上下文：我最近在忙什么、有什么通知要看、哪些事情还没做完。和我有关的信息，如果它能在需要时自己查到，我就能少重复一些背景，也不用总在几个网站和聊天窗口之间来回复制粘贴。

后来，我把里面和汕大有关的部分整理成了 STU MCP，想让其他同学也能接到自己常用的 agent 上。它负责找信息、读信息，怎么理解和整理，交给你自己的 agent。

微信聊天记录接入留在自用版本里，公开版不包含。用这里的功能也不需要先装 Hermes，或者另外配一份模型 API key。

## 想试试的话

找一个能在你电脑上执行命令的 agent，把这两行发给它：

```text
帮我安装 STU MCP：https://github.com/0error0warning/stu-mcp
按 docs/install.md 接入当前客户端，保留已有配置并验证公开查询。按安装版本说明登录；认证信息由我本人输入，不发给 agent。
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
| MySTU / Moodle | 课程、作业、测验、资料链接、个人日程 | MySTU 登录；ELC / Campus 分别核验 |
| 雨课堂 | 课程、作业、测验、课程公告 | 需要 |
| 狐友 | 汕大树洞里的公开帖子、评论和楼中楼回复 | 不用 |
| 充电设备 | 按位置查设备空闲、占用、故障数量，查看每个插座的状态 | 不用 |
| 对分易 | 多课程监听、启停与签到结果，本地网页和 MCP 共用后台；新课堂提交仍待实测 | 原微信回调，可用宿主网页或终端 |
| 桑浦山宿舍报修 | 检查缺项、填表、展示完整预览，等本人确认后提交一次 | 独立 HTTP 登录 |
| 校园连接诊断 | 分别检查业务站、统一认证、直连、DNS和本机代理 | 不用 |
| 学校入口批量检测 | 批量比较本机DNS、可选公共DNS和匿名直连，区分解析失败与连接失败 | 不用 |

也可以记一下本地待办，或者告诉 agent 你的学院、专业和兴趣。它们都不是必填项，本地勾选“完成”也不会替你向学校提交作业。

查到的信息会带来源和缓存时间。想看最新消息时，让 agent 先刷新；没查到也可能只是这次没取全。狐友里是同学们的讨论，学校的正式要求还是要看 OA 或学校原文。[狐友怎么查](docs/huyou.md)

本版包含充电查询，由本机 MCP 直接请求充电平台，按设备缓存，没有网站或自建服务器依赖。现有清单包含 14 台已核验设备，不代表全校完整清单；离线和旧数据会单独标记。[充电查询用法](docs/charging.md)

校园连接按服务处理：r和一网通办先查自身入口，宿舍报修需要时核实校园接入，SSO和ITS各协议独立判断。默认诊断只查所需端点，本机代理对照按需开启；普通读取复用连接，同批次暂时跳过连接失败的主机，继续读取其他来源。它不自动改代理或接入远程隧道。[规则与诊断](docs/network.md)

## 自己动手安装

先装好 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后运行。这里以 Codex 为例：

```sh
uv tool install --python 3.12 https://github.com/0error0warning/stu-mcp/releases/download/v0.6.0/stu_mcp-0.6.0-py3-none-any.whl
stu-mcp connect codex --apply
```

第二行换成你用的客户端，比如 `claude-code` 或 `cursor`。其他客户端、豆包工作和 Skill 的接法放在[这里](docs/clients.md)。已经装过旧版的话，第一条加上 `--force`，再重新接入、重启或重新加载 MCP；保留原来的用户数据和配置。详细步骤见[升级说明](docs/install.md#从旧版升级)。

MCP 接入和技能安装分别处理。随包的[课表导出技能](docs/timetable.md)组织校历核对和文件转换，完整学期课表仍需另行取得和核实。技能 ZIP 是可选资源包，生成后仍需按客户端支持的方式安装，不会自动让当前 agent 加载技能。

v0.6.0 支持本机 stdio 与个人服务器私有 Streamable HTTP，共用一套工具。认证默认走 HTTP 和本人终端；雨课堂由本人手机确认官方二维码，对分易沿用原微信回调。默认安装和 Docker 模板不需要桌面或 Chromium，Playwright 仅作为显式浏览器兼容依赖。服务器不必安装 agent 或模型服务，详见[服务器说明](docs/server.md)和[认证流程](docs/authentication.md)。

在运行 MCP 的主机终端执行 `stu-mcp login mystu`、`stu-mcp login yuketang` 或 `stu-mcp login repair`；密码和动态码隐藏输入，不交给 agent。会话及个人缓存加密保存，WebVPN 可另行明确配置按需自动重登。设置页默认提供宿主 CLI 指引；需原浏览器时显式选择 `--browser`。客户端到 MCP 和 MCP 到学校是两段网络，连上服务器不代表服务器能访问校园网。[版本与登录说明](docs/install.md) · [存储与隐私](SECURITY.md)

本版包含对分易后台和轻量本地网页：选课、启停监听、查询签到结果，微信回调可在宿主终端或本地网页完成。MCP 退出后后台继续运行，状态明确区分未启动、未登录、已暂停、监听中和查询异常。支持持续监听；电脑需保持运行和联网。新的课堂自动提交仍待实测。[安装与用法](docs/checkin.md)

宿舍报修使用独立 HTTP 会话填表，完整展示实际表单，等你明确确认后只提交一次。随后核对新增单据及详情，返回单号、处理状态和核对时间；结果未知时只读查单。草稿留在进程内存，登录会话独立加密保存。当前适配桑浦山学生社区；新版真实登录和填表预览已核验，正式提交仍由合成与回环测试覆盖，没有为验收额外建单。校园网报修是另一套入口。[使用与验证范围](docs/repair.md)

教务当前可用 `stu-mcp login jw --allow-http-callback` 明确允许本次官方票据回调，密码始终发至 HTTPS SSO。OA 的 HTTP 8118 兼容是另一项默认关闭的本地选择，不能默默开启或借用教务许可；详见[认证说明](docs/authentication.md)。从 0.4.1 之前升级需重新登录并刷新教务。

喜欢用终端的话，也可以直接查：

```sh
stu-mcp refresh oa --limit 20
stu-mcp query notice --source oa --search 竞赛
stu-mcp huyou search 选课
```

## 还在慢慢补

当前版本为 **[v0.6.0 学生预览版](https://github.com/0error0warning/stu-mcp/releases/tag/v0.6.0)**。本版把默认登录改为纯 HTTP CLI，加入个人服务器接入与轻量容器模板，保留 38 项工具的名称和输入输出接口。继续以 GitHub prerelease 发布，不把预览版称作稳定版。[发行说明](docs/releases/v0.6.0.md) · [最近更新](CHANGELOG.md)

正式 HTTP 适配器已实测教务、MySTU 的身份与课程、ELC/Campus 的部分业务、雨课堂课程活动，以及报修登录和完整预览。WebVPN 的密码、动态口令和资源目录通过；受保护 OA 正文及自然过期续登尚未通过本轮验收。发行 CI 包含跨平台测试和默认镜像离线检查，容器内学校业务、跨机接入、更多账号和真实新报修提交仍分别待验，详见[验证记录](docs/verification.md)。

如果你用起来了，或者发现某个入口读不动了，欢迎开 issue 聊聊。告诉我用的版本、卡在哪一步就很有帮助，别把真实成绩、密码或登录凭据贴进去。

想自己改也可以：

```sh
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run stu-mcp setup
uv run stu-checkin
uv build
```

[文档目录](docs/README.md) · [更新记录](CHANGELOG.md) · [代码结构](docs/architecture.md) · [代码来源](docs/provenance.json)

MIT 许可。个人折腾的小项目，和学校官方没有关系。
