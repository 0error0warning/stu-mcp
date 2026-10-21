"""Natural httpcore traces from an in-memory backend, without school access."""
import logging
import threading

import httpcore
import httpx
import pytest

from stu_mcp.auth_http.transport import HTTPFlow
from stu_mcp.http_privacy import private_http_logging
from stu_mcp.network import CampusHTTP
from stu_mcp.runtime import AppError

PRIVATE_COOKIE = "SYNTHETIC_PRIVATE_COOKIE"
PRIVATE_AUTH = "SYNTHETIC_PRIVATE_AUTHORIZATION"
PRIVATE_QUERY = "SYNTHETIC_PRIVATE_QUERY"
URL = "https://changjiang.yuketang.cn/v2/api/web/courses/list?identity=2&course_id=" + PRIVATE_QUERY


class Stream:
    def __init__(self, *, fail=False):
        self.fail, self.writes = fail, bytearray()
        self.pending = (b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n"
                        b"Set-Cookie: proof=" + PRIVATE_COOKIE.encode() + b"; Secure; Path=/\r\n\r\n{}")

    def read(self, max_bytes, timeout=None):
        if self.fail:
            raise httpcore.ReadError("synthetic response failure")
        result, self.pending = self.pending[:max_bytes], self.pending[max_bytes:]
        return result

    def write(self, buffer, timeout=None):
        self.writes.extend(buffer)

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None


class Backend:
    def __init__(self, stream):
        self.stream = stream

    def connect_tcp(self, *args, **kwargs):
        return self.stream

    def connect_unix_socket(self, *args, **kwargs):
        raise AssertionError("not used")

    def sleep(self, seconds):
        pass


def transport(*, fail=False):
    stream = Stream(fail=fail)
    result = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
    result._pool.close()
    result._pool = httpcore.ConnectionPool(network_backend=Backend(stream))
    return result, stream


def debug_logs(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")


def test_authenticated_business_url_cookie_and_authorization_are_not_logged(caplog):
    debug_logs(caplog)
    backend, stream = transport()
    state = {"cookies": [{"name": "session", "value": PRIVATE_COOKIE, "domain": "changjiang.yuketang.cn",
                          "path": "/", "secure": True, "expires": -1}],
             "origins": [], "yuketang_authorization": "Bearer " + PRIVATE_AUTH}
    with CampusHTTP("yuketang", state, transport=backend) as current:
        assert current.json(URL) == {}
    assert PRIVATE_AUTH.encode() in stream.writes and PRIVATE_COOKIE.encode() in stream.writes
    assert all(value not in caplog.text for value in (PRIVATE_AUTH, PRIVATE_COOKIE, PRIVATE_QUERY))


def test_anonymous_library_trace_remains_visible_after_private_business_request(caplog):
    debug_logs(caplog)
    backend, _ = transport()
    with CampusHTTP("yuketang", {"cookies": [], "origins": []}, transport=backend) as current:
        current.json(URL)
    assert PRIVATE_COOKIE not in caplog.text and PRIVATE_QUERY not in caplog.text
    caplog.clear()
    backend, _ = transport()
    with CampusHTTP("public", transport=backend) as current:
        assert current.json("https://www.stu.edu.cn/?q=" + PRIVATE_QUERY) == {}
    assert PRIVATE_QUERY in caplog.text
    assert "receive_response_headers.complete" in caplog.text and PRIVATE_COOKIE in caplog.text


def test_authentication_trace_stays_private_and_exception_restores_context(caplog):
    debug_logs(caplog)
    backend, _ = transport(fail=True)
    with HTTPFlow("yuketang", ("changjiang.yuketang.cn",), transport=backend) as flow, pytest.raises(AppError) as error:
        flow.get(URL)
    assert error.value.code == "authentication_network_error"
    assert PRIVATE_QUERY not in caplog.text
    logging.getLogger("httpx").info("outside_context_visible")
    assert "outside_context_visible" in caplog.text


def test_nested_private_context_preserves_outer_and_other_thread_logs(caplog):
    debug_logs(caplog)
    logger = logging.getLogger("httpx")
    with private_http_logging():
        logger.info("hidden_outer")
        with private_http_logging(False):
            logger.info("hidden_inner")
        thread = threading.Thread(target=lambda: logger.info("other_thread_visible"))
        thread.start()
        thread.join()
    logger.info("after_nested_visible")
    assert "hidden_outer" not in caplog.text and "hidden_inner" not in caplog.text
    assert "other_thread_visible" in caplog.text and "after_nested_visible" in caplog.text
