"""Check real login/navigation/logout on isolated temporary databases."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.auth import AuthStore


def main():
    root=Path(__file__).resolve().parents[1]
    artifacts=root/'data/ui-verification';artifacts.mkdir(parents=True,exist_ok=True)
    password='browser-test-password-123'
    origin='http://127.0.0.1:8010'
    with tempfile.TemporaryDirectory() as directory:
        temp=Path(directory)
        AuthStore(temp/'auth.db').configure('test-owner',password)
        environment={**os.environ,'INVESTPILOT_AUTH_ENABLED':'true','INVESTPILOT_AUTH_SECURE_COOKIE':'false',
            'INVESTPILOT_PUBLIC_ORIGIN':origin,'INVESTPILOT_AUTH_DB':str(temp/'auth.db'),
            'INVESTPILOT_DB':str(temp/'paper.db'),'INVESTPILOT_AI_DB':str(temp/'ai.db'),
            'NEWS_RSS_URLS':'','TOSS_STREAM_ENABLED':'false'}
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8010'],
            cwd=root,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    if httpx.get(origin+'/health',trust_env=False).status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch()
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/lab/comparison')
                page.wait_for_url('**/login?next=*')
                assert page.request.get(origin+'/api/state').status==401
                page.locator('#username').fill('test-owner');page.locator('#password').fill('wrong')
                page.get_by_role('button',name='로그인 →').click()
                page.wait_for_function("document.getElementById('message').textContent.includes('비밀번호를 확인')")
                page.screenshot(path=str(artifacts/'login-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.locator('#show-password').check();assert page.locator('#password').get_attribute('type')=='text'
                page.locator('#show-password').uncheck()
                page.screenshot(path=str(artifacts/'login-mobile.png'),full_page=True)
                page.locator('#password').fill(password);page.get_by_role('button',name='로그인 →').click()
                page.wait_for_url('**/lab/comparison')
                page.wait_for_function("document.querySelector('.auth-bar span')?.textContent==='test-owner'")
                assert page.request.get(origin+'/api/state').status==200
                assert page.request.post(origin+'/api/auth/logout',headers={'Origin':'https://attacker.example'}).status==403
                page.get_by_role('button',name='로그아웃',exact=True).click();page.wait_for_url('**/login')
                assert page.request.get(origin+'/api/state').status==401
                page.goto(origin+'/login?next=https://attacker.example')
                page.locator('#username').fill('test-owner');page.locator('#password').fill(password)
                page.get_by_role('button',name='로그인 →').click();page.wait_for_url(origin+'/')
                assert not errors,errors
                browser.close()
            print('Real desktop/mobile login, error, visibility toggle, safe redirect, API protection, CSRF and logout: passed')
        finally:
            server.terminate();server.wait(timeout=10)


if __name__=='__main__':main()
