'use strict';
const $=id=>document.getElementById(id), labels={up:'상승',down:'하락',flat:'횡보'};
let data,days=7,selected='',loading=false;
const pct=x=>x==null?'—':(x*100).toFixed(1)+'%';
const ret=x=>x==null?'대기':(x>0?'+':'')+x.toFixed(2)+'%';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
const svgEl=(tag,attrs={},text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n};
function svgRoot(container,label){const s=container.querySelector('svg')||svgEl('svg',{role:'img'});s.setAttribute('aria-label',label);container.replaceChildren(s);return s}
function renderMetrics(){const m=data.metrics[String(days)],container=$('metrics');container.replaceChildren();$('coverage').textContent='두 모델의 예측이 모두 있는 '+m.evaluated+'종목 기준 · '+days+'일 후 실제 결과';for(const [key,title,color]of [['logistic','로지스틱 회귀','#8cadff'],['ollama','Ollama · Qwen3 4B','#71e2c4']]){const block=el('div');block.append(el('div',title,'metric-title'));for(const [field,label]of [['direction_accuracy','방향 정답'],['return_accuracy','변화율 정답']]){const line=el('div',null,'metric-line'),track=el('div',null,'track'),fill=el('div',null,'fill');fill.style.width=(m.models[key][field]||0)*100+'%';fill.style.background=color;track.append(fill);line.append(el('span',label),track,el('strong',pct(m.models[key][field])));block.append(line)}block.append(el('small','평균 절대 오차 '+(m.models[key].mae_pp==null?'—':m.models[key].mae_pp.toFixed(2)+'%포인트')));container.append(block)}$('baseline').textContent='같은 종목에 항상 상승으로 답하면 '+pct(m.always_up_accuracy)+' · 항상 하락으로 답하면 '+pct(m.always_down_accuracy)}
function drawPrices(row){
  const points=data.prices[selected]||[],s=svgRoot($('price-chart'),row.name+' 실제 종가 · 원(KRW) · 날짜');
  window.investpilotCharts.line(s,{title:row.name+' 실제 종가 · 원(KRW) · 날짜',points:points.map(p=>({x:Date.parse(p.date+'T00:00:00+09:00'),y:typeof p.close==='number'?p.close:NaN})),yLabel:'종가 (원 · KRW)',tooltipUnit:'원 (KRW)',dateOnly:true,marker:Date.parse(data.test_date+'T00:00:00+09:00'),formatY:value=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0}).format(value)});
  $('price-notes').textContent=points.length?'실제 평가일 '+row.actual.exit_date+' · 기준 종가 '+(row.actual.reference_close==null?'—':row.actual.reference_close.toLocaleString()+'원'):'';
}
function drawReturns(row){
  const s=svgRoot($('return-chart'),row.name+' '+days+'일 후 실제·예상 수익률 (%)');
  window.investpilotCharts.bars(s,{title:row.name+' '+days+'일 후 실제·예상 수익률 (%)',periodLabel:data.test_date+' 기준 · '+days+'일 후',values:[{label:'실제 결과',value:row.actual.return_pct,color:'#ffc184'},{label:'로지스틱',value:row.logistic.expected_return_pct,color:'#8cadff'},{label:'Ollama AI',value:row.ollama.expected_return_pct,color:'#71e2c4'}]});
  $('probabilities').replaceChildren();for(const [key,name]of [['logistic','로지스틱'],['ollama','Ollama AI']]){const p=row[key].probabilities;const text=p?name+' · '+['up','flat','down'].map(k=>labels[k]+' '+pct(p[k])).join(' / '):name+' · 확률 수집 대기';$('probabilities').append(el('div',text,'prob-row'));}
}

function renderPrediction(row){
  $('prediction-title').textContent=row.name+' · '+days+'일 예측';
  $('prediction-context').textContent=data.test_date+' 기준 · 당시 자료로 만든 예측과 이후 실제 결과';
  const container=$('prediction-cards');container.replaceChildren();
  for(const [key,title] of [['logistic','로지스틱 회귀'],['ollama','Ollama AI'],['actual','실제 결과']]){
    const f=row[key],card=el('article',null,'prediction-card');card.append(el('h3',title));
    const available=key==='actual'?f.status==='observed':f.status==='ok';
    if(!available){card.append(el('strong',key==='actual'?'관측 대기':'예측 수집 대기','pending'),el('p',key==='actual'?'해당 기간의 실제 가격이 아직 없습니다.':'이 종목·기간의 검증된 예측이 아직 저장되지 않았습니다.','muted'));}
    else{
      const direction=key==='actual'?f.direction:f.prediction;
      card.append(el('strong',(labels[direction]||'—')+' '+ret(key==='actual'?f.return_pct:f.expected_return_pct),'forecast-value '+direction));
      if(f.probabilities)card.append(el('p',['up','flat','down'].map(k=>labels[k]+' '+pct(f.probabilities[k])).join(' · '),'muted'));
      if(key==='actual')card.append(el('p','실제 평가일 '+(f.exit_date||'—'),'muted'));
      else{const score=row.scores[key];card.append(el('p',score?'방향 '+(score.direction_correct?'정답':'오답')+' · 변화율 '+(score.return_correct?'정답':'오답'):'실제 결과가 관측되면 평가합니다.','muted'));}
    }
    container.append(card);
  }
}
function renderEmpty(message){
  $('stock').disabled=true;$('stock').replaceChildren(el('option','저장된 예측 종목 없음'));
  $('prediction-title').textContent='아직 표시할 예측이 없습니다';$('prediction-context').textContent=message;
  $('prediction-cards').replaceChildren();
  const guide=el('div',null,'empty-state');guide.append(el('strong','예측 결과 동기화가 필요합니다'),el('p','이 화면은 저장된 7·30·90일 과거 실험 결과를 비교합니다. 기다리거나 새로고침하는 것만으로 AI 예측이 생성되지는 않습니다.','muted'));
  const a=el('a','현재 AI 모의 테스트 보기 →','empty-link');a.href='/lab';guide.append(a);$('prediction-cards').append(guide);
  for(const [id,text] of [['metrics','평가할 두 모델의 공통 예측이 없습니다. 정확도를 0%로 계산하지 않습니다.'],['price-chart','비교 자료를 동기화하면 종목별 실제 가격이 표시됩니다.'],['return-chart','저장된 예측이 없어 예상 변화율을 표시할 수 없습니다.']])$(id).replaceChildren(el('p',text,'muted'));
  for(const id of ['rows','probabilities','limitations'])$(id).replaceChildren();
  $('coverage').textContent='평가 대기';$('baseline').textContent='';$('price-notes').textContent='';$('row-count').textContent='저장된 비교 종목이 없습니다.';
  $('stock-title').textContent='종목별 실제 가격';$('date').textContent='미동기화';$('progress').textContent='수집 결과 없음';$('progress-bar').value=0;
}
function renderStock(){const row=data.rows.find(r=>r.symbol===selected&&r.days===days);if(!row)return;renderPrediction(row);$('stock-title').textContent=row.name+' · 실제 가격';drawPrices(row);drawReturns(row)}
function scoreCell(row,key){const s=row.scores[key];if(!s)return el('td','대기','pending');const td=el('td');td.append(el('span',s.direction_correct?'정답':'오답',s.direction_correct?'good':'bad'),el('span',' / '),el('span',s.return_correct?'정답':'오답',s.return_correct?'good':'bad'));return td}
function renderTable(){const query=$('search').value.trim().toLowerCase(),rows=data.rows.filter(r=>r.days===days&&(r.name.toLowerCase().includes(query)||r.symbol.includes(query)));$('rows').replaceChildren();for(const row of rows){const tr=el('tr');if(row.symbol===selected)tr.className='selected';const name=el('td',row.name);name.append(el('small',row.symbol));tr.append(name,el('td',ret(row.actual.return_pct),row.actual.direction));for(const key of ['logistic','ollama']){const f=row[key],td=el('td',ret(f.expected_return_pct),f.prediction||'pending');if(f.prediction)td.append(el('small',labels[f.prediction]));tr.append(td,scoreCell(row,key))}tr.onclick=()=>{selected=row.symbol;$('stock').value=selected;renderStock();renderTable()};$('rows').append(tr)}$('row-count').textContent=rows.length+'개 종목 표시 · 미수집 예측은 평가에 포함되지 않습니다.'}
function render(){renderMetrics();renderStock();renderTable()}
async function refresh(){if(loading)return;loading=true;$('refresh').disabled=true;try{const r=await fetch('/api/experiments/top50/comparison',{cache:'no-store'});if(!r.ok)throw Error('실험 자료 조회 실패. 잠시 후 다시 시도하세요.');const next=await r.json();if(!next.ready||!next.rows?.length){data=undefined;const message=next.message||'저장된 비교 종목이 없습니다.';$('notice').textContent=message;renderEmpty(message);return}data=next;$('notice').textContent=(data.complete?'전체 예측 수집 완료':'일부 예측 수집 완료')+' · '+data.completed_forecasts+'/'+data.total_stocks*3+'건 · 화면은 30초마다 저장된 결과를 확인합니다.'+(data.skipped_batches?' 읽는 중인 자료는 다음 갱신에서 다시 확인합니다.':'');$('date').textContent=data.test_date;$('progress').textContent=data.completed_stocks+' / '+data.total_stocks+'종목';$('progress-bar').max=data.total_stocks;$('progress-bar').value=data.completed_stocks;const stocks=data.rows.filter(r=>r.days===7);if(!stocks.some(r=>r.symbol===selected))selected=(stocks.find(r=>r.ollama.status==='ok')||stocks[0])?.symbol||'';$('stock').replaceChildren(...stocks.map(r=>{const o=el('option',r.name+(r.ollama.status==='ok'?'':' · AI 수집 대기'));o.value=r.symbol;return o}));$('stock').disabled=false;$('stock').value=selected;$('limitations').replaceChildren(...data.limitations.map(t=>el('li',t)));$('updated').textContent=(data.dashboard_synced_at?'결과 동기화 '+new Date(data.dashboard_synced_at).toLocaleString('ko-KR')+' · ':'')+'화면 갱신 '+new Date().toLocaleTimeString('ko-KR');render()}catch(e){if(!data)renderEmpty('자료를 불러오지 못했습니다. 새로고침으로 다시 조회하세요.');$('notice').textContent=e.message+(data?' 기존 화면은 마지막 조회 결과입니다.':'')}finally{loading=false;$('refresh').disabled=false}}
for(const b of document.querySelectorAll('[data-days]'))b.onclick=()=>{days=Number(b.dataset.days);for(const other of document.querySelectorAll('[data-days]'))other.setAttribute('aria-pressed',String(other===b));if(data)render()};$('stock').onchange=()=>{selected=$('stock').value;renderStock();renderTable()};$('search').oninput=()=>{if(data)renderTable()};$('refresh').onclick=refresh;refresh();setInterval(refresh,30000);
