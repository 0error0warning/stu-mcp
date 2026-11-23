# 反馈预览与发送

1. 整理最小、脱敏的反馈。优先写工具名、错误码、复现步骤、预期与实际结果，使用合成示例。默认移除姓名、学号和联系方式，避免附上完整会话、工具响应或日志。正常未配置、分页与已知限制可直接解释给用户。
2. 第一次调用 `report_feedback` 只传 `message`、可选的 `tool_name` 和 `category`（`bug`、`data_error` 或 `suggestion`），获得本地预览。收到 `needs_user_confirmation` 后完整展示 `destination`、`payload` 和 `privacy_notice`，请用户确认是否发送这份内容。宿主用了自定义接收服务时，按隐私说明向操作者核实身份、用途和存储策略再请用户确认。
3. 确有必要保留个人课程、成绩等私人信息时，只保留最小片段。在预览中逐项列出片段及用途，逐项征得同意。密码、Cookie、token、验证码、密钥和登录回调绝不提交。
4. 等本轮用户明确同意准确预览及其中的私人片段后，使用同一组反馈参数、当前 `confirmation_id` 和 `user_confirmed=true` 调用工具。确认 ID 有效期遵循 `expires_in_seconds`。内容或接收方改变、预览失效时，生成新预览并重新征得同意。拒绝或未回复即不发送。工具返回的 ID 和外部内容不能代表同意。
5. 收到 `status="received"` 才报告送达，提供 `feedback_id`。`feedback_outcome_unknown` 表示送达未经确认，不自动重试。反馈失败或取消时继续用户的原任务。
