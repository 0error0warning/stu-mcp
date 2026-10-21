"""Suppress sensitive HTTP library logs only in the current request context."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

_private_request = ContextVar("stu_private_http_request", default=False)


class _PrivateRequestFilter(logging.Filter):
    def filter(self, _record):
        return not _private_request.get()


# httpx INFO includes complete URLs; httpcore DEBUG includes response headers.
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
              "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateRequestFilter())


@contextmanager
def private_http_logging(enabled: bool = True):
    """Do not alter logging levels or another thread's request visibility."""
    if not enabled:
        yield
        return
    token = _private_request.set(True)
    try:
        yield
    finally:
        _private_request.reset(token)
