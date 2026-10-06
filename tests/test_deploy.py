import pytest
from scripts.deploy import prepare,SECRET_KEY
from app.auth import AuthStore


def settings(tmp_path):
    return {'RENDER_EXTERNAL_URL':'https://investpilot-example.onrender.com',
            'INVESTPILOT_DATA_DIR':str(tmp_path),SECRET_KEY:'deployment-test-password-123','PORT':'10000'}


def test_first_deploy_creates_owner_and_strips_bootstrap_secret(tmp_path):
    source=settings(tmp_path);environment,origin,port=prepare(source)
    assert origin==source['RENDER_EXTERNAL_URL'] and port==10000
    assert SECRET_KEY not in environment
    assert source[SECRET_KEY]=='deployment-test-password-123'
    store=AuthStore(environment['INVESTPILOT_AUTH_DB'])
    token=store.login('admin',source[SECRET_KEY],'local',3600)
    assert store.authenticate(token)=='admin'
    assert source[SECRET_KEY].encode() not in (tmp_path/'auth.db').read_bytes()


def test_redeploy_does_not_reset_password_or_revoke_sessions(tmp_path):
    original=settings(tmp_path);environment,_,_=prepare(original)
    store=AuthStore(environment['INVESTPILOT_AUTH_DB'])
    token=store.login('admin',original[SECRET_KEY],'local',3600)
    changed={**original,SECRET_KEY:'new-bootstrap-password-123'}
    prepare(changed)
    assert store.authenticate(token)=='admin'
    assert store.authenticate(store.login('admin',original[SECRET_KEY],'local',3600))=='admin'
    del changed[SECRET_KEY]
    prepare(changed)


@pytest.mark.parametrize('change',[
    {'RENDER_EXTERNAL_URL':'http://public.example'},
    {'INVESTPILOT_AUTH_ENABLED':'false'},
    {'INVESTPILOT_AUTH_SECURE_COOKIE':'false'},
    {'PORT':'invalid'},
    {'PORT':'70000'},
    {SECRET_KEY:''},
])
def test_unsafe_or_incomplete_deployment_fails_closed(tmp_path,change):
    with pytest.raises(ValueError):prepare({**settings(tmp_path),**change})


def test_persistent_db_paths_cannot_escape_volume(tmp_path):
    with pytest.raises(ValueError):prepare({**settings(tmp_path),'INVESTPILOT_DB':str(tmp_path.parent/'outside.db')})


def test_free_deployment_requires_external_database(tmp_path):
    with pytest.raises(ValueError, match='외부 DB'):
        prepare({**settings(tmp_path), 'INVESTPILOT_STORAGE_MODE': 'postgres'})


def test_free_deployment_rejects_database_without_tls(tmp_path):
    with pytest.raises(ValueError, match='TLS'):
        prepare({**settings(tmp_path), 'INVESTPILOT_STORAGE_MODE': 'postgres',
                 'INVESTPILOT_DATABASE_URL': 'postgresql://local:placeholder@localhost/test?sslmode=disable'})
