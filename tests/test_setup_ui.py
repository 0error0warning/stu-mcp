from pathlib import Path

from bs4 import BeautifulSoup

WEB = Path(__file__).parents[1] / "src" / "stu_mcp" / "web"


def load():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    return html, (WEB / "app.js").read_text(encoding="utf-8"), BeautifulSoup(html, "html.parser")


def test_setup_page_is_local_and_csp_compatible():
    html, script, page = load()
    assert not page.find_all("style") and not page.find_all(style=True)
    assert not page.find_all("script", src=False)
    assert {link.get("href") for link in page.find_all("link")} == {"/style.css"}
    assert {tag.get("src") for tag in page.find_all("script")} == {"/app.js"}
    assert "innerHTML" not in script and "console." not in script
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    for path in ("/api/status", "/api/login", "/api/login/input", "/api/login/cancel", "/api/logout"):
        assert path in script
    assert "const token = location.hash.slice(1);" in script


def test_setup_page_exposes_user_choice_without_nested_configuration_cards():
    _, script, page = load()
    assert [row["data-profile"] for row in page.select(".row[data-profile]")] == ["school", "yuketang", "duifene", "webvpn", "med_jw", "smartcard"]
    assert len(page.select(".card")) == 1
    assert page.find(id="login-panel").has_attr("hidden")
    assert page.find(id="unintegrated-services")
    assert not page.find(id="advanced-login") and not page.find(id="school-sessions")
    assert page.find(id="cli-commands") and "setup_command" in script
    for path in ("/api/refresh", "/api/profile", "/api/connect", "/api/skill"):
        assert path not in script
    assert "host_cli_required" not in script


def test_private_inputs_are_not_prefilled_or_saved_to_browser_storage():
    _, script, page = load()
    for field in ("login-user", "login-pass", "login-code", "login-callback", "login-token", "login-captcha"):
        assert page.find(id=field).get("value") is None
    for field in ("login-pass", "login-callback", "login-token"):
        assert page.find(id=field)["type"] == "password"
    assert "localStorage" not in script and "sessionStorage" not in script
    assert 'window.addEventListener("pagehide"' in script
    assert '$("login-qr").removeAttribute("src")' in script
    assert '$("login-captcha-image").removeAttribute("src")' in script


def test_setup_does_not_duplicate_service_choices_or_expose_transport_policy():
    html, script, page = load()
    assert not page.find(id="school-options") and not page.find(id="school-http")
    assert "票据" not in html and "会话已保存" not in script
    assert "/api/transport" not in script and "/api/webvpn-auto" not in script
    assert "capability_catalog" in script
    assert page.find(id="login-token").find_parent("form")["id"] == "credentials-form"
