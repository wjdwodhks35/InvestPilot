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
        output=(temp/'launcher.log').open('w')
        server=subprocess.Popen([sys.executable,'-m','scripts.start','--no-browser','--port','8010'],
            cwd=root,env=environment,stdout=output,stderr=output)
        try:
            for _ in range(100):
                try:
                    if httpx.get(origin+'/health',trust_env=False).status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.1)
            for _ in range(50):
                if '플랫폼 준비 완료' in (temp/'launcher.log').read_text():break
                time.sleep(.1)
            log=(temp/'launcher.log').read_text()
            assert origin+'/login' in log and origin+'/lab/comparison' in log
            assert password not in log
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
                page.route('**/api/broker/holdings',lambda route:route.fulfill(json={'items':[{'symbol':'005930','name':'삼성전자','quantity':'1','averagePurchasePrice':'60000','lastPrice':'70000','currency':'KRW','profitLoss':{'rate':'0.1667'}}]}))
                page.route('**/api/broker/breakdown',lambda route:route.fulfill(json={'loaded':True,'currencies':[{'currency':'KRW','total':'70000','categories':[{'category':'AI 반도체','value':'70000','weight_pct':100}]}]}))
                page.route('**/api/market/quotes',lambda route:route.fulfill(json=[{'symbol':'005930','price':70000,'at':'2026-10-08T07:00:00+00:00'}]))
                for width,label in [(1440,'desktop'),(390,'mobile')]:
                    page.set_viewport_size({'width':width,'height':1000})
                    page.reload()
                    page.wait_for_function("document.getElementById('category-breakdown').textContent.includes('100.0%')")
                    assert '삼성전자' in page.locator('#live-prices').inner_text()
                    assert '005930' not in page.locator('#live-prices').inner_text()
                    assert page.locator('.quote-card').count()==6
                    page.get_by_role('button',name='안랩 모의 주문 선택',exact=True).click()
                    assert page.locator('#order select[name=symbol]').input_value()=='053800'
                    page.get_by_role('link',name='내 실제 계좌',exact=True).click()
                    assert page.locator('#real-holdings').is_visible()
                    page.locator('#paper-source').select_option('toss_live')
                    page.locator('#source-save').click()
                    page.wait_for_function("document.getElementById('message').textContent.includes('소스를 저장')")
                    assert page.request.get(origin+'/api/state').json()['price_source']=='toss_live'
                    page.locator('#category-name').fill('반도체 테스트')
                    page.locator('#category-form button').click()
                    page.wait_for_function("document.getElementById('message').textContent.includes('카테고리 저장')")
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(artifacts/f'portfolio-{label}.png'),full_page=True)
                page.goto(origin+'/lab')
                page.locator('#ai-data').click()
                page.wait_for_function("document.getElementById('learning-status').textContent.includes('가중치 학습 미실행')")
                page.locator('#ai-unpause').click()
                page.wait_for_function("document.getElementById('ai-result').textContent.includes('정지를 해제')")
                assert not errors,errors
                browser.close()
            print('Real desktop/mobile login, error, visibility toggle, safe redirect, API protection, CSRF and logout: passed')
        finally:
            server.terminate();server.wait(timeout=10);output.close()


if __name__=='__main__':main()
