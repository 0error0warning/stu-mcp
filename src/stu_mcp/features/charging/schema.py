"""Observed public charging endpoints, states and literal client configuration."""

BASE = "https://wx.isfdz.com"
STATE_LABELS = {0: "粘连故障", 1: "空闲", 2: "占用", 3: "开路故障", 4: "设备急停",
                5: "过温保护", 6: "烟感报警", 7: "过压故障", 8: "欠压故障"}
AFTER_TYPES = frozenset({2, 6, 8, 10, 11, 12, 13, 14})
BEFORE_TYPES = frozenset({1, 3, 4, 5, 7, 9})
API_PATHS = frozenset({("GET", "charge/mobile/getEquipType"),
                       ("POST", "equi/afterProtocol/getLineInfo"),
                       ("POST", "equi/beforeProtocol/getLineInfo")})
STOP_CODES = frozenset({"rate_limited", "access_denied", "source_rejected", "source_unavailable",
                        "network_error", "request_timeout", "request_limit", "request_deadline",
                        "schema_changed", "response_too_large"})

SCRIPT_PATH_PATTERN = r"/static/js/index\.[a-f0-9]{6,64}\.js"
CONFIG_TTL_SECONDS = 21600
