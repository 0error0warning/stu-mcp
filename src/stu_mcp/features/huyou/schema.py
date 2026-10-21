"""Fixed, observed anonymous Huyou API contracts and bounded read budgets."""

API_BASE = "https://cs-ol.sns.sohu.com"
WEB_BASE = "https://hy.sns.sohu.com/"
DEFAULT_CIRCLE = "905956136904237440"
APP_VERSION = "6.22.0"
PUBLIC_SIGNING_CONSTANT = "30lh2d011v20d362"
API_PATHS = frozenset({"/circle/search/v20", "/circle/search/feed/v22", "/v7/feeds/show",
                       "/v8/comment/list", "/v8/comment/replylist"})
STOP_CODES = frozenset({"huyou_login_required", "rate_limited", "request_limit", "request_deadline"})


REQUEST_LIMIT = 40
DEADLINE_SECONDS = 45
RESPONSE_BYTES = 2 * 1024 * 1024
SEARCH_PATH = "/circle/search/feed/v22"
CIRCLES_PATH = "/circle/search/v20"
DETAIL_PATH = "/v7/feeds/show"
COMMENTS_PATH = "/v8/comment/list"
REPLIES_PATH = "/v8/comment/replylist"
