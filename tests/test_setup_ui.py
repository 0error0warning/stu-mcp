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
    for path in ("/api/status", "/api/login", "/api/login/input", "/api/login/cancel", "/api/logout", "/api/webvpn-auto"):
        assert path in script
    assert "const token = location.hash.slice(1);" in script


def test_setup_page_exposes_user_choice_without_nested_configuration_cards():
    _, script, page = load()
    assert [row["data-profile"] for row in page.select(".row[data-profile]")] == ["school", "yuketang", "duifene", "webvpn"]
    assert len(page.select(".card")) == 1
    assert page.find(id="login-panel").has_attr("hidden")
    assert page.find(id="unintegrated-services")
    assert not page.find(id="advanced-login").has_attr("open")
    assert "stu-mcp login school" in page.find(id="cli-panel").get_text()
    for path in ("/api/refresh", "/api/profile", "/api/connect", "/api/skill"):
        assert path not in script
    assert "host_cli_required" not in script


def test_private_inputs_are_not_prefilled_or_saved_to_browser_storage():
    _, script, page = load()
    for field in ("login-user", "login-pass", "login-code", "login-callback", "vpn-user", "vpn-pass", "vpn-totp"):
        assert page.find(id=field).get("value") is None
    for field in ("login-pass", "login-callback", "vpn-pass", "vpn-totp"):
        assert page.find(id=field)["type"] == "password"
    assert "localStorage" not in script and "sessionStorage" not in script
    assert 'window.addEventListener("pagehide"' in script
    assert '$("login-qr").removeAttribute("src")' in script


def test_http_permission_is_explicit_and_only_for_current_login():
    _, script, page = load()
    consent = page.find(id="school-http")
    assert consent["type"] == "checkbox" and not consent.has_attr("checked")
    assert "仅本次" in page.find(id="school-http-choice").get_text()
    assert "HTTPS" in page.find(id="school-http-note").get_text()
    assert "allow_http_callback = true" in script
    assert "jw_http_compat: true" not in script
