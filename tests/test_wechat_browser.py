"""Optional backend lifecycle and network policy, without installed browsers."""
import builtins
import sys
from types import SimpleNamespace

import pytest
from test_wechat_articles import PAGE, URL

from stu_mcp.features.wechat import browser, service


class BrowserError(Exception):
    pass


class BrowserTimeout(BrowserError):
    pass


class Runtime:
    def __init__(self, *, final_url=URL, fail=False):
        self.final_url, self.fail = final_url, fail
        self.closed, self.exited, self.context_closed = 0, 0, 0
        self.launch_options, self.context_options, self.route_handler = {}, {}, None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited += 1

    def launch(self, **kwargs):
        self.launch_options = kwargs
        return self

    def close(self):
        self.closed += 1

    def new_context(self, **kwargs):
        self.context_options = kwargs
        runtime = self

        class Context:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                runtime.context_closed += 1

            def route(self, pattern, handler):
                runtime.route_handler = handler

            def new_page(self):
                return SimpleNamespace(goto=runtime.goto, wait_for_function=lambda *a, **k: None,
                                       evaluate=lambda script: PAGE, url=runtime.final_url)

        return Context()

    def request(self, url, *, navigation=True, resource="document", child=False):
        result = []
        request = SimpleNamespace(url=url, method="GET", resource_type=resource,
                                  is_navigation_request=lambda: navigation,
                                  frame=SimpleNamespace(parent_frame=object() if child else None))
        self.route_handler(SimpleNamespace(request=request, continue_=lambda: result.append("allow"),
                                           abort=lambda: result.append("abort")))
        return result[0]

    def goto(self, *args, **kwargs):
        if self.fail == "network":
            raise BrowserError("synthetic_private_never_echo")
        if self.fail:
            raise BrowserTimeout("synthetic_private_never_echo")
        if self.request(self.final_url) == "abort":
            raise BrowserError("navigation denied")
        return SimpleNamespace(status=200)


@pytest.fixture
def install_runtime(monkeypatch):
    def install(runtime):
        runtime.chromium = runtime
        monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
            Error=BrowserError, TimeoutError=BrowserTimeout, sync_playwright=lambda: runtime))
    return install


def test_explicit_browser_is_fresh_headless_and_closed(install_runtime, monkeypatch):
    runtime = Runtime()
    install_runtime(runtime)
    monkeypatch.setattr(service, "fetch_http", lambda *_: pytest.fail("Explicit browser only"))
    result = service.read_article(URL, backend="browser")
    assert result["ok"] and result["backend"] == "browser" and result["content_ready"]
    assert runtime.launch_options == {"headless": True, "timeout": 10000}
    assert runtime.context_options["service_workers"] == "block"
    assert not runtime.context_options["accept_downloads"]
    assert "storage_state" not in runtime.context_options
    assert runtime.closed == runtime.exited == runtime.context_closed == 1
    assert runtime.request("https://evil.test/track", navigation=False, resource="fetch") == "abort"
    assert runtime.request("https://mp.weixin.qq.com/image", navigation=False, resource="image") == "abort"
    assert runtime.request("https://res.wx.qq.com/script.js", navigation=False, resource="script") == "allow"
    assert runtime.request("https://evil.test/frame", child=True) == "abort"


@pytest.mark.parametrize("final_url,fail,status", [
    ("https://127.0.0.1/s/synthetic_article", False, "unsafe_redirect"),
    ("https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha", False, "captcha_required"),
    (URL, True, "request_timeout"),
    (URL, "network", "network_error"),
])
def test_failed_browser_closes_resources_and_returns_safe_status(install_runtime, final_url, fail, status):
    runtime = Runtime(final_url=final_url, fail=fail)
    install_runtime(runtime)
    result = service.read_article(URL, backend="browser")
    assert not result["ok"] and not result["content_ready"] and result["status"] == status
    assert "synthetic_private" not in str(result)
    assert runtime.closed == runtime.exited == runtime.context_closed == 1


def test_browser_package_is_optional(monkeypatch):
    original = builtins.__import__

    def absent(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("synthetic missing optional dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)
    result = service.read_article(URL, backend="browser")
    assert result["status"] == "browser_unavailable" and result["next_action"] == "install_optional_browser"
    assert not result["content_ready"]


def test_invalid_browser_input_does_not_launch(monkeypatch):
    monkeypatch.setattr(browser, "fetch_browser", lambda *_: pytest.fail("Invalid URL must not launch"))
    assert service.read_article("https://127.0.0.1/s/synthetic_article", backend="browser")["status"] == "invalid_article_url"
