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


def captcha_image(size=(8, 4), *, kind="PNG"):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=kind)
    return buffer.getvalue()


@pytest.mark.parametrize("kind,media_type", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_captcha_is_rendered_only_at_tty_and_answer_is_private(tty, monkeypatch, kind, media_type):
    observed = []
    monkeypatch.setattr(terminal.getpass, "getpass", lambda prompt, **_: observed.append(prompt) or "0246")
    assert terminal.captcha_input(captcha_image(kind=kind), media_type=media_type) == "0246"
    output = tty[1].getvalue()
    assert "▄" in output and "\x1b[38;2;" in output
    assert "0246" not in output and not tty[0].getvalue() and len(observed) == 1


@pytest.mark.parametrize("image,media_type", [(b"", "image/png"), (b"x" * 65537, "image/jpeg"),
                                             (b"<svg>private</svg>", "image/svg+xml"),
                                             (b"private malformed image", "image/png")],
                         ids=["empty", "oversized", "svg", "malformed"])
def test_unsupported_captcha_stops_before_prompt(tty, monkeypatch, image, media_type):
    prompts = []
    monkeypatch.setattr(terminal.getpass, "getpass", lambda *_args, **_: prompts.append(1))
    with pytest.raises(AppError) as error:
        terminal.captcha_input(image, media_type=media_type)
    assert error.value.code == "captcha_display_unavailable" and not prompts
    assert "private" not in str(error.value) and not tty[1].getvalue()


def test_captcha_dimensions_and_declared_type_are_checked_before_rendering(tty, monkeypatch):
    prompts = []
    monkeypatch.setattr(terminal.getpass, "getpass", lambda *_args, **_: prompts.append(1))
    for image, media_type in ((captcha_image((513, 2)), "image/png"),
                              (captcha_image(), "image/jpeg")):
        with pytest.raises(AppError) as error:
            terminal.captcha_input(image, media_type=media_type)
        assert error.value.code == "captcha_display_unavailable"
    assert not prompts and not tty[1].getvalue()


def test_captcha_requires_human_tty_and_valid_four_digit_answer(tty, monkeypatch):
    monkeypatch.setattr(terminal.getpass, "getpass", lambda *_args, **_: "１２３４")
    with pytest.raises(AppError) as error:
        terminal.captcha_input(captcha_image(), media_type="image/png")
    assert error.value.code == "invalid_authentication_input"
    monkeypatch.setattr(terminal.sys, "stderr", io.StringIO())
    with pytest.raises(AppError) as error:
        terminal.captcha_input(b"not inspected", media_type="image/png")
    assert error.value.code == "terminal_required"
