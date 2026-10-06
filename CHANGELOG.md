# 更新记录

## 0.4.0 — 2026-10-06（学生预览版）

- 新增狐友匿名圈子搜索、帖子正文、评论和楼中楼回复，提供三项 MCP 工具及对应 CLI / Skill 入口。默认搜索汕大树洞；社区内容独立标记，不混入官方通知。
- 通知列表刷新保留此前获取的正文和附件，单独记录详情获取时间；更换 URL 或认证范围时不沿用旧详情。
- 教务、MySTU、雨课堂与 WebVPN 的手动登录统一核对会话版本。退出会撤销在途登录，旧登录不能覆盖后来切换的账号或清空新账号缓存。
- README、安装 prompt 和发行包统一指向 v0.4.0；升级后重新加载 MCP，使用 Skill 的客户端重新导出并导入技能包。

个人来源的真实学生账号登录及失效恢复、客户端应用内完整接入仍待验收，见[验证记录](docs/verification.md)。

## 历史发行

- [v0.3.1](https://github.com/0error0warning/stu-mcp/releases/tag/v0.3.1)：修复 uv 启动路径、课程范围同步和登录设置页交互。
- [v0.3.0](https://github.com/0error0warning/stu-mcp/releases/tag/v0.3.0)：可选 WebVPN 自动重登。
- [v0.2.0](https://github.com/0error0warning/stu-mcp/releases/tag/v0.2.0)：扩展 agent 客户端适配和本机 Skill。
- [v0.1.0](https://github.com/0error0warning/stu-mcp/releases/tag/v0.1.0)：首个学生预览版。
