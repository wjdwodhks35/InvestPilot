"""Exercise real account storage with a synthetic read-only broker at desktop/mobile sizes."""
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def serve():
    import uvicorn
    from app import main
    async def read(path, **kwargs):
        if path == '/api/v1/holdings':
            return {'items':[
                dict(symbol='005930',name='삼성전자',currency='KRW',quantity='2',averagePurchasePrice='50000',lastPrice='60000',profitLoss={'rate':'0.2'}),
                dict(symbol='AAPL',name='애플',currency='USD',quantity='3',averagePurchasePrice='100',lastPrice='90',profitLoss={'rate':'-0.1'})]}
        if path == '/api/v1/exchange-rate':
            now=datetime.now(timezone.utc)
            return dict(baseCurrency='USD',quoteCurrency='KRW',rate='1400',validFrom=(now-timedelta(seconds=1)).isoformat(),validUntil=(now+timedelta(minutes=10)).isoformat())
        raise ValueError('Only synthetic portfolio reads allowed')
    main.broker.read=read
    import httpx
    from app.dividend_market import DividendMarket
    def provider(request):
        symbol=request.url.params['symbol']
        if request.url.path.endswith('/profile2'):
            return httpx.Response(200,json={'ticker':symbol,'currency':'KRW' if symbol=='TEST-KR' else 'USD'})
        if request.url.path.endswith('/metric'):
            return httpx.Response(200,json={'symbol':symbol,'metric':{} if symbol=='NODATA' else {'dividendYieldIndicatedAnnual':4}})
        return httpx.Response(200,json={'c':50000 if symbol=='TEST-KR' else 100,'t':datetime.now(timezone.utc).timestamp()})
    main.dividend_market=DividendMarket(env={'FINNHUB_API_KEY':'synthetic-test-key',
        'INVESTPILOT_DIVIDEND_SYMBOL_MAP':'{"005930":"TEST-KR"}'},
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    uvicorn.run(main.app,host='127.0.0.1',port=8014)


def main():
    if '--serve' in sys.argv:
        serve();return
    import httpx
    from playwright.sync_api import sync_playwright
    from app.auth import AuthStore
    root=Path(__file__).resolve().parents[1]
    artifacts=root/'data/ui-verification';artifacts.mkdir(parents=True,exist_ok=True)
    origin='http://127.0.0.1:8014'
    with tempfile.TemporaryDirectory() as folder:
        temp=Path(folder)
        AuthStore(temp/'auth.db',database_url='').configure('test-owner','browser-portfolio-test-123')
        env={**os.environ,'INVESTPILOT_DATABASE_URL':'','INVESTPILOT_AUTH_ENABLED':'true',
             'INVESTPILOT_AUTH_SECURE_COOKIE':'false','INVESTPILOT_PUBLIC_ORIGIN':origin,
             'INVESTPILOT_DB':str(temp/'paper.db'),'INVESTPILOT_AI_DB':str(temp/'ai.db'),
             'INVESTPILOT_AUTH_DB':str(temp/'auth.db'),'INVESTPILOT_DATA_DIR':str(temp),
             'TOSS_CLIENT_ID':'','TOSS_CLIENT_SECRET':'','TOSS_ACCOUNT_SEQ':'','TOSS_STREAM_ENABLED':'false',
             'NEWS_RSS_URLS':'','OPENAI_API_KEY':'','INVESTPILOT_MCP_ENABLED':'false','INVESTPILOT_COLLECTION_ENABLED':'false'}
        with (temp/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','scripts.check_portfolio_ui','--serve'],cwd=root,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        if httpx.get(origin+'/health',trust_env=False).status_code==200:break
                    except httpx.ConnectError:pass
                    time.sleep(.1)
                with sync_playwright() as p:
                    browser=p.chromium.launch();page=browser.new_page()
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin+'/login');page.locator('#username').fill('test-owner');page.locator('#password').fill('browser-portfolio-test-123')
                    page.get_by_role('button',name='로그인 →').click();page.wait_for_url(origin+'/')
                    page.locator('#holdings-refresh').click()
                    page.wait_for_function("document.querySelector('#portfolio-totals').textContent.includes('498,000')")
                    page.locator('#fx-open').click()
                    page.wait_for_selector('#fx-dialog[open]')
                    page.wait_for_function("document.querySelectorAll('#fx-chart circle').length>=1")
                    page.locator('#fx-period').select_option('7')
                    page.locator('#fx-close').click()
                    for width,height,label in [(1440,1100,'desktop'),(390,844,'mobile')]:
                        page.set_viewport_size({'width':width,'height':height})
                        page.locator('#portfolio-editor').evaluate('(node)=>node.open=true')
                        page.locator('#category-symbols input[value="005930"]').check()
                        page.locator('#category-symbols input[value="AAPL"]').check()
                        page.locator('#category-name').fill('장기·배당')
                        page.locator('#category-save').click()
                        page.wait_for_function("document.querySelector('#portfolio-message').textContent.includes('저장했습니다')")
                        page.locator('#portfolio-filter').select_option('장기·배당')
                        assert page.locator('#portfolio-positions tr').count()==2
                        assert '₩520,000' in page.locator('#portfolio-totals').inner_text()
                        page.locator('#portfolio-currency').select_option('USD')
                        assert 'US$' in page.locator('#portfolio-totals').inner_text()
                        page.locator('#portfolio-currency').select_option('native')
                        assert page.locator('#portfolio-totals article').count()==2
                        page.locator('#portfolio-currency').select_option('KRW')
                        # Bulk reassignment to unclassified and back.
                        page.locator('#category-unassign').click()
                        page.wait_for_function("document.querySelector('#category-breakdown').textContent.includes('미분류')")
                        page.locator('#category-name').fill('장기·배당');page.locator('#category-save').click()
                        page.wait_for_function("document.querySelector('#category-breakdown').textContent.includes('장기·배당')")
                        # UI text injection must remain literal, never create an image or execute JS.
                        page.locator('#category-name').fill('<img src=x onerror=alert(1)>');page.locator('#category-save').click()
                        page.wait_for_function("document.querySelector('#category-breakdown').textContent.includes('<img')")
                        assert page.locator('#category-breakdown img').count()==0
                        page.locator('#category-name').fill('장기·배당');page.locator('#category-save').click()
                        page.wait_for_function("document.querySelector('#category-breakdown').textContent.includes('장기·배당')")
                        page.locator('#dividend-symbol').fill('NODATA')
                        page.locator('#dividend-lookup').click()
                        page.wait_for_function("document.querySelector('#dividend-message').textContent.includes('자료가 없습니다') || document.querySelector('#dividend-message').textContent.includes('잠시 후')")
                        assert page.locator('#dividend-results article').count()==0
                        assert page.locator('#dividend-yield').input_value()==''
                        page.locator('#dividend-stock').select_option('005930')
                        page.wait_for_function("document.querySelector('#dividend-yield').value==='4'")
                        assert page.locator('#dividend-yield').get_attribute('readonly') is not None
                        page.locator('#dividend-investment').fill('1000000')
                        assert page.locator('#dividend-currency').input_value()=='KRW'
                        page.locator('#dividend-tax').fill('0')
                        page.locator('#dividend-frequency').select_option('4')
                        page.locator('#dividend-form button[type=submit]').click()
                        page.wait_for_function("document.querySelector('#dividend-results').textContent.includes('40,000')")
                        page.locator('#dividend-save').click()
                        page.wait_for_function("document.querySelector('#dividend-message').textContent.includes('저장했습니다')")
                        page.reload()
                        page.wait_for_function("document.querySelector('#dividend-investment').value==='1000000'")
                        assert '장기·배당' in page.locator('#category-breakdown').inner_text()
                        assert page.locator('#dividend-yield').input_value()=='4'
                        page.locator('#fx-open').click()
                        page.wait_for_selector('#fx-dialog[open]')
                        page.wait_for_function("document.querySelectorAll('#fx-chart circle').length>=1")
                        page.screenshot(path=str(artifacts/f'fx-{label}.png'))
                        page.locator('#fx-close').click()
                        page.locator('#portfolio-section').scroll_into_view_if_needed()
                        page.screenshot(path=str(artifacts/f'portfolio-{label}.png'),full_page=True)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors,errors
                    browser.close()
                print('Portfolio categories and dividend scenarios: desktop/mobile passed')
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':main()
