# 文档目录

已发布版本为 v0.4.1；当前源码为 0.5.0.dev0。开发版新增功能和真实验收范围分别记录，尚未发布新安装包。

| 用途 | 文档 |
| --- | --- |
| 安装、升级、登录 | [安装说明](install.md)、[客户端接入](clients.md) |
| 狐友公开讨论 | [狐友查询](huyou.md) |
| 充电设备状态 | [充电查询](charging.md)、[平台接口证据](charging-platform.md) |
| 对分易网页、监听与 MCP | [对分易后台](checkin.md) |
| 最近更新与实测范围 | [更新记录](../CHANGELOG.md)、[验证记录](verification.md) |
| 代码结构与校园协议 | [架构](architecture.md)、[校园协议核验](campus-protocols.md) |
| 数据和代码来源 | [安全与隐私](../SECURITY.md)、[来源清单](provenance.json) |

开发检查在仓库根目录执行：

```sh
uv sync --locked --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
uv run --extra dev python scripts/check_installed_runtime.py
```

`src/stu_mcp` 是 MCP/CLI 和按需校园查询；`src/stu_checkin` 是独立签到进程及网页。`tests/checkin_worker` 保存后台合成测试，`tests/test_checkin_integration.py` 验证共享进程与状态。上游适配代码单独放在 `src/stu_checkin/vendor`，保留来源和许可说明。

真实个人页面、凭据、缓存及本机诊断回执留在 Git 外。自动化检查使用合成账号；实际课堂签到和账号登录的结论只以验证记录中的业务证据为准。
