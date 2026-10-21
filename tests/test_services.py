
import pytest

from stu_mcp.services import describe_service


@pytest.mark.parametrize("url", ["https://repair.stu.edu.cn.example.org/", "https://not-its.stu.edu.cn/"])
def test_host_lookalikes_are_not_classified_as_school_repair(url):
    item = describe_service({"title": "校园网报修", "url": url})
    assert not item["purpose_verified"] and "service_id" not in item


def test_login_network_access_and_community_navigation_are_not_repair_services():
    roles = [describe_service({"url": url})["service_id"] for url in (
        "https://sso.stu.edu.cn/login?service=synthetic", "https://a.stu.edu.cn/", "https://d.stulip.org/")]
    assert roles == ["school_sso", "network_access", "community_navigation"]
    assert describe_service({"url": "https://d.stulip.org/"})["official"] is False


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:password@repair.stu.edu.cn/",
                                     "https://example.org/?ticket=SYNTHETIC_TICKET"])
def test_invalid_or_secret_bearing_links_are_not_returned(url):
    assert describe_service({"url": url}) is None
