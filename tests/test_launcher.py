import io
import pytest
from scripts import start
from app.auth import AuthStore


def test_first_run_creates_owner_without_printing_password(tmp_path,monkeypatch,capsys):
    store=AuthStore(tmp_path/'auth.db')
    class Console(io.StringIO):
        def isatty(self):return True
    monkeypatch.setattr(start.sys,'stdin',Console())
    monkeypatch.setattr('builtins.input',lambda prompt:'owner')
    monkeypatch.setattr(start.getpass,'getpass',lambda prompt:'setup-test-password-123')
    start.ensure_owner(store)
    assert store.configured()
    token=store.login('owner','setup-test-password-123','local',3600)
    assert store.authenticate(token)=='owner'
    assert 'setup-test-password-123' not in capsys.readouterr().out


def test_headless_first_run_requires_explicit_account_setup(tmp_path,monkeypatch):
    store=AuthStore(tmp_path/'auth.db')
    monkeypatch.setattr(start.sys,'stdin',io.StringIO())
    with pytest.raises(ValueError,match='configure_auth'):start.ensure_owner(store)
    assert not store.configured()


def test_ready_links_open_login_and_headless_keeps_links(monkeypatch,capsys):
    opened=[]
    monkeypatch.setattr(start.webbrowser,'open',lambda url,new:opened.append(url) or True)
    start.show_platform('http://127.0.0.1:8123')
    assert opened==['http://127.0.0.1:8123/login']
    assert 'http://127.0.0.1:8123/lab/comparison' in capsys.readouterr().out
    start.show_platform('https://example.com',no_browser=True)
    assert len(opened)==1 and 'https://example.com/login' in capsys.readouterr().out


def test_loopback_cookie_adjustment_does_not_change_public_configuration():
    source={'INVESTPILOT_AUTH_SECURE_COOKIE':'true'}
    assert start.launch_environment(source)['INVESTPILOT_AUTH_SECURE_COOKIE']=='false'
    assert source['INVESTPILOT_AUTH_SECURE_COOKIE']=='true'
    production={**source,'INVESTPILOT_PUBLIC_ORIGIN':'https://example.com'}
    assert start.launch_environment(production)==production


def test_failed_server_does_not_open_browser():
    class Failed:
        def poll(self):return 1
    with pytest.raises(ValueError,match='실패'):start.wait_ready(Failed(),'http://127.0.0.1:8000')
