"""Observed Web SSO gateway token and Moodle redirect, with synthetic cookies."""
from urllib.parse import parse_qs

import httpx
import pytest

from stu_mcp.auth_http.cas import MOODLE_SERVICES, REPAIR, SERVICES, SSO, _bridge_service_token, acquire_state
from stu_mcp.auth_http.transport import HTTPFlow
from stu_mcp.runtime import AppError

USERNAME, PASSWORD = "synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD"
FORM = ('<form method="post"><input name="username"><input name="password" type="password">'
        '<input name="lt" type="hidden" value="synthetic-lt">'
        '<input name="execution" type="hidden" value="synthetic-execution">'
        '<input name="_eventId" type="hidden" value="submit"></form>')


def mystu(*, token=True, test_query="testsession=123456", test_path="/courses/elc/index.php",
          inventory=(), fail_instance=None, challenge_instance=None, wrong_instance=None):
    calls, authenticated, moodle_ready, moodle_callback = [], False, set(), set()

    def handler(request):
        nonlocal authenticated
        calls.append(request)
        host, path, query = request.url.host, request.url.path, dict(request.url.params)
        cookies = request.headers.get("cookie", "")
        if host == "sso.stu.edu.cn":
            assert "MoodleSession=" not in cookies and "school_session=" not in cookies
            if request.method == "POST":
                authenticated = True
                assert parse_qs(request.content.decode())["password"] == [PASSWORD]
                headers = [("location", SERVICES["mystu"] + "?ticket=synthetic-ticket"),
                           ("set-cookie", "CASTGC=SYNTHETIC_CAS; Domain=.stu.edu.cn; Path=/; Secure"),
                           ("set-cookie", "username=SYNTHETIC_NAME; Path=/; Secure")]
                if token:
                    # The actual gateway token is not Secure at SSO. Its copy
                    # is deliberately strengthened and narrowed to HTTPS my.
                    headers.append(("set-cookie", "_UT_=SYNTHETIC_WEB; Domain=.stu.edu.cn; Path=/"))
                return httpx.Response(302, headers=headers)
            if authenticated and query.get("service") in MOODLE_SERVICES.values():
                service = query["service"]
                name = service.split("/")[4]
                if name == wrong_instance:
                    return httpx.Response(302, headers={"location": MOODLE_SERVICES["elc"] + "?ticket=synthetic-other"})
                if name == fail_instance:
                    raise httpx.ReadTimeout("synthetic_private_error_not_for_output", request=request)
                if name != challenge_instance:
                    return httpx.Response(302, headers={"location": service + "?ticket=synthetic-moodle"})
            return httpx.Response(200, text=FORM, headers={
                "set-cookie": "JSESSIONID=SYNTHETIC_SSO; Path=/; Secure"})
        assert host == "my.stu.edu.cn"
        assert all(name + "=" not in cookies for name in ("CASTGC", "JSESSIONID", "username"))
        if path == "/discussion/my-courses":
            if not authenticated:
                return httpx.Response(302, headers={
                    "location": SSO + "?" + str(httpx.QueryParams({"service": SERVICES["mystu"]})),
                    "set-cookie": "school_session=SYNTHETIC_MY; Path=/; Secure"})
            if token:
                assert "_UT_=SYNTHETIC_WEB" in cookies
            else:
                assert "school_session=SYNTHETIC_MY" in cookies
            if "ticket" in query:
                return httpx.Response(302, headers={"location": SERVICES["mystu"]})
            return httpx.Response(200, text="synthetic inventory page")
        if path.endswith("/user/validate"):
            return httpx.Response(200, json={"username": USERNAME, "id": "synthetic-id"})
        if path.endswith("/course/query"):
            return httpx.Response(200, json={"items": [
                {"id": name + "-synthetic", "name": "合成课程", "attendanceYear": 2026, "attendanceSemester": 1,
                 "url": f"https://my.stu.edu.cn/courses/{name}/course/view.php?id=1"} for name in inventory]})
        name = path.split("/")[2] if path.startswith("/courses/") else ""
        root = f"/courses/{name}"
        service = MOODLE_SERVICES.get(name, "")
        active_test_path = test_path.replace("/elc/", f"/{name}/") if name != "elc" else test_path
        if path == root + "/":
            if name in moodle_ready:
                if name == "campus":
                    return httpx.Response(303, headers={"location": root + "/my/"})
                return httpx.Response(200, text='<a href="/courses/elc/login/logout.php">logout</a>')
            return httpx.Response(303, headers={"location": service})
        if path == root:
            assert not query
            return httpx.Response(301 if name == "campus" else 303, headers={"location": root + "/"})
        if path == root + "/my/":
            assert name in moodle_ready and not query
            return httpx.Response(200, text=f'<a href="{root}/login/logout.php">logout</a>')
        if path == root + "/login/index.php":
            if "testsession" in query:
                moodle_ready.add(name)
                return httpx.Response(303, headers={"location": root})
            if "ticket" not in query:
                if name in moodle_callback:
                    return httpx.Response(303, headers={"location": active_test_path + "?" + test_query})
                return httpx.Response(302, headers={"location": SSO + "?" + str(httpx.QueryParams({
                    "service": service, "gateway": "true"}))})
            if name == "campus":
                moodle_callback.add(name)
            return httpx.Response(302, headers={"location": root + ("/login/index.php" if name == "campus" else "/index.php"), "set-cookie":
                                               f"MoodleSession=SYNTHETIC_MOODLE; Path={root}/; Secure"})
        if path == root + "/index.php" and not query:
            return httpx.Response(303, headers={"location": active_test_path + "?" + test_query})
        if path == active_test_path and query:
            moodle_ready.add(name)
            return httpx.Response(303, headers={"location": root})
        pytest.fail("unexpected fixed source endpoint")
    return httpx.MockTransport(handler), calls


@pytest.mark.parametrize("token", [True, False])
@pytest.mark.parametrize("test_path", ["/courses/elc/index.php", "/courses/elc/login/index.php"])
def test_mystu_only_required_web_token_bridges_and_moodle_get_test_is_followed(token, test_path):
    transport, calls = mystu(token=token, test_path=test_path)
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["identity_verified"] and candidate.proof["elc_bootstrapped"]
    assert "repair_sso_state" not in candidate.state
    cookies = {cookie["name"]: cookie for cookie in candidate.state["cookies"]}
    assert not {"CASTGC", "JSESSIONID", "username"} & cookies.keys()
    assert ("_UT_" in cookies) is token
    if token:
        assert cookies["_UT_"]["domain"] == "my.stu.edu.cn" and cookies["_UT_"]["secure"] is True
    assert sum(request.method == "POST" for request in calls) == 1
    assert all(request.method == "GET" for request in calls if request.url.host == "my.stu.edu.cn")
    assert any(request.url.path == "/courses/elc" and not request.url.query for request in calls)
    assert calls[-1].url.path == "/courses/elc/"


@pytest.mark.parametrize("query,path", [
    ("testsession=", "/courses/elc/index.php"),
    ("testsession=123456789012345678901", "/courses/elc/index.php"),
    ("testsession=1&testsession=2", "/courses/elc/index.php"),
    ("testsession=1&ticket=synthetic", "/courses/elc/index.php"),
    ("testsession=not-a-number", "/courses/elc/index.php"),
    ("testsession=123", "/discussion/my-courses"),
    ("testsession=123", "/courses/elc"),
])
def test_moodle_test_query_does_not_expand_other_redirects(query, path):
    transport, calls = mystu(test_query=query, test_path=path)
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["identity_verified"] is True
    assert candidate.proof["moodle_bootstrap"] == {
        "elc": {"bootstrapped": False, "status": "authentication_schema_changed"}}
    assert sum(request.method == "POST" for request in calls) == 1
    assert not any(request.url.query.decode() == query for request in calls)


@pytest.mark.parametrize("inventory", [("campus",), ("elc",), ("campus", "elc")])
def test_only_inventory_moodle_instances_bootstrap_with_their_own_gateway(inventory):
    transport, calls = mystu(inventory=inventory, test_path="/courses/elc/login/index.php")
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["moodle_bootstrap"] == {
        name: {"bootstrapped": True, "status": "verified"} for name in inventory}
    assert {request.url.path.split("/")[2] for request in calls if request.url.path.startswith("/courses/")} == set(inventory)
    if "campus" in inventory:
        assert any(request.url.path == "/courses/campus/my/" for request in calls)
        # Eight school pages and one CAS gateway GET form the observed
        # 9-request campus login chain, including the slash-normalizing 301.
        assert sum(request.url.path.startswith("/courses/campus") for request in calls) == 8
    assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.parametrize("failure", ["network", "challenge"])
def test_failed_campus_bootstrap_preserves_identity_and_independent_elc_success(failure):
    transport, calls = mystu(inventory=("campus", "elc"),
                             fail_instance="campus" if failure == "network" else None,
                             challenge_instance="campus" if failure == "challenge" else None)
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["authenticated"] and candidate.proof["identity_verified"]
    assert candidate.proof["courses_verified"]
    assert candidate.proof["moodle_bootstrap"] == {
        "campus": {"bootstrapped": False, "status": "authentication_network_error" if failure == "network"
                   else "moodle_session_unconfirmed"}, "elc": {"bootstrapped": True, "status": "verified"}}
    assert "synthetic_private_error" not in str(candidate.proof)
    assert sum(request.method == "POST" for request in calls) == 1


def test_campus_cannot_claim_another_moodle_instances_logged_in_page_as_its_proof():
    transport, calls = mystu(inventory=("campus", "elc"), wrong_instance="campus")
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["moodle_bootstrap"] == {
        "campus": {"bootstrapped": False, "status": "authentication_schema_changed"},
        "elc": {"bootstrapped": True, "status": "verified"}}
    assert not any(request.url.params.get("ticket") == "synthetic-other" for request in calls)
    assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.parametrize("domain,path,duplicate", [
    ("sso.stu.edu.cn", "/", False), (".edu.cn", "/", False),
    (".stu.edu.cn", "/login", False), (".stu.edu.cn", "/", True),
])
def test_web_token_ambiguity_or_scope_change_never_bridges(domain, path, duplicate):
    with HTTPFlow("mystu", ("sso.stu.edu.cn",)) as sso, HTTPFlow("mystu", ("my.stu.edu.cn",)) as school:
        sso.client.cookies.set("_UT_", "SYNTHETIC_WEB", domain=domain, path=path)
        if duplicate:
            sso.client.cookies.set("_UT_", "SYNTHETIC_OTHER", domain=domain, path="/login")
        with pytest.raises(AppError) as error:
            _bridge_service_token(sso, school, "mystu")
        assert error.value.code == "unsafe_cookie_scope" and not school.state()["cookies"]


def test_legacy_jw_never_bridges_any_parent_or_cas_cookie():
    with HTTPFlow("jw", ("sso.stu.edu.cn",)) as sso, HTTPFlow("jw", ("jw.stu.edu.cn",)) as school:
        for name in ("_UT_", "CASTGC", "JSESSIONID"):
            sso.client.cookies.set(name, "SYNTHETIC_PRIVATE", domain=".stu.edu.cn", path="/")
        _bridge_service_token(sso, school, "jw")
        assert not school.state()["cookies"]


@pytest.mark.parametrize("source,host", [("mystu", "my.stu.edu.cn"), ("repair", "repair.stu.edu.cn")])
def test_bridge_is_exact_https_service_host_and_never_a_cas_session(source, host):
    with HTTPFlow(source, ("sso.stu.edu.cn",)) as sso, HTTPFlow(source, (host,)) as school:
        for name in ("_UT_", "CASTGC", "JSESSIONID", "username"):
            sso.client.cookies.set(name, "SYNTHETIC_PRIVATE", domain=".stu.edu.cn", path="/")
        _bridge_service_token(sso, school, source)
        saved = school.state()["cookies"]
        assert len(saved) == 1 and saved[0]["name"] == "_UT_"
        assert saved[0]["domain"] == host and saved[0]["secure"] is True


def repair(*, mode="success"):
    calls, password_sent, student_logged_in = [], False, False
    student = REPAIR + "student.aspx"
    second_service = {"external": "https://evil.example/", "other_repair": REPAIR + "admin.aspx"}.get(mode, student)

    def listing():
        filters = ''.join(f'<input id="{key}" value="">' for key in (
            "tb_AppBill_ID", "tb_AppBill_Title", "tb_Appbill_from_Date", "tb_Appbill_to_Date"))
        return '<h1>我的报修单据列表</h1>' + filters + (
            '<select id="ddl_Appbill_Status"><option>全部</option></select><p>没有任何数据!</p>')

    def handler(request):
        nonlocal password_sent, student_logged_in
        calls.append(request)
        host, path, query = request.url.host, request.url.path, dict(request.url.params)
        cookies = request.headers.get("cookie", "")
        if host == "sso.stu.edu.cn":
            assert "repair_session=" not in cookies
            if request.method == "POST":
                assert not password_sent
                password_sent = True
                assert parse_qs(request.content.decode())["password"] == [PASSWORD]
                return httpx.Response(302, headers=[
                    ("location", SERVICES["repair"] + "?ticket=synthetic-default-ticket"),
                    ("set-cookie", "CASTGC=SYNTHETIC_CAS; Domain=.stu.edu.cn; Path=/; Secure"),
                    ("set-cookie", "_UT_=SYNTHETIC_WEB; Domain=.stu.edu.cn; Path=/")])
            if password_sent:
                assert query == {"service": student} and "CASTGC=SYNTHETIC_CAS" in cookies
                location = SSO + "?" + str(httpx.QueryParams({"service": student})) if mode == "loop" else (
                    student + "?ticket=synthetic-student-ticket")
                return httpx.Response(302, headers={"location": location})
            return httpx.Response(200, text=FORM, headers={
                "set-cookie": "JSESSIONID=SYNTHETIC_SSO; Path=/; Secure"})
        assert host == "repair.stu.edu.cn"
        assert "CASTGC=" not in cookies and "JSESSIONID=" not in cookies
        if path == "/":
            return httpx.Response(302, headers={"location": SSO + "?" + str(httpx.QueryParams({
                "service": SERVICES["repair"]}))})
        assert "_UT_=SYNTHETIC_WEB" in cookies
        if path == "/default.aspx":
            assert query == {"ticket": "synthetic-default-ticket"}
            return httpx.Response(302, headers={"location": student})
        assert path == "/student.aspx"
        if query == {"ticket": "synthetic-student-ticket"}:
            student_logged_in = True
            if mode == "per_page":
                return httpx.Response(200, text=listing())
            return httpx.Response(302, headers={"location": student, "set-cookie":
                                               "repair_session=SYNTHETIC_REPAIR; Path=/; Secure"})
        if not student_logged_in or mode == "per_page":
            return httpx.Response(302, headers={"location": SSO + "?" + str(httpx.QueryParams({
                "service": second_service}))})
        if mode == "unproven":
            return httpx.Response(200, text="synthetic welcome without a personal list")
        return httpx.Response(200, text=listing())
    return httpx.MockTransport(handler), calls


def test_repair_secondary_cas_service_uses_two_get_tickets_but_only_one_password():
    transport, calls = repair()
    candidate = acquire_state("repair", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof == {"authenticated": True, "list_verified": True, "orders": 0}
    assert sum(request.method == "POST" for request in calls) == 1
    assert len([request for request in calls if "ticket" in request.url.params]) == 2
    assert {cookie["name"] for cookie in candidate.state["cookies"]} == {"_UT_", "repair_session"}
    assert all(cookie["domain"] == "repair.stu.edu.cn" for cookie in candidate.state["cookies"])
    assert "CASTGC" in {cookie["name"] for cookie in candidate.state["repair_sso_state"]["cookies"]}


def test_repair_proof_consumes_final_ticket_page_without_a_redundant_unauthenticated_get():
    transport, calls = repair(mode="per_page")
    candidate = acquire_state("repair", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof["list_verified"] is True
    assert calls[-1].url.params["ticket"] == "synthetic-student-ticket"
    assert sum(request.url.path == "/student.aspx" and not request.url.query for request in calls) == 1
    assert all(cookie["name"] != "CASTGC" for cookie in candidate.state["cookies"])
    assert "repair_sso_state" in candidate.state


@pytest.mark.parametrize("mode,code", [("external", "authentication_schema_changed"),
                                       ("other_repair", "authentication_schema_changed"),
                                       ("loop", "authentication_budget"), ("unproven", "schema_changed")])
def test_repair_secondary_cas_service_is_bounded_and_requires_actual_list(mode, code):
    transport, calls = repair(mode=mode)
    with pytest.raises(AppError) as error:
        acquire_state("repair", USERNAME, PASSWORD, transport=transport)
    assert error.value.code == code
    assert sum(request.method == "POST" for request in calls) == 1
    assert all(request.url.host in {"sso.stu.edu.cn", "repair.stu.edu.cn"} for request in calls)
    assert len(calls) <= 13
