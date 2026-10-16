import json
import pytest
from scripts.check_mcp import inspect


@pytest.fixture
def environment():
    from cryptography.fernet import Fernet
    return {
        'INVESTPILOT_MCP_ENABLED':'true',
        'INVESTPILOT_PUBLIC_ORIGIN':'https://portfolio.example.test',
        'INVESTPILOT_MCP_RESOURCE':'https://portfolio.example.test/mcp',
        'INVESTPILOT_MCP_ISSUER':'https://identity.example.test/',
        'INVESTPILOT_MCP_JWKS_URL':'https://identity.example.test/jwks',
        'INVESTPILOT_MCP_CLIENT_IDS':'approved-client',
        'INVESTPILOT_DATABASE_URL':'postgresql://test:private-password@db.example.test/app?sslmode=require',
        'INVESTPILOT_SETTINGS_KEY':Fernet.generate_key().decode(),
    }


def test_ready_does_not_claim_live_connection_or_touch_db(environment, monkeypatch, tmp_path):
    import psycopg
    def forbidden(*args, **kwargs):
        pytest.fail('Preflight must not connect or create storage')
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    monkeypatch.chdir(tmp_path)
    original = environment.copy()
    report = inspect(environment)
    assert report['configuration_ready'] and not report['live_connection_verified']
    assert environment == original and not list(tmp_path.iterdir())
    output = json.dumps(report)
    for value in environment.values():
        if len(value) > 10:
            assert value not in output
    assert 'private-password' not in output


@pytest.mark.parametrize('key,value,check', [
    ('INVESTPILOT_MCP_ENABLED','false','enabled'),
    ('INVESTPILOT_AUTH_ENABLED','false','web_auth'),
    ('INVESTPILOT_AUTH_SECURE_COOKIE','false','web_auth'),
    ('INVESTPILOT_PUBLIC_ORIGIN','http://portfolio.example.test','public_origin'),
    ('INVESTPILOT_PUBLIC_ORIGIN','https://portfolio.example.test/subpath','public_origin'),
    ('INVESTPILOT_MCP_RESOURCE','https://other.example.test/mcp','resource'),
    ('INVESTPILOT_MCP_ISSUER','https://user:private-password@identity.example.test/','issuer'),
    ('INVESTPILOT_MCP_JWKS_URL','https://identity.example.test:invalid/jwks','jwks'),
    ('INVESTPILOT_MCP_CLIENT_IDS','client, another','clients'),
    ('INVESTPILOT_MCP_CLIENT_IDS','','clients'),
    ('INVESTPILOT_DATABASE_URL','postgresql://test:private-password@db.example.test/app?sslmode=disable','database'),
    ('INVESTPILOT_DATABASE_URL','','database'),
    ('INVESTPILOT_SETTINGS_KEY','private-password','settings_key'),
])
def test_blocks_bad_configuration_without_echoing_values(environment, key, value, check):
    environment[key] = value
    report = inspect(environment)
    assert not report['configuration_ready']
    assert next(c for c in report['checks'] if c['check'] == check)['status'] == 'fail'
    assert 'private-password' not in json.dumps(report)


def test_render_origin_fallback_matches_deploy_entrypoint(environment):
    environment['RENDER_EXTERNAL_URL'] = environment.pop('INVESTPILOT_PUBLIC_ORIGIN')
    assert inspect(environment)['configuration_ready']


def test_empty_environment_fails_safely():
    report = inspect({})
    assert not report['configuration_ready'] and not report['live_connection_verified']
