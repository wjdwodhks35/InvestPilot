"""Exercise owner settings at desktop/mobile sizes with synthetic credentials."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright
from app.auth import AuthStore


def main():
    root=Path(__file__).resolve().parents[1]
    artifacts=root/'data/ui-verification';artifacts.mkdir(parents=True,exist_ok=True)
    origin='http://127.0.0.1:8012'
    with tempfile.TemporaryDirectory() as folder:
        temp=Path(folder);password='browser-settings-test-123'
        AuthStore(temp/'auth.db',database_url='').configure('owner',password)
        env={**os.environ,'INVESTPILOT_DATABASE_URL':'','INVESTPILOT_AUTH_ENABLED':'true',
            'INVESTPILOT_AUTH_SECURE_COOKIE':'false','INVESTPILOT_PUBLIC_ORIGIN':origin,
            'INVESTPILOT_AUTH_DB':str(temp/'auth.db'),'INVESTPILOT_DB':str(temp/'paper.db'),
            'INVESTPILOT_AI_DB':str(temp/'ai.db'),'INVESTPILOT_DATA_DIR':str(temp),
            'INVESTPILOT_SETTINGS_KEY':Fernet.generate_key().decode(),
            'TOSS_CLIENT_ID':'','TOSS_CLIENT_SECRET':'','TOSS_STREAM_ENABLED':'false','NEWS_RSS_URLS':''}
        with (temp/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--port','8012'],cwd=root,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        if httpx.get(origin+'/health',trust_env=False).status_code==200: break
                    except httpx.ConnectError: pass
                    time.sleep(.1)
                with sync_playwright() as p:
                    browser=p.chromium.launch();page=browser.new_page()
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin+'/settings');page.wait_for_url('**/login?next=*')
                    page.locator('#username').fill('owner');page.locator('#password').fill(password)
                    page.get_by_role('button',name='로그인 →').click();page.wait_for_url('**/settings')
                    for width,height,label in [(1440,1000,'desktop'),(390,844,'mobile')]:
                        page.set_viewport_size({'width':width,'height':height})
                        page.locator('#client-id').fill('synthetic-client')
                        page.locator('#client-secret').fill('synthetic-secret')
                        page.locator('#account-seq').fill('synthetic-account')
                        page.get_by_role('button',name='저장',exact=True).click()
                        page.wait_for_function("document.getElementById('message').textContent.includes('저장했습니다')")
                        assert page.locator('#client-secret').input_value()==''
                        assert page.locator('#account-seq').input_value()==''
                        assert 'synthetic-secret' not in page.locator('body').inner_text()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        page.route('**/api/settings/toss/test',lambda route:route.fulfill(json={'ok':True,'message':'테스트 인증 성공'}))
                        page.get_by_role('button',name='연결 테스트',exact=True).click()
                        page.wait_for_function("document.getElementById('message').textContent==='테스트 인증 성공'")
                        page.screenshot(path=str(artifacts/f'settings-{label}.png'),full_page=True)
                        page.once('dialog',lambda dialog:dialog.accept())
                        page.get_by_role('button',name='연결 해제',exact=True).click()
                        page.wait_for_function("document.getElementById('message').textContent.includes('해제했습니다')")
                        page.reload();page.wait_for_function("document.getElementById('status').textContent.includes('인증정보 미설정')")
                        page.locator('summary').click()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors,errors
                    browser.close()
                print('Settings desktop/mobile interactions passed (synthetic broker test).')
            finally:
                server.terminate();server.wait(timeout=10)


if __name__=='__main__': main()
