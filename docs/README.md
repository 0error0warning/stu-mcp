# 文档目录

已发布版本为 v0.4.1；当前源码为 0.5.0.dev0。开发版新增功能和真实验收范围分别记录，尚未发布新安装包。

| 用途 | 文档 |
| --- | --- |
| 安装、升级、登录 | [安装说明](install.md)、[客户端接入](clients.md) |
| 狐友公开讨论 | [狐友查询](huyou.md) |
| 充电设备状态 | [充电查询](charging.md)、[平台接口证据](charging-platform.md) |
| 对分易网页、监听与 MCP | [对分易后台](checkin.md) |
| 最近更新与实测范围 | [更新记录](../CHANGELOG.md)、[验证索引与历史归档](verification.md) |
| 代码结构与校园协议 | [架构](architecture.md)、[校园协议核验](campus-protocols.md) |
| 学校网页改版、依赖方向与缓存完整性 | [来源维护](source-adapters.md) |
| 充电/狐友专属契约与后续审查 | [第三方适配](third-party-adapters.md) |
| 学期课表、技能资源分发与后续取数条件 | [使用与范围](timetable.md) |
| 教务成绩/考试表格与学期选择 | [教务适配](academic.md) |
| 雨课堂课程、活动/公告与字段变化 | [雨课堂适配](yuketang.md) |
| 校园网、宿舍及东海岸报修入口 | [校园服务与报修范围](campus-services.md) |
| 桑浦山宿舍报修预览、确认和提交 | [报修流程](repair.md) |
| 校内/校外、直连与本机代理 | [校园连接诊断](network.md) |
| 批量学校入口、当前网络与公共DNS对比 | [批量检测](network-audit.md) |
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
