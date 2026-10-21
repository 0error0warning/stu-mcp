"""Synthetic provider documents only; public signing values never leave the decoder."""
import pytest

from stu_mcp import charging
from stu_mcp.features.charging.parser import (
    device_protocol,
    discover_script,
    parse_configuration,
    parse_envelope,
    parse_ports,
)
from stu_mcp.runtime import AppError

SCRIPT = "/static/js/index.abcdef12.js"
CONFIG = '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET"}'


def changed(function, *args):
    with pytest.raises(AppError) as failure:
        function(*args)
    assert failure.value.code == "schema_changed"
    assert "SYNTHETIC_SECRET" not in str(failure.value.result())


@pytest.mark.parametrize("markup", [
    f'<script src="{SCRIPT}"></script>',
    f'<div><script defer src=.{SCRIPT}></script></div>',
    f'<script src="https://wx.isfdz.com{SCRIPT}"></script>',
    f'<script src="https://cdn.example/other.js"></script><script type=module src="{SCRIPT}"></script>',
    f'<script src="{SCRIPT}"></script><script src="{SCRIPT}"></script>',
])
def test_script_wrapping_attributes_and_identical_duplicates_keep_the_observed_path(markup):
    assert discover_script(markup) == SCRIPT


@pytest.mark.parametrize("markup", [
    None, "", "<h1>维护中</h1>",
    f'<script src="http://wx.isfdz.com{SCRIPT}"></script>',
    f'<script src="https://evil.example{SCRIPT}"></script>',
    f'<script src="{SCRIPT}?token=SYNTHETIC_SECRET"></script>',
    f'<script src="{SCRIPT}#fragment"></script>',
    f'<script src="{SCRIPT}"></script><script src="/static/js/index.123456ab.js"></script>',
    f'<script src="{SCRIPT}" src="/static/js/index.123456ab.js"></script>',
    '<script src="http://[invalid"></script>',
])
def test_unknown_or_ambiguous_script_discovery_fails_without_guessing(markup):
    changed(discover_script, markup)


@pytest.mark.parametrize("source", [
    "var config=" + CONFIG + ";",
    'var config={app_secret:"SYNTHETIC_SECRET",base:"https://example.test",app_id:"SYNTHETIC_ID"};',
    '''var config={"app_id":'SYNTHETIC_ID',"app_secret":'SYNTHETIC_SECRET'};''',
    "var a=" + CONFIG + ";var b=" + CONFIG + ";",
])
def test_unique_literal_configuration_keeps_values_and_does_not_evaluate_js(source):
    config = parse_configuration(source, 42.5)
    assert config.app_id == "SYNTHETIC_ID" and config.secret == "SYNTHETIC_SECRET"
    assert config.loaded_at == 42.5 and "SYNTHETIC" not in repr(config)


@pytest.mark.parametrize("source", [
    None, "", "function config(){return fetch('/unknown')}",
    '{app_id:"SYNTHETIC_ID"};{app_secret:"SYNTHETIC_SECRET"}',
    CONFIG + ';{app_id:"another",app_secret:"another"}',
    '{app_id:"SYNTHETIC_ID",app_id:"another",app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:9,app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID",app_secret:null}',
    '{app_id:"SYNTHETIC_ID",app_secret:{value:"SYNTHETIC_SECRET"}}',
    '{app_id:"' + "x" * 129 + '",app_secret:"SYNTHETIC_SECRET"}',
])
def test_configuration_missing_conflicting_or_nonliteral_fields_are_explicit_errors(source):
    changed(parse_configuration, source, 42.5)


@pytest.mark.parametrize("payload", [None, [], {}, {"code": True}, {"code": "200"},
                                      {"code": 200.0}, {"code": 200},
                                      {"code": 500, "msg": {"token": "SYNTHETIC_SECRET"}}])
def test_envelope_field_changes_are_not_empty_successes(payload):
    changed(parse_envelope, payload)


@pytest.mark.parametrize("code,status", [(401, "access_denied"), (403, "access_denied"), (429, "rate_limited")])
@pytest.mark.parametrize("message", ["设备不在线", "签名错误", {"token": "SYNTHETIC_SECRET"}])
def test_provider_wide_rejection_cannot_be_downgraded_to_device_failure(code, status, message):
    with pytest.raises(AppError) as exc:
        parse_envelope({"code": code, "msg": message})
    assert exc.value.code == status and exc.value.http_status == 200
    assert "SYNTHETIC_SECRET" not in str(exc.value.result())


def test_envelope_keeps_explicit_data_and_bounded_renewal_signal():
    data = [{"num": 1, "state": 1, "extra": "ignored by ports"}]
    assert parse_envelope({"code": 200, "data": data, "extra": True}).data is data
    assert parse_envelope({"code": 200, "data": None}).data is None
    assert not parse_envelope({"code": 200, "data": data}).renew_config
    assert parse_envelope({"code": 500, "msg": "签名错误"}).renew_config
    assert parse_envelope({"code": 500, "msg": "时间戳已过期"}).renew_config


def test_legacy_ports_identity_and_unknown_states_stay_compatible():
    assert charging.parse_ports is parse_ports
    result = parse_ports([{"num": 2, "state": 1024, "raw": "SYNTHETIC_SECRET"},
                          {"num": 1, "state": 1}], 4)
    assert result["counts"] == {"total": 4, "observed": 2, "free": 1, "occupied": 0,
                                "fault": 0, "unknown": 3}
    assert "SYNTHETIC_SECRET" not in str(result)


@pytest.mark.parametrize("kind,protocol", [(1, "beforeProtocol"), (6, "afterProtocol")])
def test_protocol_selection_keeps_observed_integer_types(kind, protocol):
    assert device_protocol(kind) == protocol


@pytest.mark.parametrize("kind", [None, True, "6", 6.0, {}, [], 999])
def test_protocol_drift_does_not_guess_a_branch(kind):
    with pytest.raises(AppError) as exc:
        device_protocol(kind)
    assert exc.value.code == "unsupported_device"
