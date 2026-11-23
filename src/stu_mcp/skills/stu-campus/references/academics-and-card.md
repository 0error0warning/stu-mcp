# 学业、课表与一卡通

## 教务成绩、考试与主校区课表（`jw`）

- 成绩与考试先在宿主完成学校统一账号（`jw`）登录并调用 `refresh_source(source="jw")`。
- 用 `get_grades(query=..., limit=..., offset=...)` 查成绩缓存，用 `get_exams(...)` 查考试安排（时间保留学校原文，以学校页面为准），用 `academic_summary(semester="")` 计算已缓存全部成绩的学分加权均分与绩点；若存在 `scan_capped=true` 或 `total_count_is_lower_bound=true`，标明统计仅覆盖部分缓存且不替代学校官方认定。
- 读取本人主校区理论课表调用 `get_academic_timetable(semester="")`（按需联网，复用 `jw` 会话，不写入课程或日程缓存；省略 `semester` 读取学校表单当前选中学期并返回真实可选学期列表）。
- `get_academic_timetable` 仅覆盖本人理论课表（含全周次、未排课与 `pending` 待核对项），不覆盖实验课、目标学期最新有效校历、节次实际时刻和 OA 专项调课。如需导出 WakeUp CSV 或 Google/Outlook 可导入的 ICS，引导用户使用随包独立的 **`stu-timetable-export`** 技能核对校历与作息后转换。不得将 `get_courses`、`get_schedule` 或 `get_exams` 当作完整学期课表。

## 课程、作业、资料与日程（`mystu` / `yuketang`）

- MySTU 与雨课堂各自独立保存会话；查询前按需刷新对应来源。
- 调用 `get_courses(source=..., query=..., limit=..., offset=...)`、`get_tasks(...)`、`get_course_resources(...)` 读取课程库存（最新可用学期）、作业/测验截止时间、学校提交状态与资料链接；`source` 支持 `all`、`mystu`、`yuketang`。
- 调用 `get_schedule(query=..., limit=..., offset=...)` 读取 MySTU 个人日程缓存（刷新窗口为过去 7 天至未来 31 天）。
- `set_task_status(item_id, status)`（`todo`、`done`、`ignored`）仅修改本机待办状态，与学校提交状态分开，不会向学校提交或修改作业。

## 本人一卡通只读查询（`smartcard`）

- 一卡通使用独立查询密码与正常图片验证码，不属于学校 SSO/CAS 统一账号；官方入口为固定明文 HTTP 地址。缺登录时引导本人在私密设置页或宿主终端运行 `stu-mcp login smartcard` 完成认证，不借用统一账号密码，不读取或保存查询密码。
- 调用 `get_campus_card()` 按需读取卡概况、余额与卡状态（不写缓存）。保留 `balance`（卡余额）与 `balance_breakdown` 中的当前过渡余额、上次过渡余额各自含义，不得相加推断可用余额。
- 调用 `get_campus_card_transactions(start_date, end_date, transaction_type="")` 查询学校时间 `YYYY-MM-DD` 历史流水，单次最多 30 天；`transaction_type` 留空为全部，或选用来源返回的 `available_transaction_types` 选项。保留上游交易类别，不将扣款、补助或转账混作餐饮消费，并按 `coverage` 与 `pending` 报告分页或续读完整性。本组工具不办理挂失、充值或改密。
