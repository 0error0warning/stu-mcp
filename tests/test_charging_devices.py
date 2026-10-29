"""Static location contracts checked against the supplied device QR photographs."""
import pytest

from stu_mcp.charging_devices import DEVICES, select_devices
from stu_mcp.features.charging.service import ChargingService


@pytest.mark.parametrize("location,code", [
    ("思源书院左一", "4GR00008492"),
    ("思源书院左二", "4GR00008485"),
    ("思源书院左三", "4GR00008489"),
    ("思源左四", "4GR00008490"),
    ("图书馆一", "4GR00008495"),
    ("图书馆二", "4GR00008493"),
    ("图书馆三", "4GR00008491"),
    ("敬一书院", "4GR00008494"),
    ("志诚书院", "4GR00008498"),
    ("文科教学楼", "4GR00008484"),
    ("滑板场一", "4GR00008497"),
    ("滑板场二", "4GR00008488"),
    ("修远书院", "4GR00008480"),
    ("教师宿舍", "4GR00006723"),
])
def test_document_location_queries_resolve_to_the_photographed_device(app, location, code):
    overview = ChargingService(app.store).overview(location, refresh=False)
    assert overview["total_count"] == 1
    assert [item["device_code"] for item in overview["items"]] == [code]
    assert overview["items"][0]["counts"] is None


@pytest.mark.parametrize("provider_label,code", [
    ("SY-1", "4GR00008490"),
    ("SY-2", "4GR00008489"),
    ("SY-3", "4GR00008485"),
    ("SY-4", "4GR00008492"),
    ("明德书院 MD-1", "4GR00008480"),
    ("文南楼下架空层 WNL-1", "4GR00008484"),
    ("运动场中路 YDC-1", "4GR00008488"),
    ("运动场中路 YDC-2", "4GR00008497"),
])
def test_provider_labels_keep_their_device_identity(provider_label, code):
    assert [device.code for device in select_devices(provider_label, DEVICES)] == [code]


def test_relocated_label_exposes_provider_name_without_overriding_document_location(app):
    device = ChargingService(app.store).detail("4GR00008480", refresh=False)["device"]
    assert device["name"] == "修远书院" and device["location"] == "修远书院"
    assert device["provider_name"] == "明德书院 MD-1"


def test_teacher_device_is_queryable_and_water_center_is_not_removed_by_document_omission(app):
    service = ChargingService(app.store)
    teacher = service.detail("4GR00006723", refresh=False)["device"]
    water = service.detail("4GR00008477", refresh=False)["device"]
    assert teacher["name"] == "教师宿舍" and teacher["provider_name"] == "高层教师宿舍"
    assert water["location"] == "水电中心"
    assert teacher["counts"] is None and water["counts"] is None
    overview = service.overview(refresh=False)
    assert overview["coverage"]["catalog_device_count"] == 15
    assert overview["coverage"]["inventory_complete"] is None
