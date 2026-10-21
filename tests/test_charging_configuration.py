"""Synthetic JS lexical boundaries; no evaluation, HTTP, signing or real configuration."""
import pytest

from stu_mcp.features.charging.parser import parse_configuration
from stu_mcp.runtime import AppError

CONFIG = '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET"}'


def changed(source):
    with pytest.raises(AppError) as failure:
        parse_configuration(source, 10)
    assert failure.value.code == "schema_changed"
    assert "SYNTHETIC" not in str(failure.value.result())


@pytest.mark.parametrize("decoy", [
    '''const note="{app_id:'DECOY',app_secret:'DECOY'}";''',
    '''const note='{app_id:"DECOY",app_secret:"DECOY"}';''',
    '/* {app_id:"DECOY",app_secret:"DECOY"} */',
    '// {app_id:"DECOY",app_secret:"DECOY"}\n',
    'const note=`{app_id:"DECOY",app_secret:"DECOY"}`;',
    'const note=`${ {app_id:"DECOY",app_secret:"DECOY"} }`;',
    'const note=`${ `nested ${ {app_id:"DECOY",app_secret:"DECOY"} }` }`;',
    'const pattern=/{app_id:"DECOY",app_secret:"DECOY"}/;',
    'if (enabled) /{app_id:"DECOY",app_secret:"DECOY"}/.test(text);',
    'while (enabled) /{app_id:"DECOY",app_secret:"DECOY"}/.test(text);',
])
def test_strings_comments_templates_and_regex_are_not_configuration(decoy):
    changed(decoy)
    config = parse_configuration(decoy + "const config=" + CONFIG, 10)
    assert config.app_id == "SYNTHETIC_ID" and config.secret == "SYNTHETIC_SECRET"


@pytest.mark.parametrize("source", [
    '{app_id:"SYNTHETIC_ID"+suffix,app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID".trim(),app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET"||fallback}',
    '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET",...other}',
    '{...other,app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET",["app_id"]:"OTHER"}',
    '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET",get app_id(){return "OTHER"}}',
    '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET",app_id}',
    '{app_id:"SYNTHETIC_ID",app_secret:`SYNTHETIC_SECRET`}',
    r'{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_\x53ECRET"}',
])
def test_computed_values_and_possible_identity_overrides_are_not_plain_literals(source):
    changed(source)


@pytest.mark.parametrize("source", [
    '{app_id:"SYNTHETIC_ID",ui:{lang:"zh"},app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID",ui:[{lang:"zh"},"}"],app_secret:"SYNTHETIC_SECRET"}',
    'function boot(){const config=' + CONFIG + ';return config;}',
    '{app_id:/* { decoy } */"SYNTHETIC_ID",app_secret:\n"SYNTHETIC_SECRET",}',
    '{app_id:"SYNTHETIC_ID",extra:"contains { } \\\" quote",app_secret:"SYNTHETIC_SECRET"}',
])
def test_unrelated_nested_fields_and_wrappers_do_not_hide_direct_configuration(source):
    config = parse_configuration(source, 10)
    assert config.app_id == "SYNTHETIC_ID" and config.secret == "SYNTHETIC_SECRET"
    assert config.loaded_at == 10 and "SYNTHETIC" not in repr(config)


@pytest.mark.parametrize("source", [
    '{app_id:"SYNTHETIC_ID",nested:{app_secret:"SYNTHETIC_SECRET"}}',
    '{nested:{app_id:"SYNTHETIC_ID"},app_secret:"SYNTHETIC_SECRET"}',
    '{app_id:"SYNTHETIC_ID"};{app_secret:"SYNTHETIC_SECRET"}',
    CONFIG + ';{app_id:"OTHER",app_secret:"OTHER"}',
    CONFIG + ';{app_id:"OTHER"}',
    CONFIG + ';/* unterminated',
    CONFIG + ';const x="unterminated',
    CONFIG + ';const x=`unterminated',
    CONFIG + ';const x=(]',
])
def test_incomplete_ambiguous_or_unfinished_documents_fail_without_cross_object_pairs(source):
    changed(source)
