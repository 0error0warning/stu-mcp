"""Per-page repair CAS tickets, isolated encrypted state, no real school calls."""
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
import pytest
from test_http_repair import School

from stu_mcp.features.repair.http_adapter import open_http
from stu_mcp.features.repair.schema import LIST_URL
from stu_mcp.runtime import AppError


def cookie(name, domain):
    return {"name": name, "value": "SYNTHETIC_PRIVATE", "domain": domain,
            "path": "/", "secure": True, "expires": -1}


class Vault:
    def __init__(self, home):
        self.runtime, self.revision = SimpleNamespace(home=home), b"synthetic-before"

    def login_revision(self, _service):
        return self.revision

    def load(self, _service):
        return {"cookies": [cookie("repair_session", "repair.stu.edu.cn"),
                            cookie("CASTGC", ".stu.edu.cn"), cookie("CASTGC", "repair.stu.edu.cn")],
                "origins": [], "repair_sso_state": {"cookies": [cookie("CASTGC", ".stu.edu.cn"),
                    cookie("JSESSIONID", "sso.stu.edu.cn")], "origins": []}}


class TicketSchool(School):
    def __init__(self, mode="success", *, challenge=None):
        super().__init__(mode)
        self.calls, self.tickets, self.sequence, self.challenge = [], {}, 0, challenge

    def handle(self, request):
        self.calls.append(request)
        cookies = request.headers.get("cookie", "")
        parsed = urlsplit(str(request.url))
        query = parse_qs(parsed.query, keep_blank_values=True)
        if request.url.host == "sso.stu.edu.cn":
            assert request.method == "GET" and "CASTGC=SYNTHETIC_PRIVATE" in cookies
            assert "repair_session=" not in cookies
            assert parsed.path == "/login" and set(query) == {"service"}
            service = query["service"][0]
            if self.challenge == "expired":
                return httpx.Response(200, text='<input type="password">')
            self.sequence += 1
            token = f"SYNTHETIC_TICKET_{self.sequence}"
            self.tickets[token] = service
            callback = service + ("&" if "?" in service else "?") + urlencode({"ticket": token})
            if self.challenge == "external_callback":
                callback = "https://evil.example/?ticket=SYNTHETIC"
            elif self.challenge == "wrong_detail":
                callback = callback.replace("ApplyBill_ID=900001", "ApplyBill_ID=900002")
            elif self.challenge == "duplicate_ticket":
                callback += "&ticket=SYNTHETIC_DUPLICATE"
            elif self.challenge == "missing_ticket":
                callback = service
            return httpx.Response(302, headers={"location": callback})
        assert request.url.host == "repair.stu.edu.cn" and "CASTGC=" not in cookies and "JSESSIONID=" not in cookies
        if request.method == "POST":
            assert "ticket" not in query
            return super().handle(request)
        tokens = query.pop("ticket", [])
        canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))
        if not tokens or self.challenge == "loop":
            service = canonical if self.challenge != "wrong_service" else "https://r.stu.edu.cn/"
            return httpx.Response(302, headers={"location": "https://sso.stu.edu.cn/login?" + urlencode({"service": service})})
        assert len(tokens) == 1 and self.tickets.pop(tokens[0]) == canonical
        return super().handle(httpx.Request("GET", canonical, headers=request.headers))


@pytest.mark.parametrize("mode", ["success", "lost_response"])
def test_each_page_uses_fresh_get_ticket_and_unknown_post_is_never_replayed(tmp_path, mode):
    school, vault = TicketSchool(mode), Vault(tmp_path)
    with open_http(threading.Event(), lambda **_: None, vault=vault,
                   transport=httpx.MockTransport(school.handle)) as current:
        assert all(current.open(school.fields)["matches"].values())
        capture = current.capture()
        current.prepare_receipt()
        result = current.submit(capture)
        assert result["status"] == "submitted" and result["receipt"]["order_id"] == school.order
        current.check()
        assert sum(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts) == 1
        assert all(request.method == "GET" for request in school.calls if request.url.host == "sso.stu.edu.cn")
        assert school.sequence >= 6


@pytest.mark.parametrize("challenge,code", [
    ("wrong_service", "repair_login_required"), ("external_callback", "unsafe_url"),
    ("duplicate_ticket", "unsafe_url"), ("missing_ticket", "unsafe_url"),
    ("expired", "repair_login_required"), ("loop", "repair_authentication_budget"),
])
def test_per_page_ticket_exchange_stops_on_new_challenge_or_changed_route(tmp_path, challenge, code):
    school = TicketSchool(challenge=challenge)
    with open_http(threading.Event(), lambda **_: None, vault=Vault(tmp_path),
                   transport=httpx.MockTransport(school.handle)) as current:
        with pytest.raises(AppError) as error:
            current.read(LIST_URL)
        assert error.value.code == code
        assert len(school.calls) <= 8 and not school.posts


def test_detail_ticket_must_preserve_original_id_and_logout_cancels_further_reads(tmp_path):
    school, vault = TicketSchool(challenge="wrong_detail"), Vault(tmp_path)
    with open_http(threading.Event(), lambda **_: None, vault=vault,
                   transport=httpx.MockTransport(school.handle)) as current:
        with pytest.raises(AppError) as error:
            current.read("https://repair.stu.edu.cn/student_detail.aspx?ApplyBill_ID=900001")
        assert error.value.code == "unsafe_url"
        before = len(school.calls)
        vault.revision = b"synthetic-logout"
        with pytest.raises(AppError) as error:
            current.read(LIST_URL)
        assert error.value.code == "session_changed" and len(school.calls) == before
