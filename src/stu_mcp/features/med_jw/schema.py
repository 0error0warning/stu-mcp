"""Fixed medical-campus routes and the timetable contract ported from STU-APP.

Routes and field names come from the 2026-10-29 application investigation and
the subsequent APP parser. Synthetic fixtures validate this implementation;
they do not establish current school availability or first-login acceptance.
Only the current timetable is exposed: its request has no semester selector.
"""

MED_JW_SOURCE = "med_jw"
MED_JW_SCHEMA_VERSION = 1
MED_JW_BASE = "https://jwgl.med.stu.edu.cn"
MED_JW_API = MED_JW_BASE + "/dev-api/appapi"
MED_JW_SSO_BASE = "https://sso.med.stu.edu.cn"
MED_JW_TOKEN_HEADER = "token"

MED_JW_TIMETABLE_PATH = "/dev-api/appapi/Studentkb/index"
MED_JW_INFO_PATH = "/dev-api/appapi/getInfo"
MED_JW_LOGIN_PATH = "/dev-api/appapi/applogin"
MED_JW_CAPTCHA_PATH = "/dev-api/appapi/captcha/getCaptchaCode"
MED_JW_TIMETABLE_URL = MED_JW_BASE + MED_JW_TIMETABLE_PATH
MED_JW_INFO_URL = MED_JW_BASE + MED_JW_INFO_PATH
MED_JW_LOGIN_URL = MED_JW_BASE + MED_JW_LOGIN_PATH
MED_JW_CAPTCHA_URL = MED_JW_BASE + MED_JW_CAPTCHA_PATH
MED_JW_TIMETABLE_BODY = {"zc": "all", "jc": "", "teadm": ""}

# Authentication has its own transport policy; login is not a read route.
MED_JW_READ_ROUTES = frozenset({
    ("GET", MED_JW_INFO_PATH),
    ("POST", MED_JW_TIMETABLE_PATH),
})

# Public key embedded in the school's application, not an application secret.
MED_JW_PUBLIC_KEY_B64 = (
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAKoR8mX0rGKLqzcWmOzbfj64K8ZIgOdH"
    "nzkXSOVOZbFu/TJhZ7rFAN+eaGkl3C4buccQd/EjEsj9ir7ijT7h96MCAwEAAQ=="
)

MED_JW_MAX_WEEKS = 60
MED_JW_MAX_PERIOD = 30
MED_JW_MAX_ROWS = 10000
MED_JW_MAX_JSON_BYTES = 4 * 1024 * 1024
MED_JW_MAX_TEXT = 2000
