import json

import pytest

from stu_mcp.services import describe_service


@pytest.mark.parametrize("query", ["校园网 报修", "校园网报修", "网络报修", "网络故障"])
def test_network_repair_available_without_cache_network_or_keyring(app, monkeypatch, query):
    monkeypatch.setattr(app.vault, "_key", lambda **_: pytest.fail("service lookup must not read credentials"))
    result = app.query("service", query, source="public")
    assert result["total_count"] == 2
    item = result["items"][0]
    assert item["url"] == "https://r.stu.edu.cn/"
    assert item["service_id"] == "campus_repair" and item["recommended"] is True
    assert item["form_verified"] is True and item["submission_verified"] is False
    assert item["last_live_verification"]["category"] == "网络故障"
    assert item["campuses"] == ["桑浦山", "东海岸"]
    assert item["verification_scope"] == "entry_purpose"
    assert item["collected_at"] is None
    assert item["availability"] == "not_checked" and item["workflow_verified"] is False
    reference = result["items"][1]
    assert reference["url"] == "http://its.stu.edu.cn/" and reference["recommended"] is False
    assert reference["migration_confirmed"] is False
    assert reference["last_connection_check"]["http"] == "connection_refused"
    assert app.store.freshness() == []


def test_cached_mislabel_and_duplicate_do_not_route_network_faults_to_dorm_repair(app):
    app.store.save_batch("public", [
        {"id": "public:service:old", "kind": "service", "title": "校园网报修",
         "url": "http://repair.stu.edu.cn/"},
        {"id": "public:service:duplicate", "kind": "service", "title": "网上报修",
         "url": "https://repair.stu.edu.cn/"},
    ])
    assert [i["service_id"] for i in app.query("service", "校园网 报修")["items"]] == [
        "campus_repair", "network_repair"]
    dorm = app.query("service", "桑浦山 宿舍")["items"]
    assert len(dorm) == 1 and dorm[0]["url"] == "https://repair.stu.edu.cn/"
    assert dorm[0]["collected_at"]
    assert dorm[0]["original_title"] in {"网上报修", "校园网报修"}
    assert app.store.get("public:service:old")["title"] == "校园网报修"  # Read-only overlay.


def test_repair_campuses_and_pagination_are_independent(app):
    east = app.query("service", "东海岸 报修")["items"]
    assert len(east) == 1 and east[0]["url"] == "https://r.stu.edu.cn/"
    first = app.query("service", "报修", limit=1)
    second = app.query("service", "报修", limit=1, offset=1)
    last = app.query("service", "报修", limit=1, offset=2)
    assert first["total_count"] == second["total_count"] == last["total_count"] == 3
    assert first["has_more"] and not last["has_more"]
    assert len({i["items"][0]["service_id"] for i in (first, second, last)}) == 3
    assert app.query("service", source="oa")["total_count"] == 0


def test_callback_ticket_is_not_exposed_as_a_service_link(app):
    app.store.save_batch("public", [{"id": "public:service:callback", "kind": "service", "title": "网上报修",
                                    "url": "https://repair.stu.edu.cn/student.aspx?ticket=SYNTHETIC_TICKET"}])
    result = app.query("service", "桑浦山 宿舍")
    assert "SYNTHETIC_TICKET" not in json.dumps(result)
    assert result["items"][0]["url"] == "https://repair.stu.edu.cn/"


def test_old_east_campus_label_does_not_hide_verified_network_category(app):
    app.store.save_batch("public", [{"id": "public:service:r", "kind": "service", "title": "东海岸网上报修",
                                    "url": "http://r.stu.edu.cn/"}])
    item = app.query("service", "桑浦山 网络故障")["items"][0]
    assert item["service_id"] == "campus_repair"
    assert item["original_title"] == "东海岸网上报修"
    assert item["last_live_verification"]["campus_options"] == ["桑浦山校区", "东海岸校区"]
    assert any("分类" in step and "网络故障" in step for step in item["workflow_steps"])


def test_one_stop_network_topic_is_available_but_not_a_fault_request_form(app):
    app.store.save_batch("public", [{"id": "public:service:portal", "kind": "service", "title": "网络故障报修",
                                    "url": "https://service.stu.edu.cn/"}])
    portal = app.query("service", "一网通办")["items"][0]
    assert portal["service_id"] == "school_service_portal"
    assert portal["topic_services"] == ["科研流量包", "防火墙网络", "校外人员WebVPN开通", "国际学术资源访问申请"]
    assert "school_service_portal" not in {i["service_id"] for i in app.query("service", "网络报修")["items"]}


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
