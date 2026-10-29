"""Public device identities and locations checked against device QR photographs."""
from dataclasses import dataclass

from .runtime import AppError

VERIFIED_ON = "2026-10-29"


@dataclass(frozen=True)
class Device:
    code: str
    name: str
    location: str
    capacity: int = 20
    aliases: tuple[str, ...] = ()
    provider_name: str | None = None

    def metadata(self) -> dict:
        return {"device_code": self.code, "name": self.name, "location": self.location,
                "provider_name": self.provider_name or self.name,
                "expected_port_count": self.capacity, "registry_verified_on": VERIFIED_ON,
                "source_url": "https://wx.isfdz.com/charge/enter/" + self.code}


DEVICES = (
    Device("4GR00008477", "水电中心", "水电中心"),
    Device("4GR00008480", "修远书院", "修远书院", aliases=("修远", "明德", "MD"),
           provider_name="明德书院 MD-1"),
    Device("4GR00008484", "文科教学楼", "文科教学楼", aliases=("文南", "WNL"),
           provider_name="文南楼下架空层 WNL-1"),
    Device("4GR00008485", "思源书院左二", "思源书院", aliases=("思源", "SY", "思源3", "思源左二"),
           provider_name="思源书院 SY-3"),
    Device("4GR00008488", "滑板场二", "滑板场", aliases=("运动场", "YDC", "滑板场2"),
           provider_name="运动场中路 YDC-1"),
    Device("4GR00008489", "思源书院左三", "思源书院", aliases=("思源", "SY", "思源2", "思源左三"),
           provider_name="思源书院 SY-2"),
    Device("4GR00008490", "思源书院左四", "思源书院", aliases=("思源", "SY", "思源1", "思源左四"),
           provider_name="思源书院 SY-1"),
    Device("4GR00008491", "图书馆三", "图书馆", aliases=("TSG", "图书馆3"), provider_name="图书馆 TSG-3"),
    Device("4GR00008492", "思源书院左一", "思源书院", aliases=("思源", "SY", "思源4", "思源左一"),
           provider_name="思源书院 SY-4"),
    Device("4GR00008493", "图书馆二", "图书馆", aliases=("TSG", "图书馆2"), provider_name="图书馆 TSG-2"),
    Device("4GR00008494", "敬一书院", "敬一书院", aliases=("敬一",)),
    Device("4GR00008495", "图书馆一", "图书馆", aliases=("TSG", "图书馆1"), provider_name="图书馆 TSG-1"),
    Device("4GR00008497", "滑板场一", "滑板场", aliases=("运动场", "YDC", "滑板场1"),
           provider_name="运动场中路 YDC-2"),
    Device("4GR00008498", "至诚书院", "至诚书院", aliases=("至诚", "ZC", "志诚", "志诚书院"),
           provider_name="至诚书院 ZC-1"),
    Device("4GR00006723", "教师宿舍", "教师宿舍", aliases=("教师",), provider_name="高层教师宿舍"),
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
                                    for value in (d.code, d.name, d.location, d.provider_name or d.name, *d.aliases))]
