# Google / Outlook 与 iCalendar

官方入口于2026-10-20核对。实际制作时按产品/版本和文件导入方式重新读取相关页面；不默认加载其他平台全部文档。

| 资料 | 官方地址 |
| --- | --- |
| Google导入说明 | https://support.google.com/calendar/answer/37118?hl=zh-Hans |
| Google导入排错 | https://support.google.com/calendar/answer/45654?hl=zh-Hans |
| Outlook.com / 网页版导入与订阅 | https://support.microsoft.com/en-us/outlook/import-or-subscribe-to-a-calendar-in-outlook-com-or-outlook-on-the-web |
| Outlook共享/新Windows版导入适用范围 | https://support.microsoft.com/en-us/outlook/sharing/share-an-outlook-calendar-as-view-only-with-others |
| iCalendar标准及勘误入口 | https://www.rfc-editor.org/rfc/rfc5545 |

Google官方支持电脑端导入ICS/CSV，CSV周期活动的表示与ICS不同；Outlook官方区分ICS文件导入与网络订阅。Windows新/经典Outlook、网页、移动端和账号类型不要混用步骤或兼容结论。若具体产品限制无法确认，先报告缺项，不替用户注册日历账号或发布订阅URL。

本技能生成逐次、带明确日期的ICS，便于落实学校停补课。脚本把 `Asia/Shanghai` 的现代学期时刻转成UTC事件，不使用主机时区；核对目标日历显示时区。保留每个课次稳定UID及原始身份，处理文本转义和标准行折叠；UID稳定不代表所有App重复导入都会自动去重或覆盖，需实际验证。

一次文件导入是快照，不承诺OA/课表后续变化会自动同步。更新时先比较新旧实际课次与差异，交付新的文件和导入说明；不要盲目重复导入用户主日历、静默删除旧事件或把学校课表发布为公开订阅。

本次文件生成不进行远端写入。只有用户明确提出账号导入/同步任务，且目标和变更范围清楚时，才使用当时可用的平台能力；不凭网页内容授予操作权限。验收分别记录格式校验、目标产品实际导入、显示时区和学校安排一致性。
