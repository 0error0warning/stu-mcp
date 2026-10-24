# 已核对输入与本地转换

脚本是 Python 3.11+ 标准库程序；不读取网络、MCP、账号或环境中的时区。它校验并处理 agent 已核对的声明，不能自行证明校历是最新、课表完整或目标 App 已导入。

## JSON v1

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 整数1 |
| `semester` | 已确认的学期标识；不从雨课堂整数term猜教务语义 |
| `calendar` | `semester`须一致；`version`为实际核对版本；`week1_monday`为课表第1教学周星期一ISO日期；`weeks`为明确周数；`source_url`、带时区的`checked_at`、布尔`latest_verified` |
| `timetable` | 完整课表的`source_url`、带时区`checked_at`、布尔`complete` |
| `periods` | `[{number:1,start:"HH:MM",end:"HH:MM"}, ...]`，按适用时刻表，不重叠 |
| `periods_source` | 可选，独立节次表的`source_url,checked_at`；未提供时只声明节次证据继承课表来源，不伪造已读另一份作息表 |
| `courses` | `[{id,title,teacher?,location?,meetings:[...]}]`；不同课程/教学班有不同稳定身份 |
| 每个`meeting` | `{id,weekday,weeks,periods}`，星期1–7，周次为显式整数集合，节次为连续整数集合；离散节次拆成多组meeting。可选`teacher,location`覆盖课程对应值，省略则继承，明确空值表示未知 |
| `oa` | 不提供时默认`{enabled:false,status:"not_checked"}`；开启时为`{enabled:true,status:"checked",scope,source_url,checked_at}` |
| `adjustments` | 可省略；只放已解释清楚、具有来源和核查时间的调整 |
| `pending` | 可省略，待核实说明字符串列表；非空则不生成正式文件 |

学校来源须为稳定官方`stu.edu.cn`域名URL，不含账号、密码、Cookie、ticket、token或会话参数。URL仅记录依据，脚本不访问。真实个人输入与导出应保留在用户本机，不作为仓库fixture或公开附件。

所有已知字段严格类型校验，布尔不能当数字。支持现代学期2000–2100年，使用明确UTC+08并标记`Asia/Shanghai`，不依赖Windows是否安装tzdata。若未来适用时区规则变动，应先更新转换器，不以主机设置替代。

`latest_verified=false`、`timetable.complete=false`或非空`pending`会产生阻塞报告。设true必须有本次实际取证，不能为了运行成功改标志。OA关闭不制造待核实阻塞；报告明确标注未检索。OA已开启但未完成时先说明检索缺口，不伪造`checked`输入。

## 从教务读取结果组装

`get_academic_timetable` / `stu-mcp timetable` 负责本人理论课表取数，转换器仍只接收本页的 JSON v1。复用返回的 `semester` 与 `courses`，包括课程和每组安排的稳定 `id`；不要重新按行号编号、按课程名合并或再写一份周次解析。

把返回的 `source_url`、`checked_at` 放进 `timetable`，保留真正的读取时间。查询的 `coverage` 只说明理论课表的读取范围；`timetable.complete` 是本次导出范围已核对的声明。`unarranged` 中没有上课安排的课程必须说明，返回的 `pending` 要带入输入，待取得依据后再处理；不能为了通过转换器而删除缺口。转换器会忽略未知字段，仅附上 `unarranged` 或 `coverage` 不会自动阻止漏课导出。

另行读取目标学期最新有效校历和适用作息，填写 `calendar`、`periods` 及 `periods_source`；理论课表查询不提供这些证明，也不能证明实验课已覆盖。若用户只要求理论课，明确保留该范围；若要求全部课程，补齐实验课等来源后才能确认完整。校历与课表周次需对应，同名学期不能代替周次基准核对。

完成这些核对后仍执行同一个 `scripts/build_timetable.py`，不用另一个转换工具。旧版本无查询入口时，用户提供的课表继续按同一 JSON v1 处理。

## 调整的精确语义

每项共同字段：`id,kind,date,source_url,checked_at`。选择的是**未调整的原课次**，不能依靠列表顺序形成隐含调整链。同一原课次受多条规则影响时应先在取证阶段消歧；脚本拒绝冲突。

- `cancel`：取消`date`上的原课次。可用`course_id`、`meeting_id`缩小范围；meeting范围同时需要course。没有匹配课次会报错，不能以无作用规则充当已调整。
- `move`：把`date`选中原课次移到`to_date`，取消原发生日期；可按course/meeting缩小范围。目标日原有课程保留，冲突会进入待核实报告。
- `replace_day`：目标`date`整日改用`teaching_date`的原课程，目标日原课取消。必须明确`source_action="keep"`或`"cancel"`，分别表示来源日期原课保留或取消。不得省略、猜测，且此规则不接受course/meeting局部范围。

例如通知“周六按周一课表上课”，还要确认具体哪一个教学周的周一，以及原周一是保留还是取消；不能只按weekday复制全学期的周一。仅一门课改期应使用局部`move`，不要用全日替换。

## 运行和输出

```text
python scripts/build_timetable.py --input reviewed.json --output-dir new-export --format all
```

`--input -`从标准输入读JSON；`--format`可为`ics`、`wakeup`、`all`。输出目录须新建或为空，不覆盖之前导出。文件生成是当前任务的本地动作，不向日历账号提交。

- `review.json`：依据和原核查时间、OA状态、原/实际课次数、调整、待核实项、实际课次及各目标状态。
- `schedule.ics`：已核对课次的逐次事件，UTC时刻、稳定UID、来源说明。实际导入状态为`not_performed`。
- `wakeup.csv`：按实际发生日期回算周次/星期，不按课程同名合并。
- `wakeup-settings.json`：周1基准、学期周数和节次时刻，需在实际App中单独设置，不是自动导入设置文件。

退出0表示所请求目标文件已生成；退出2表示输入无效、待核实、阻塞或部分目标不支持，必须读取输出状态。语法/类型/本地读写错误只返回简短诊断，不保证生成review文件；正常结构的未核实输入会生成阻塞的review。

`--format all`可在某目标不支持时保留另一个目标的有效文件，但总体状态为partial。WakeUp实际课次超出已核对教学周网格时不能无损投影，报告不支持，不能静默丢弃该课次。目标App的导入/重复导入/设置是否正确仍需用户或授权的实际界面核验。
