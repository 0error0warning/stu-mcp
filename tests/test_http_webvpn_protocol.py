"""Offline WebVPN protocol and source-bound transport regression coverage."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from stu_mcp import network, webvpn
from stu_mcp.auth_http import webvpn as protocol
from stu_mcp.runtime import AppError

PASSWORD = "SYNTHETIC_PASSWORD"
NONCE = "SYNTHETIC_FRESH_NONCE"
SID = "SYNTHETIC_FRESH_SESSION"
HTTP_ROUTE = {"scheme": "http", "host": "oa-stu-edu-cn.webvpn.stu.edu.cn", "port": 8118}
OA_CANONICAL = "https://oa-stu-edu-cn.webvpn.stu.edu.cn/ind/bulletin.nsf/notice"


def xml(tag, **values):
    root = ET.Element(tag)
    for name, value in values.items():
        ET.SubElement(root, name).text = str(value)
    return ET.tostring(root)


def catalog(*, attributes=False, extra="", scheme="http:", port="8118"):
    config = {"scheme": scheme, "hostname": "webvpn.stu.edu.cn", "port": port}
    resource = {"id": "42", "host": "http://oa.stu.edu.cn/login/Login.jsp?logintype=1",
                "svc": "webapp:http", "type": "0", "attr": "0"}
    conf, resources = ET.Element("Conf"), ET.Element("Resource")
    web, rc = ET.SubElement(conf, "WebVpn"), ET.SubElement(ET.SubElement(resources, "Rcs"), "Rc")
    for node, values in ((web, config), (rc, resource)):
        if attributes:
            node.attrib.update(values)
        else:
            for name, value in values.items():
                ET.SubElement(node, name).text = value
    if extra:
        resources.append(ET.fromstring(extra))
    return ET.tostring(conf), ET.tostring(resources)


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=1024)


class Scenario:
    def __init__(self, key):
        self.key = key
        self.sent = []
        self.inits = 0
        self.cookie_matches = True
        self.error_at = None
        self.graphical = False
        self.password_reply = {"ErrorCode": 1, "NextService": "auth/token",
                               "NextServiceSubType": "totp", "TotpStatus": "Bind", "TwfID": SID}
        self.totp_reply = {"ErrorCode": 1}
        self.totp_calls = 0
        self.conf, self.resources = catalog()

    def auth(self, *, fresh=False):
        numbers = self.key.public_key().public_numbers()
        return {"ErrorCode": 1, "TwfID": SID if fresh else "SYNTHETIC_INITIAL_SESSION",
                "CSRF_RAND_CODE": NONCE if fresh else "SYNTHETIC_INITIAL_NONCE",
                "RSA_ENCRYPT_KEY": format(numbers.n, "x"), "RSA_ENCRYPT_EXP": numbers.e,
                "RndImg": int(self.graphical), "MID_ATK_CHECK": 0}

    def handle(self, request):
        self.sent.append(request)
        url = str(request.url)
        if url == self.error_at:
            raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_ERROR_MUST_NOT_ESCAPE")
        if url == protocol.ORIGIN + "/portal/":
            return httpx.Response(200, text="synthetic portal")
        if url == protocol.INIT:
            self.inits += 1
            fresh = self.inits == 2
            values = self.auth(fresh=fresh)
            headers = {}
            if fresh:
                headers["set-cookie"] = f"TWFID={SID if self.cookie_matches else 'other'}; Secure; HttpOnly; Path=/"
            return httpx.Response(200, content=xml("Auth", **values), headers=headers)
        if url == protocol.CONFIG:
            return httpx.Response(200, content=xml("Auth", ErrorCode=1, USE_RAND_CODE=0,
                MID_ATK_CHECK=0, CSRF_RAND_CODE="SYNTHETIC_CONFIG_NONCE", unknown_metadata="harmless"))
        if url == protocol.PASSWORD:
            values = parse_qs(request.content.decode(), keep_blank_values=True)
            assert values["svpn_req_randcode"] == [NONCE]
            decrypted = self.key.decrypt(bytes.fromhex(values["svpn_password"][0]), padding.PKCS1v15())
            assert decrypted == (PASSWORD + "_" + NONCE).encode()
            assert values["svpn_name"] == ["synthetic-user"]
            assert request.headers["origin"] == protocol.ORIGIN
            assert "TWFID=" + SID in request.headers["cookie"]
            assert PASSWORD.encode() not in request.content
            return httpx.Response(200, content=xml("Auth", **self.password_reply))
        if url == protocol.TOTP:
            values = parse_qs(request.content.decode())
            assert values == {"twfid": [SID], "svpn_inputtoken": ["123456"]}
            return httpx.Response(200, content=xml("Auth", **self.totp_reply))
        if url in (protocol.CONF, protocol.RESOURCES):
            return httpx.Response(200, content=self.conf if url == protocol.CONF else self.resources)
        raise AssertionError("Unexpected synthetic endpoint")

    def code(self):
        self.totp_calls += 1
        return "123456"

    def acquire(self):
        return protocol.acquire_state(username="synthetic-user", password=PASSWORD,
            totp_code=self.code, transport=httpx.MockTransport(self.handle))

    def posts(self):
        return [str(request.url) for request in self.sent if request.method == "POST"]


def test_fresh_nonce_rsa_ciphertext_session_and_catalog_proof(rsa_key, capsys, caplog):
    scenario = Scenario(rsa_key)
    state, proof = scenario.acquire()
    assert scenario.inits == 2
    assert scenario.posts() == [protocol.PASSWORD, protocol.TOTP]
    assert scenario.totp_calls == 1
    assert state["webvpn_oa_route"] == HTTP_ROUTE
    assert state["webvpn_catalog_verified"] is True
    assert state["cookies"][0]["value"] == SID
    assert state["cookies"][0]["secure"]
    assert proof["authentication_verified"] and proof["portal_catalog_verified"]
    assert proof["oa_content_verified"] is False and proof["oa_http_compat_required"]
    assert PASSWORD not in json.dumps(proof) and NONCE not in json.dumps(proof) and SID not in json.dumps(proof)
    assert capsys.readouterr() == ("", "")
    assert PASSWORD not in caplog.text and NONCE not in caplog.text and SID not in caplog.text


def test_fresh_cookie_must_match_fresh_init_before_password(rsa_key):
    scenario = Scenario(rsa_key)
    scenario.cookie_matches = False
    with pytest.raises(AppError) as failure:
        scenario.acquire()
    assert failure.value.code == "schema_changed"
    assert scenario.posts() == [] and scenario.totp_calls == 0


@pytest.mark.parametrize("phase,code", [("password", 20113), ("totp", 20014)])
def test_explicit_refusal_and_expired_token_are_not_retried(rsa_key, phase, code):
    scenario = Scenario(rsa_key)
    setattr(scenario, phase + "_reply", {"ErrorCode": code, "ErrorMessage": "SYNTHETIC_PRIVATE"})
    with pytest.raises(AppError) as failure:
        scenario.acquire()
    assert failure.value.code == "auto_login_failed"
    assert scenario.posts() == [protocol.PASSWORD] + ([protocol.TOTP] if phase == "totp" else [])
    assert "SYNTHETIC_PRIVATE" not in str(failure.value.result())
    assert all(str(request.url) != protocol.CONF for request in scenario.sent)


def test_graphical_requirement_stops_before_any_password(rsa_key):
    scenario = Scenario(rsa_key)
    scenario.graphical = True
    with pytest.raises(AppError) as failure:
        scenario.acquire()
    assert failure.value.code == "auto_login_interaction_required"
    assert scenario.posts() == [] and scenario.totp_calls == 0


def test_unbound_totp_stops_without_binding_or_prompting_code(rsa_key):
    scenario = Scenario(rsa_key)
    scenario.password_reply["TotpStatus"] = "UnBind"
    with pytest.raises(AppError) as failure:
        scenario.acquire()
    assert failure.value.code == "auto_login_interaction_required"
    assert scenario.posts() == [protocol.PASSWORD] and scenario.totp_calls == 0


@pytest.mark.parametrize("endpoint", [protocol.PASSWORD, protocol.TOTP])
def test_credential_post_timeout_is_unknown_and_single_send(rsa_key, endpoint):
    scenario = Scenario(rsa_key)
    scenario.error_at = endpoint
    with pytest.raises(AppError) as failure:
        scenario.acquire()
    assert failure.value.code == "authentication_outcome_unknown"
    assert scenario.posts().count(endpoint) == 1
    assert "SYNTHETIC_PRIVATE_ERROR" not in str(failure.value.result())


@pytest.mark.parametrize("attributes", [False, True])
def test_conf_and_resources_support_elements_and_attributes_with_metadata(attributes):
    conf, resource = catalog(attributes=attributes, extra="<HarmlessMetadata value='synthetic'/>")
    route, proof = protocol.oa_route(conf, resource)
    assert route == HTTP_ROUTE and proof["oa_resource"] == "catalog_verified"


def test_catalog_critical_attribute_element_conflict_and_doctype_are_rejected():
    conf, resource = catalog(attributes=True)
    conflicted = conf.replace(b"/>", b"><port>443</port></WebVpn>")
    with pytest.raises(AppError) as failure:
        protocol.oa_route(conflicted, resource)
    assert failure.value.code == "schema_changed"
    with pytest.raises(AppError):
        protocol.auth_fields(b'<!DOCTYPE Auth [<!ENTITY sample "private">]><Auth><ErrorCode>1</ErrorCode></Auth>')


@pytest.mark.parametrize("extra", [
    "<WebSsoInfos><webssoinfo><rcid>42</rcid></webssoinfo></WebSsoInfos>",
    "<Sso enable='1' data='42:synthetic;'/>",
])
def test_resource_sso_requirement_is_not_treated_as_content_ready(extra):
    conf, resource = catalog(extra=extra)
    route, proof = protocol.oa_route(conf, resource)
    assert route is None and proof["oa_resource"] == "sso_or_client_requires_review"


def cookie(name, domain, *, secure=False):
    return {"name": name, "value": "SYNTHETIC_" + name, "domain": domain, "path": "/",
            "secure": secure, "expires": -1}


def test_oa_http_needs_explicit_optin_and_never_sends_sso_parent_or_secure_cookie():
    state = {"cookies": [cookie("session", ".webvpn.stu.edu.cn"), cookie("secure", ".webvpn.stu.edu.cn", secure=True),
        cookie("sso", ".stu.edu.cn"), cookie("central", "sso.stu.edu.cn"), cookie("oa", HTTP_ROUTE["host"])],
        "origins": [], "webvpn_oa_route": HTTP_ROUTE}
    sent = []
    transport = httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200, text="ok"))
    target = "http://" + HTTP_ROUTE["host"] + ":8118/ind/bulletin.nsf/notice"
    with network.CampusHTTP("oa", state, transport=transport) as http, pytest.raises(AppError):
        http.request(target)
    assert sent == []
    with network.CampusHTTP("oa", state, transport=transport, allow_oa_http=True) as http:
        assert http.request(target).text == "ok"
        with pytest.raises(AppError):
            http.request(target, data={"ordinary": "form"})
    assert len(sent) == 1
    header = sent[0].headers["cookie"]
    assert "session=" in header and "oa=" in header
    assert all(name + "=" not in header for name in ("secure", "sso", "central"))


def test_oa_mapping_requires_catalog_route_and_canonicalizes_document_links(monkeypatch):
    state = {"cookies": [], "origins": [], "webvpn_oa_route": HTTP_ROUTE, "webvpn_catalog_verified": True}
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, text='<html><a href="http://oa.stu.edu.cn/a?view=1">synthetic</a></html>',
                              headers={"content-type": "text/html"})

    real = network.CampusHTTP
    monkeypatch.setattr(webvpn, "CampusHTTP", lambda *args, **kwargs: real(
        *args, transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AppError) as failure:
        webvpn._request(state, OA_CANONICAL, lambda response: response.text)
    assert failure.value.code == "oa_http_compat_required" and sent == []
    result = webvpn._request(state, OA_CANONICAL, lambda response: response.text, allow_oa_http=True)
    assert str(sent[0].url) == OA_CANONICAL.replace("https://", "http://").replace(".cn/", ".cn:8118/")
    assert 'href="https://oa-stu-edu-cn.webvpn.stu.edu.cn/a?view=1"' in result
    with pytest.raises(AppError) as failure:
        webvpn._request({"cookies": [], "webvpn_catalog_verified": True}, OA_CANONICAL, lambda response: None)
    assert failure.value.code == "oa_route_unavailable"


@pytest.mark.parametrize("source,url", [("yuketang", "https://changjiang.yuketang.cn/read"),
                                        ("mystu", "https://my.stu.edu.cn/read")])
def test_saved_bearer_applies_only_to_yuketang_and_fixed_https_host(source, url):
    state = {"cookies": [], "origins": [], "yuketang_authorization": "Bearer SYNTHETIC_PRIVATE_BEARER"}
    sent = []
    transport = httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200, text="ok"))
    with network.CampusHTTP(source, state, transport=transport) as http:
        assert http.text(url) == "ok"
        if source == "yuketang":
            with pytest.raises(AppError):
                http.text("https://my.stu.edu.cn/read")
            with pytest.raises(AppError):
                http.text("http://changjiang.yuketang.cn/read")
    assert len(sent) == 1
    assert (sent[0].headers.get("authorization") is not None) is (source == "yuketang")


def test_webvpn_automatic_login_defaults_to_http_without_loading_legacy_browser(monkeypatch):
    seen = []

    def acquire(**kwargs):
        seen.append(kwargs)
        return {"cookies": []}, {"authentication_verified": True}

    monkeypatch.setattr(protocol, "acquire_state", acquire)
    monkeypatch.setattr(webvpn, "_browser_automatic_login", lambda *args, **kwargs: pytest.fail("browser called"))
    credentials = type("SyntheticCredentials", (), {"username": "synthetic-user", "password": PASSWORD})()
    assert webvpn.automatic_login(credentials, lambda: None) == {"cookies": []}
    assert seen[0]["username"] == "synthetic-user" and seen[0]["timeout"] == 50


def test_candidate_http_requests_keep_tls_verification_and_environment_proxy_disabled(monkeypatch):
    settings = []
    actual = httpx.Client

    def client(*args, **kwargs):
        settings.append(kwargs.copy())
        return actual(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    with network.CampusHTTP("oa", {"cookies": []}, transport=httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.ConnectError("synthetic TLS")))) as http, \
            pytest.raises(AppError):
        http.text("https://oa-stu-edu-cn.webvpn.stu.edu.cn/ind/bulletin.nsf")
    assert settings[0]["verify"] is True and settings[0]["trust_env"] is False


def test_optional_renderer_import_is_not_required_for_core_http_modules():
    # A fresh interpreter also catches indirect eager imports without reloading
    # shared modules or changing module identity in the main pytest process.
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'playwright' or name.startswith('playwright.'):
        raise AssertionError('Core HTTP code imported optional browser')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import stu_mcp.auth_http.webvpn
import stu_mcp.auth_http.yuketang
import stu_mcp.network
import stu_mcp.webvpn
import stu_mcp.yuketang_readiness
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_missing_optional_renderer_package_has_safe_error_without_affecting_http(monkeypatch):
    import builtins

    readiness = importlib.import_module("stu_mcp.yuketang_readiness")
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ModuleNotFoundError("synthetic missing optional package")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(AppError) as failure:
        readiness.render_inspection(readiness.Inspection({"question_count": 0}, "", None))
    assert failure.value.code == "render_unavailable"
    assert "synthetic" not in failure.value.message


@pytest.mark.parametrize("body", [b"<Unknown>synthetic private value</Unknown>", b"X" * 2_000_001],
                         ids=["changed-xml", "response-limit"])
def test_unknown_after_sent_password_pauses_future_automatic_attempts(app, rsa_key, monkeypatch, body):
    scenario = Scenario(rsa_key)
    actual_acquire = protocol.acquire_state

    def handler(request):
        response = scenario.handle(request)
        return httpx.Response(200, content=body) if str(request.url) == protocol.PASSWORD else response

    def acquire(**kwargs):
        return actual_acquire(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(protocol, "acquire_state", acquire)
    config = webvpn.WebVPNConfig(app.vault)
    config.configure({"enabled": True, "username": "synthetic-user", "password": PASSWORD,
                      "totp": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"})  # Published RFC 6238 vector.
    with pytest.raises(AppError):
        webvpn.protected_access(app.vault, OA_CANONICAL, lambda response: response.text)
    assert scenario.posts() == [protocol.PASSWORD]
    assert config.status()["enabled"] is False
    with pytest.raises(AppError) as failure:
        webvpn.protected_access(app.vault, OA_CANONICAL, lambda response: response.text)
    assert failure.value.code == "auto_login_paused"
    assert scenario.posts() == [protocol.PASSWORD]
