"""Capabilities are independent of authentication and collection."""
from dataclasses import dataclass

JW_LOGIN_URL = "https://jw.stu.edu.cn/jwglxt/xtgl/login_slogin.html"
# The current SSO entry still serves the student query modules under /jsxsd.
JW_BASE = "https://jw.stu.edu.cn/jsxsd"
JW_HOME = JW_BASE + "/framework/xsMainV.htmlx"
SMARTCARD_BASE = "http://smartcard.stu.edu.cn"


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    features: tuple[str, ...]
    login_url: str | None = None
    hosts: tuple[str, ...] = ()
    session: str | None = None


SOURCES = {
    "public": Source("public", "学校公开网站", ("通知", "活动", "校园服务入口"),
                     hosts=("www.stu.edu.cn", "xsc.stu.edu.cn")),
    "oa": Source("oa", "OA 通知", ("通知列表", "正文", "附件文字"),
                 "https://webvpn.stu.edu.cn/portal/#!/service",
                 ("oa.stu.edu.cn", "webvpn.stu.edu.cn", "oa-stu-edu-cn.webvpn.stu.edu.cn"), "webvpn"),
    "jw": Source("jw", "教务系统", ("成绩", "加权统计", "考试安排", "本人理论课表"),
                 JW_LOGIN_URL, ("jw.stu.edu.cn", "sso.stu.edu.cn"), "jw"),
    "med_jw": Source("med_jw", "医学院教务", ("本人当前学期课表（待真实账号验收）",),
                     "https://jwgl.med.stu.edu.cn/app/", ("jwgl.med.stu.edu.cn",), "med_jw"),
    "mystu": Source("mystu", "MySTU", ("课程", "作业", "Moodle / ELC 活动", "个人日程"),
                    "https://my.stu.edu.cn/discussion/my-courses",
                    ("my.stu.edu.cn", "sso.stu.edu.cn"), "mystu"),
    "yuketang": Source("yuketang", "雨课堂", ("课程", "作业", "课程公告"),
                      "https://changjiang.yuketang.cn/", ("changjiang.yuketang.cn",), "yuketang"),
    "huyou": Source("huyou", "狐友 · 汕大树洞", ("圈内关键词搜索", "公开帖子", "评论和回复"),
                    hosts=("cs-ol.sns.sohu.com", "hy.sns.sohu.com")),
    "charging": Source("charging", "校园充电设备 · 第三方平台", ("按位置查询设备", "空闲插座", "逐口状态"),
                       hosts=("wx.isfdz.com",)),
    "smartcard": Source("smartcard", "一卡通本人查询", ("卡概况与余额", "本人历史流水"),
                        SMARTCARD_BASE + "/homeLogin.action", ("smartcard.stu.edu.cn",), "smartcard"),
}

PUBLIC_LISTINGS = (
    ("学校要闻", "https://www.stu.edu.cn/xwzx/zxyw.htm"),
    ("综合新闻", "https://www.stu.edu.cn/xwzx/zhxw.htm"),
    ("活动预告", "https://www.stu.edu.cn/xwzx/hdyg.htm"),
    ("学生通知", "https://xsc.stu.edu.cn/NoticeList.aspx?NewsTypeID=3"),
)

OA_DIRECT = "http://oa.stu.edu.cn"
OA_SECURE_PROXY = "https://oa-stu-edu-cn.webvpn.stu.edu.cn"
MYSTU_BASE = "https://my.stu.edu.cn"
MYSTU_API = MYSTU_BASE + "/v3/services/api"
YUKETANG_BASE = "https://changjiang.yuketang.cn"
