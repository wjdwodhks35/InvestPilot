"""Browser smoke check of the shipped UI with explicitly synthetic responses."""
import json
import subprocess
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright


def sample():
    rows=[]
    for i in range(50):
        symbol=f'{i+1:06}'
        for days in (7,30,90):
            forecast={'status':'ok','prediction':'up','expected_return_pct':2.5,
                      'probabilities':{'up':.6,'flat':.1,'down':.3}}
            rows.append({'symbol':symbol,'name':'테스트 종목 '+str(i+1),'days':days,
                'actual':{'status':'observed','return_pct':3,'direction':'up','exit_date':'2026-06-08','reference_close':10000},
                'logistic':forecast,'ollama':forecast if i==0 else {'status':'pending'},
                'scores':{'logistic':{'direction_correct':True,'return_correct':True},
                    **({'ollama':{'direction_correct':True,'return_correct':True}} if i==0 else {})}})
    models={key:{'direction_accuracy':1,'return_accuracy':1,'mae_pp':.5} for key in ('logistic','ollama')}
    prices=[{'date':(date(2026,4,1)+timedelta(days=i)).isoformat(),'close':10000+i*20} for i in range(150)]
    return {'ready':True,'complete':False,'completed_stocks':1,'completed_forecasts':3,'total_stocks':50,
        'skipped_batches':0,'test_date':'2026-06-01','rows':rows,
        'metrics':{str(d):{'evaluated':1,'models':models,'always_up_accuracy':1,'always_down_accuracy':0} for d in (7,30,90)},
        'prices':{r['symbol']:prices for r in rows},'limitations':['합성 데이터 / synthetic test data']}


def main():
    root=Path(__file__).resolve().parents[1]
    artifacts=root/'data/ui-verification';artifacts.mkdir(parents=True,exist_ok=True)
    server=subprocess.Popen(['python','-m','http.server','8008','--bind','127.0.0.1','--directory',str(root/'app')],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                if httpx.get('http://127.0.0.1:8008/static/comparison.html',trust_env=False).status_code==200:break
            except httpx.ConnectError:pass
            time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1080})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            response=sample()
            page.route('**/api/auth/session',lambda route:route.fulfill(json={'enabled':False}))
            page.route('**/api/experiments/top50/comparison',lambda route:route.fulfill(json=response))
            page.goto('http://127.0.0.1:8008/static/comparison.html')
            page.wait_for_function("document.getElementById('rows').children.length===50")
            assert page.locator('#price-chart svg').count()==1
            assert page.locator('#return-chart svg').count()==1
            assert '수집 완료' in page.locator('#notice').inner_text()
            assert page.locator('#prediction-cards article').count()==3
            assert '상승 +2.50%' in page.locator('#prediction-cards').inner_text()
            assert '상승 60.0%' in page.locator('#prediction-cards').inner_text()
            page.get_by_role('button',name='중기 · 30일').click()
            assert page.get_by_role('button',name='중기 · 30일').get_attribute('aria-pressed')=='true'
            page.locator('#search').fill('000001');assert page.locator('#rows tr').count()==1
            page.locator('#search').fill('');page.locator('#stock').select_option('000002')
            assert '테스트 종목 2' in page.locator('#stock-title').inner_text()
            assert '대기' in page.locator('#return-chart').inner_text()
            assert '예측 수집 대기' in page.locator('#prediction-cards').inner_text()
            response['prices']={}
            page.get_by_role('button',name='새로고침 ↻').click()
            page.wait_for_function("document.getElementById('price-chart').textContent.includes('가격 이력이 없습니다')")
            assert page.locator('#price-notes').inner_text()==''
            assert '상승 +2.50%' in page.locator('#prediction-cards').inner_text()
            page.screenshot(path=str(artifacts/'desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.get_by_role('button',name='장기 · 90일').click()
            page.screenshot(path=str(artifacts/'mobile.png'),full_page=True)
            response.clear();response.update({'ready':False,'message':'실험 결과가 없습니다.'})
            page.get_by_role('button',name='새로고침 ↻').click()
            page.wait_for_function("document.getElementById('notice').textContent==='실험 결과가 없습니다.'")
            assert page.locator('#rows tr').count()==0
            assert page.locator('#stock').is_disabled()
            assert '예측 결과 동기화가 필요합니다' in page.locator('#prediction-cards').inner_text()
            assert page.locator('#prediction-cards a').get_attribute('href')=='/lab'
            assert '예상 변화율을 표시할 수 없습니다' in page.locator('#return-chart').inner_text()
            response.clear();response.update(sample())
            page.get_by_role('button',name='새로고침 ↻').click()
            page.wait_for_function("document.getElementById('rows').children.length===50")
            assert page.locator('#stock').is_enabled()
            assert page.locator('#prediction-cards article').count()==3
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors,errors
            browser.close()
        print('Desktop/mobile charts, period selection, search, pending and empty responses: passed')
    finally:
        server.terminate();server.wait(timeout=10)


if __name__=='__main__':main()
