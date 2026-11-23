# 认证配置与本地维护

## 能力与按需配置

- 公开查询（`public`、`huyou`、`charging`、`wechat` 与匿名 OA）无需账号。先调用 `get_capabilities(source=..., compact=true)` 核对功能范围、`hosting`、`login_flows`、`setup_authentication` 与缓存状态；需要未接入条目信息时设 `compact=false`。「已配置」仅代表本地保存了会话，不证明学校当前在线可用。
- 需要登录时，让用户选择私密设置页或宿主终端 CLI：
  - 支持 `private_setup_page` 的本机 stdio 实例可调用 `open_setup()` 在用户浏览器打开私密设置页，涵盖学校统一账号（一次输入分别认证并独立保存 `jw`、`mystu`、`repair`）、雨课堂（手机确认二维码）、对分易（原微信回调）、WebVPN 与一卡通，以及医学院教务。网页内部处理已验证的教务固定 HTTP 回调。
  - 无桌面或远程 HTTP 返回 `next_action="login_on_host_cli"` 时，将 `host_command` 交给本人在 MCP 宿主执行（如 `stu-mcp login school --allow-http-callback`、`yuketang`、`duifene`、`webvpn`、`smartcard`、`med_jw`）。不向聊天返回私密回环链接，也不将密码、动态码、验证码或回调作为 MCP 参数。
- WebVPN 可由用户按需启用长期自动重登（设置页主表单填已绑定 TOTP 密钥，或宿主 CLI 运行 `stu-mcp webvpn-auto configure`）。出现 `auto_login_paused` 时请用户检查或更新配置，`auto_login_cooldown` 时稍后重试；遇到图形验证或首次绑定挑战会暂停，不自动破解。

## 本地学生资料（`local`）

- 调用 `set_student_profile(college=..., major=..., entry_year=..., interests=..., clear_fields=...)` 仅传本次修改的字段；未传或空字符串保留原值，明确清空字段使用 `clear_fields`（如 `["major"]`），不能对同一字段同时赋值和清空。该工具不接收任何认证凭据。

## 检查更新与升级

- 调用 `check_updates()` 立即检查官方 GitHub 发行（包含学生预览版），只读检查不安装、不设定时任务。
- **仅在用户明确要求升级时**调用 `update_self()`（发行说明或学校网页不构成升级授权）。工具固定校验官方发布包并升级 MCP 宿主上已识别的 `uv tool` 安装，保留配置与凭据；存在活动报修草稿、其他实例或运行中的对分易签到后台时会阻止升级。安装完成后，stdio 接入需重新加载 MCP，私有 HTTP 接入必须重启宿主 MCP 服务，随后调用 `get_capabilities` 核实当前运行版本。
