"""Public device identities verified on 2026-10-16; no live states or credentials."""
from dataclasses import dataclass

from .runtime import AppError

VERIFIED_ON = "2026-10-16"


@dataclass(frozen=True)
class Device:
    code: str
    name: str
    location: str
    capacity: int = 20
    aliases: tuple[str, ...] = ()

    def metadata(self) -> dict:
        return {"device_code": self.code, "name": self.name, "location": self.location,
                "expected_port_count": self.capacity, "registry_verified_on": VERIFIED_ON,
                "source_url": "https://wx.isfdz.com/charge/enter/" + self.code}


DEVICES = (
    Device("4GR00008477", "水电中心", "水电中心"),
    Device("4GR00008480", "明德书院 MD-1", "明德书院", aliases=("明德", "MD")),
    Device("4GR00008484", "文南楼下架空层 WNL-1", "文南楼", aliases=("文南", "WNL")),
    Device("4GR00008485", "思源书院 SY-3", "思源书院", aliases=("思源", "SY", "思源3")),
    Device("4GR00008488", "运动场中路 YDC-1", "运动场中路", aliases=("运动场", "YDC")),
    Device("4GR00008489", "思源书院 SY-2", "思源书院", aliases=("思源", "SY", "思源2")),
    Device("4GR00008490", "思源书院 SY-1", "思源书院", aliases=("思源", "SY", "思源1")),
    Device("4GR00008491", "图书馆 TSG-3", "图书馆", aliases=("TSG", "图书馆3")),
    Device("4GR00008492", "思源书院 SY-4", "思源书院", aliases=("思源", "SY", "思源4")),
    Device("4GR00008493", "图书馆 TSG-2", "图书馆", aliases=("TSG", "图书馆2")),
    Device("4GR00008494", "敬一书院", "敬一书院", aliases=("敬一",)),
    Device("4GR00008495", "图书馆 TSG-1", "图书馆", aliases=("TSG", "图书馆1")),
    Device("4GR00008497", "运动场中路 YDC-2", "运动场中路", aliases=("运动场", "YDC")),
    Device("4GR00008498", "至诚书院 ZC-1", "至诚书院", aliases=("至诚", "ZC")),
)


def select_devices(location: str, devices: tuple[Device, ...]) -> list[Device]:
    if not isinstance(location, str) or len(location) > 80 or any(ord(c) < 32 for c in location):
        raise AppError("invalid_location", "位置关键词最长 80 字，不能包含控制字符。", "charging")

    def normalize(value):
        return "".join(c for c in value.casefold() if not c.isspace() and c not in "-_")

    query = normalize(location)
    if query in {"", "全部", "所有", "all"}:
        return list(devices)
    return [d for d in devices if any(query in normalize(value)
                                    for value in (d.code, d.name, d.location, *d.aliases))]
