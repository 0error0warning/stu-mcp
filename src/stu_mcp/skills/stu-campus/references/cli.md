# 本机命令接入（无原生 MCP 时使用）

本文件仅用于**未连接原生 MCP、通过本机命令运行 `stu-mcp`** 的客户端（如豆包工作、`generic-cli`）。具体业务规则、分页语义、隐私与报修确认要求，仍按 [主指南](../SKILL.md) 读取对应的场景参考。

## 启动前缀与运行边界

- 若存在随包 `runtime.json`，读取其中的 `command` 与 `args` 作为命令前缀，按参数数组拼接下列子命令执行；禁止将路径或用户输入拼成 shell 字符串。先执行 `--version` 与 `status --compact` 验证本机权限。
- 无 `runtime.json` 时检查本机 `stu-mcp --version`；未安装见 [官方安装说明](https://github.com/0error0warning/stu-mcp/blob/main/docs/install.md)。
- 若当前环境无权访问本机命令，直接报告执行限制，不上传用户数据目录或凭据。`runtime.json` 仅作本机入口，不自动建立远程 HTTP 连接。

## CLI 命令映射

| 用途 | 命令与参数（`\|` 表示选一个值） |
| --- | --- |
| 能力、登录与缓存状态 | `status [--source SCOPE] [--compact]` |
| 刷新来源 | `refresh public\|oa\|jw\|mystu\|yuketang [--limit 20] [--semester …]` |
| 查询本地缓存 | `query notice\|grade\|exam\|course\|task\|resource\|event\|service\|post [--source …] [--search …] [--limit 20] [--offset 0]` |
| 通知正文与附件 | `notice ITEM_ID [--refresh] [--offset 0] [--max-chars 8000]` · `attachment ITEM_ID [--index 0]` |
| 成绩统计与课表 | `academic-summary [--semester …]` · `timetable [--semester …] [--source jw\|med_jw]`（医学院只支持当前学期，不传 `--semester`） |
| 一卡通（只读） | `card` · `card-transactions --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--transaction-type …]` |
| 狐友公开讨论 | `huyou search 原问题 --keyword 短词 [--keyword …] [--circle-id ID] [--with-discussion] [--local]` · `huyou detail FEED_ID [--local]` · `huyou circles [关键词]` |
| 充电设备与插座 | `charging overview [位置] [--limit 4] [--offset 0] [--local]` · `charging device DEVICE_CODE [--local]` |
| STU 外卖查询 | `takeout status` · `takeout shops [关键词] [--area-id ID] [--meal-period …] [--category-id ID]` · `takeout meal-shops --area-id ID --meal-period 餐段 [--date YYYY-MM-DD] [--scan-limit 5] [--offset 0] [--include-closed] [--refresh]` · `takeout shop SHOP_ID` · `takeout slots SHOP_ID [--date YYYY-MM-DD] [--meal-period …] [--only-open] [--refresh]` · `takeout menu SHOP_ID [--query …] [--category-id …]` |
| 服务与网络诊断 | `network [--service-id …] [--location-hint unknown\|campus\|off_campus] [--check-login\|--anonymous-only] [--compare-proxy] [--refresh]` · `network-audit [--location-hint …] [--compare-public-dns] [--refresh]` |
| 宿舍报修草稿和演练 | `repair plan [--fields-file PATH]` · `repair drill [--fields-file PATH]` · `repair preview --browser [--fields-file PATH]`。业务字段从标准输入或 JSON 文件读取。演练展示完整表单后退出。 |
| 宿舍报修提交 | 仅在用户明确要求提交时使用 `repair drill --fields-file PATH --submit`。业务字段放在本机 JSON 文件，真实终端留给本人核对完整预览并输入“确认提交”。 |
| 本地待办与学生资料 | `task-status ITEM_ID todo\|done\|ignored` · `profile [--college …] [--major …] [--entry-year …] [--interests …]` |
| 更新与课表导出包 | `update --check` · `update` · `skill-export --skill stu-timetable-export --apply` |

## 本人终端认证与范围边界

- 以下涉及个人凭据或回调，**仅引导本人在自己的真实 TTY 或浏览器执行**，agent 不索要、代填或通过管道/环境变量传入：`setup`、`login school [--services jw mystu repair] [--allow-http-callback] [--reauthenticate]`、`login jw|mystu|yuketang|webvpn|duifene|repair|smartcard|med_jw`、`webvpn-auto configure|status|remove`、`takeout configure --file PATH`、`takeout remove`、`logout jw|mystu|yuketang|webvpn|repair|smartcard|med_jw`。
- 当前没有对应 `stu-mcp` CLI 子命令的 MCP 专属功能包括：`get_wechat_article`（公众号文章读取）、`report_feedback`（反馈预览发送）、`get_takeout_product` 与 `prepare_takeout_selection`（商品规格与选餐清单）、`set_student_profile(clear_fields=...)`（清空资料字段），以及 MCP 交互式对分易控制工具（`get_checkin_status`、`start_checkin_monitor` 等由独立本机 `stu-checkin` 服务及网页提供）。在仅 CLI 环境下遇到这些需求时如实说明限制。
