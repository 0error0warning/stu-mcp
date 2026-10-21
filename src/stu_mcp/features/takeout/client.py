"""Seven catalog/specification reads verified against STU mini-program v21 on 2026-10-21."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

import requests

from ...http_privacy import private_http_logging
from ...runtime import AppError

SOURCE = "takeout"
BASE = "https://applet-api.veding.com"
SHOPS = "/applet/wechat/shop/api/json.jhtml"
DETAIL = "/wechat/applet/shop/detail.jhtml"
MENU = "/applet/wechat/menu/api/json.jhtml"
CATEGORIES = "/applet/wechat/menu/category/api/json.jhtml"
PRODUCT = "/applet/wechat/goods/detail/api/json.jhtml"
SETTINGS = "/applet/goodslist/submit/data/json.jhtml"
PROPERTIES = "/wx/applet/goods/data/list.jhtml"
READS = frozenset({("GET", SHOPS), ("GET", DETAIL), ("POST", MENU), ("POST", CATEGORIES),
                  ("POST", PRODUCT), ("POST", SETTINGS), ("GET", PROPERTIES)})
SALT_INDEXES = (
    8, 19, 20, 34, 46, 53, 49, 31, 49, 27, 20, 59, 43, 26, 22, 28,
    56, 50, 39, 43, 20, 56, 25, 39, 50, 45, 26, 19, 21, 32, 44, 43,
    31, 20, 3, 60, 51, 51, 11, 28, 19, 23, 14, 53, 16, 51, 10, 50,
    17, 60, 48, 53, 48, 58, 44, 26, 22, 49, 35, 48, 40, 1, 32, 20,
    6, 51, 16, 28, 31, 3, 26, 21, 35, 46, 6, 9, 10, 58, 54, 24,
    39, 43, 57, 3, 46, 44, 43, 36, 54, 46, 9, 60, 2, 30, 4, 46,
)


def signed(method: str, path: str, params: dict, config: dict) -> dict:
    if (method, path) not in READS:
        raise AppError("unsupported_takeout_operation", "仅支持已核验的外卖目录读取。", SOURCE)
    outgoing = {key: re.sub("eval|atob", "", str(value), flags=re.IGNORECASE)
                for key, value in params.items() if key != "signature" and value is not None}
    canonical = "".join(f"{key}={value.strip()}&" for key, value in sorted(outgoing.items())
                        if value.strip() not in ("", "undefined", "null"))
    salt = "".join(config["salt"][index] for index in SALT_INDEXES)
    material = method + BASE + path + canonical + "signToken=" + config["signToken"] + "{" + salt + "}"
    outgoing["signature"] = hashlib.md5(material.encode()).hexdigest()
    return outgoing


class TakeoutClient:
    def __init__(self, config: dict):
        self.config = config
        self.http = requests.Session()
        self.http.trust_env = False
        if config.get("proxy"):
            self.http.proxies.update(http=config["proxy"], https=config["proxy"])
        self.http.headers.update(config.get("headers", {}))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def read(self, method: str, path: str, params: dict) -> dict | list:
        common = {key: self.config[key] for key in ("userId", "appletId", "apiToken")}
        params = signed(method, path, {**common, "_api_version_": "3", "requestFromType": "wechatApplet",
            **params, "nonce": secrets.token_hex(8), "timestamp": str(int(time.time() * 1000))}, self.config)
        try:
            with private_http_logging(), self.http.request(method, BASE + path, params=params if method == "GET" else None,
                    data=params if method == "POST" else None, timeout=(4, 8), allow_redirects=False,
                    headers={"Content-Type": "application/x-www-form-urlencoded"} if method == "POST" else None,
                    stream=True) as response:
                if response.status_code != 200:
                    raise AppError("source_rejected", "外卖平台未返回成功响应。", SOURCE,
                                   http_status=response.status_code)
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise AppError("response_too_large", "外卖响应超出读取上限。", SOURCE)
        except requests.RequestException:
            raise AppError("network_error", "外卖平台连接失败；请检查宿主网络或已配置的代理。", SOURCE) from None
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise AppError("schema_changed", "外卖平台返回了无法识别的数据。", SOURCE) from None
        if isinstance(data, list) and path == PROPERTIES:
            return data
        if not isinstance(data, dict):
            raise AppError("schema_changed", "外卖平台响应结构改变。", SOURCE)
        if "ret" in data and str(data["ret"]) != "0":
            # A rejection can be specific to one shop or operation. It does not
            # prove that this app's signing configuration is globally invalid.
            raise AppError("source_rejected", "外卖平台拒绝了此次读取；请在微信核对此店状态。", SOURCE)
        return data

    def shops(self, query: str, category: str, area: str) -> dict:
        return self.read("GET", SHOPS, {"shopAreaId": area or self.config.get("default_area", ""),
            "category": category, "orderBy": "-1", "shopName": query, "needCategory": "Y", "act": "first",
            "latitude": "", "longitude": "", "customShopListId": "", "shopSaleStatus": "",
            "shopCouponStatus": "", "showShopListSales": "", "shopTagStatus": ""})

    def detail(self, shop_id: str) -> dict:
        return self.read("GET", DETAIL, {"shopId": shop_id, "customerId": ""})

    def menu(self, shop_id: str) -> dict:
        return self.read("POST", MENU, {"shopId": shop_id})

    def categories(self, shop_id: str) -> dict:
        return self.read("POST", CATEGORIES, {"shopId": shop_id, "customerId": "", "refreshCache": "Y"})

    def product(self, shop_id: str, product_id: str) -> dict:
        return self.read("POST", PRODUCT, {"shopId": shop_id, "menuId": product_id, "customerId": ""})

    def settings(self, shop_id: str) -> dict:
        return self.read("POST", SETTINGS, {"shopId": shop_id, "customerId": "", "refreshCache": "Y"})

    def properties(self, product_id: str) -> dict:
        return {"items": self.read("GET", PROPERTIES, {"ids": product_id, "uid": self.config["userId"],
                                                       "loginCustomerId": ""})}
