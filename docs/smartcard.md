# 一卡通本人查询

v0.7.1提供两项按需只读查询：本人卡概况（余额和卡状态）与指定日期的历史流水。使用独立的 `smartcard` 会话，不属于学校统一账号组；当前没有新增持久缓存、后台任务或统计图工具。

## 本人登录

在 MCP 宿主运行 `stu-mcp setup`，选择「一卡通查询」，或在真实终端执行：

```sh
stu-mcp login smartcard
```

本人输入一卡通查询账号与独立查询密码，并根据官方图片填写验证码。CLI 在终端显示图片，网页使用私密设置页；不需要服务端浏览器，不自动识别或绕过验证码。不把密码、验证码、Cookie、本人 HTML 或回调交给 agent，也不通过命令行参数、环境变量或管道输入。

学校当前官方入口为 [HTTP 一卡通查询](http://smartcard.stu.edu.cn/homeLogin.action)，独立查询密码和会话会经过明文 HTTP，存在网络暴露风险。该例外仅适用于固定一卡通主机和已核验路径；普通学校/CAS 密码、TOTP 仍使用 HTTPS，JW/OA 开关不能授予一卡通权限。不会修改代理、DNS 或证书校验。

只有登录后基本信息页的学工号与本次输入精确匹配，才保存来源隔离的加密会话；查询密码不保存。退出用 `stu-mcp logout smartcard`，只影响本来源；退出或换号期间尚未完成的读取会丢弃。

## 查询与范围

| MCP 工具 | CLI | 含义 |
| --- | --- | --- |
| `get_campus_card()` | `stu-mcp card` | 本人卡余额与可解析的卡状态；不返回证件号码、住址等完整个人资料 |
| `get_campus_card_transactions(start_date, end_date, transaction_type="")` | 下方示例 | 本人历史流水，保留学校原始交易分类及读取范围 |

```sh
stu-mcp card
stu-mcp card-transactions --start-date 2026-10-17 --end-date 2026-10-24
stu-mcp card-transactions --start-date 2026-10-17 --end-date 2026-10-24 --transaction-type 1A
```

日期使用学校时间 `YYYY-MM-DD`，单次最多 30 天；空交易类型为全部，其他值必须来自本次响应的 `available_transaction_types`。`1A` 是当前上游支付宝转账记录分类，示例不会发起转账。扣款、消费、补助、转账分别保留，不能一概当作餐饮消费，也不能仅凭流水金额推出完整月度统计。

概况的 `balance` 仅对应页面「卡余额」；`balance_breakdown` 另列「当前过渡余额」和「上次过渡余额」，保留学校正负号，不相加或猜测可用余额。

先使用已登录页面提供的本人卡账户和类型选项，再走其当前表单、日期及有界续行；`__continue` 等会话参数只在内存使用，不返回原始 action 或图像统计 URL。请求结果带来源、核查时间、HTTP 路线、`cached=false` 及 `coverage`。分页实际合同尚未验证时仅读第一页，并明确 `complete=false`；结构变化、身份不符或登录失效均不当作空记录。

只有上述两项业务已接入。挂失/解挂、充值、改密、限额修改、写操作、统计图、完整个人资料、当日流水与电子账户专属接口不通过这两个工具办理。自动测试使用合成页面；先前临时协议实读保留[原日期和范围](investigation/2026-10-23/smartcard-personal.md)，正式适配器的本人认证、CLI／MCP、全部与分类空态另见[v0.7.1 验收](verification/2026-10-23-v0.7.1.md)，不扩大成其它账号和未验业务成功。
