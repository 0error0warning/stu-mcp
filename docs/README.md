# 文档目录

发行安装说明对应 **v0.7.6 学生预览版**，新增医学院当前学期课表试验能力，沿用共用认证、个人服务器接入与按需更新。安装见[安装说明](install.md)，DSH 界面见[插件安装](../integrations/dsh/README.md)，单命令升级见[更新说明](updates.md)；版本功能和真实验收范围分别记录在发行说明与验证索引中。

v0.7.1 提供统一账号 `login school`、配置分组能力目录和私密网页 HTTP 认证。本人可在自己的浏览器或真实终端完成交互，两者共用认证核心，MCP 不接收认证输入；用法见[配置与服务总表](campus-services.md)，检查范围见[本轮记录](verification/2026-10-23-private-setup.md)。

| 用途 | 文档 |
| --- | --- |
| 安装、升级、登录 | [安装说明](install.md)、[更新说明](updates.md)、[客户端接入](clients.md) |
| DeepSeek Harness（DSH）接入与跨 agent 兼容 | [已确定的低维护成本方案](deepseek-harness.md) |
| 个人服务器、私有 HTTP 与无桌面登录 | [服务器说明](server.md)、[容器模板](server-container.md) |
| 狐友公开讨论 | [狐友查询](huyou.md) |
| 微信公众号公开文章（源码新增） | [免登录文章读取与失败状态](wechat-articles.md) |
| 充电设备状态 | [充电查询](charging.md)、[平台接口证据](charging-platform.md) |
| 外卖目录、配送批次与选餐（实验） | [外卖查询](takeout.md) |
| 对分易网页、监听与 MCP | [对分易后台](checkin.md) |
| 最近更新与实测范围 | [更新记录](../CHANGELOG.md)、[验证索引与历史归档](verification.md) |
| 代码结构与校园协议 | [架构](architecture.md)、[校园协议核验](campus-protocols.md) |
| 模块职责、现有登录、成功证明与状态归属 | [当前认证与会话边界](authentication.md) |
| 学校网页改版、依赖方向与缓存完整性 | [来源维护](source-adapters.md) |
| 充电/狐友专属契约与后续审查 | [第三方适配](third-party-adapters.md) |
| 一卡通余额、卡状态及本人历史流水 | [一卡通查询](smartcard.md) |
| 本人理论课表读取、既有导出技能与资源分发 | [使用与范围](timetable.md) |
| 教务成绩／考试／课表解析与学期选择 | [教务适配](academic.md) |
| 医学院当前学期课表（试验） | [接入范围与验证边界](medical-jw.md) |
| 雨课堂课程、活动/公告与字段变化 | [雨课堂适配](yuketang.md) |
| 配置登录能用什么、学校服务入口与接入缺口 | [配置与服务总表](campus-services.md)、[导航与官方入口普查](verification/2026-10-22-campus-entries.md) |
| 未接入入口的功能、认证、接口与调查缺口 | [10/23 协议调查索引](investigation/2026-10-23/README.md) |
| 逐项接入进度、后续馆藏及邮箱授权方案 | [功能接入方案](feature-expansion-plan.md) |
| 桑浦山宿舍报修预览、确认和提交 | [报修流程](repair.md) |
| 网络访问与排障 | [单服务连接诊断](network.md)、[学校入口批量检测](network-audit.md) |
| 数据和代码来源 | [安全与隐私](../SECURITY.md)、[来源清单](provenance.json) |

开发检查在仓库根目录执行：

```sh
uv sync --locked --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
uv run --extra dev python scripts/check_installed_runtime.py
```

文档按用途维护：架构描述当前模块边界，来源适配描述共同维护契约，功能文档描述使用方法与专属行为；`verification/` 按主题和日期保留证据、失败及未验收项，更新记录只概述版本变化。旧 `timetable-plan.md` 保留跳转，规划内容集中在 `timetable.md`；技能内部步骤与官方文档入口以技能源文件及参考资料为准。

`src/stu_mcp` 是 MCP/CLI、按需校园查询和本地文件转换；`src/stu_checkin` 是独立签到进程及网页。`tests/checkin_worker` 保存后台合成测试，`tests/test_checkin_integration.py` 验证共享进程与状态。上游适配代码单独放在 `src/stu_checkin/vendor`，保留来源和许可说明。

真实个人页面、凭据、缓存及本机诊断回执留在 Git 外。自动化检查使用合成账号；实际课堂签到和账号登录的结论只以验证记录中的业务证据为准。
