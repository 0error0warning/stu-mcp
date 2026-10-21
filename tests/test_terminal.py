import io
import warnings
from types import SimpleNamespace

import pytest

from stu_mcp import terminal
from stu_mcp.runtime import AppError


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def tty(monkeypatch):
    source, errors = Terminal(), Terminal()
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=source, stderr=errors))
    return source, errors


@pytest.mark.parametrize("stream", ["stdin", "stderr"])
def test_input_requires_both_terminal_streams(tty, monkeypatch, stream):
    monkeypatch.setattr(terminal.sys, stream, io.StringIO())
    called = []
    monkeypatch.setattr(terminal.getpass, "getpass", lambda *_args, **_kwargs: called.append(1))
    with pytest.raises(AppError) as error:
        terminal.secret_input("Hidden: ")
    assert error.value.code == "terminal_required" and not called


def test_hidden_input_never_falls_back_to_echo(tty, monkeypatch):
    fallback = []

    def cannot_hide(*_args, **_kwargs):
        warnings.warn("synthetic terminal failure", terminal.getpass.GetPassWarning, stacklevel=2)
        fallback.append("would read echoed input")
        return "must not be read"

    monkeypatch.setattr(terminal.getpass, "getpass", cannot_hide)
    with pytest.raises(AppError) as error:
        terminal.secret_input("Hidden: ")
    assert error.value.code == "terminal_input_unavailable" and not fallback
    assert "synthetic" not in str(error.value.result())


@pytest.mark.parametrize("cancel", [EOFError, KeyboardInterrupt])
def test_cancellation_is_safe(tty, monkeypatch, cancel):
    def interrupted(*_args, **_kwargs):
        raise cancel

    monkeypatch.setattr(terminal.getpass, "getpass", interrupted)
    with pytest.raises(AppError) as error:
        terminal.secret_input("Hidden: ")
    assert error.value.code == "operation_cancelled"


def test_secret_is_returned_only_to_caller(tty, monkeypatch):
    def hidden(prompt, *, stream):
        assert prompt == "Hidden: " and stream is tty[1]
        return "synthetic-secret"

    monkeypatch.setattr(terminal.getpass, "getpass", hidden)
    assert terminal.secret_input("Hidden: ") == "synthetic-secret"
    assert not tty[0].getvalue() and not tty[1].getvalue()
