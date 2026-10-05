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
    for path in ("/api/status", "/api/login", "/api/logout", "/api/connect", "/api/skill",
                 "/api/transport", "/api/webvpn-auto"):
        assert path in script
    assert "const token = location.hash.slice(1);" in script


def test_setup_page_only_asks_for_what_is_needed():
    _, script, page = load()
    services = [row["data-service"] for row in page.select(".row[data-service]")]
    assert services == ["jw", "mystu", "yuketang", "oa"]
    # Refreshing is the agent's job through MCP; the page has no refresh or profile form.
    assert "/api/refresh" not in script and "/api/profile" not in script
    assert not page.find(string=lambda s: s and "刷新" in s)


def test_credentials_are_never_prefilled_and_always_cleared():
    _, script, page = load()
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        assert page.find(id=field).get("value") is None
        assert page.find(id=field).get("autocomplete") == "off"
    assert page.find(id="vpn-pass")["type"] == "password"
    assert page.find(id="vpn-totp")["type"] == "password"
    assert 'window.addEventListener("pagehide", clearCredentials)' in script


def test_legacy_http_needs_explicit_consent_in_the_page():
    _, script, page = load()
    panel = page.find(id="panel-jw")
    assert panel.has_attr("hidden") and "HTTP" in panel.get_text()
    # Consent is only written from the explicit continue button.
    assert script.count("jw_http_compat: true") == 1
    assert 'getElementById("jw-continue")' in script or '$("jw-continue")' in script
