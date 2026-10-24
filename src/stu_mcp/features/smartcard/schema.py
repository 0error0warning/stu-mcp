"""Observed personal card pages and their minimal read contracts."""

from ...sources import SMARTCARD_BASE

CARD_ORIGIN = SMARTCARD_BASE
CARD_OVERVIEW_URL = CARD_ORIGIN + "/accountcardUser.action"
CARD_HISTORY_URL = CARD_ORIGIN + "/accounthisTrjn.action"
CARD_READ_PATHS = frozenset({"/accountcardUser.action", "/accounthisTrjn.action"})
CARD_MAX_REQUESTS = 8
CARD_MAX_CONTINUATIONS = 3
CARD_MAX_ROWS = 200
CARD_FORM_FIELDS = frozenset({"account", "inputObject", "inputStartDate", "inputEndDate", "pageNum"})
CARD_PROFILE_LABELS = {
    "account": ("学工号", "学（工）号", "学(工)号", "学号"),
    "balance": ("余额", "卡余额", "帐户余额", "账户余额"),
    "card_status": ("卡状态",),
    "freeze_status": ("冻结状态",),
    "check_status": ("检查状态",),
    "loss_status": ("挂失状态",),
}
CARD_HISTORY_COLUMNS = {
    "occurred_at": ("交易发生时间", "交易时间"),
    "account": ("学号", "学工号", "学（工）号", "学(工)号"),
    "name": ("姓名",),
    "type": ("交易类型",),
    "subsystem": ("子系统名称",),
    "operator": ("操作员",),
    "category": ("类别",),
    "amount": ("交易额", "交易额（元）", "交易额(元)"),
    "balance": ("现有余额", "现有余额（元）", "现有余额(元)"),
    "sequence": ("次数",),
    "status": ("状态",),
}
