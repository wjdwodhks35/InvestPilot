(() => {
  const get = id => document.getElementById(id);
  let dirty = false, sequence = 0, quoteSequence = 0;
  const fields = {investment:'dividend-investment',currency:'dividend-currency',assumed_tax_pct:'dividend-tax',payments_per_year:'dividend-frequency'};
  function message(value) {get('dividend-message').textContent=value;}
  function values() {
    const result=Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,get(id).value]));
    result.payments_per_year=Number(result.payments_per_year);
    result.fractional=get('dividend-fractional').checked;
    result.symbol=get('dividend-symbol').value.trim();
    return result;
  }
  function line(label,value) {const p=document.createElement('p');p.textContent=label+': '+value;return p;}
  function market(quote) {
    get('dividend-yield').value=quote?quote.annual_yield_pct:'';
    get('dividend-price').value=quote?.share_price??'';
    if(quote)get('dividend-currency').value=quote.currency;
    get('dividend-source').textContent=quote?
      quote.source+' · 예상 연 배당률 '+quote.annual_yield_pct+'% (제공처 연환산 지표) · 조회 '+new Date(quote.fetched_at).toLocaleString('ko-KR')+
      (quote.price_at?' · 주가 시각 '+new Date(quote.price_at).toLocaleString('ko-KR'):' · 주가 자료 없음: 투자금 전액 적용 가정')+
      ' · 조회 시각은 예상치 산정 기준일과 다를 수 있습니다.':'예상 배당률 자료를 조회해야 계산할 수 있습니다.';
  }
  function display(report) {
    const container=get('dividend-results');container.replaceChildren();
    market(report.market);
    for(const view of report.converted) {
      const box=document.createElement('article');box.className='portfolio-total';
      const h=document.createElement('h3');h.textContent=view.currency+' 예상 배당';box.append(h);
      const format=value=>value===null?'환율 확인 필요':new Intl.NumberFormat('ko-KR',{style:'currency',currency:view.currency,maximumFractionDigits:view.currency==='KRW'?0:2}).format(Number(value));
      for(const [key,label] of [['invested','가정 투자금'],['unspent','미투자 잔액'],['annual_gross','연간 세전'],['annual_net','연간 차감 후'],['monthly_average_net','월평균 차감 후'],['per_payment_net','1회당 차감 후']])box.append(line(label,format(view[key])));
      container.append(box);
    }
    get('dividend-note').textContent=(report.shares==null?'매수 수량 미계산. ':'가정 매수 수량 '+report.shares+'주. ')+report.note+
      (report.fx?' 환산 기준: 1 USD = '+report.fx.rate+' KRW · '+new Date(report.fx.valid_from).toLocaleString('ko-KR'):' 유효한 환율이 없어 다른 통화 환산은 표시하지 않습니다.');
  }
  async function lookup() {
    const current=++quoteSequence,symbol=get('dividend-symbol').value.trim();
    market(null);get('dividend-results').replaceChildren();
    if(!symbol){message('배당을 확인할 종목을 선택하세요.');return;}
    try {
      const quote=await api('broker/dividends/quote/'+encodeURIComponent(symbol));
      if(current!==quoteSequence||symbol!==get('dividend-symbol').value.trim())return;
      market(quote);message('종목의 예상 연 배당률을 조회했습니다. 투자금액을 입력해 계산하세요.');
    } catch(error){if(current===quoteSequence)message(error.message);}
  }
  async function submit(save) {
    if(!get('dividend-form').reportValidity())return;
    const current=++sequence,request=values();
    get('dividend-results').replaceChildren();
    try {
      const result=await api('broker/dividends/'+(save?'scenario':'calculate'),save?'PUT':'POST',request);
      if(current!==sequence)return;
      display(result);message(save?'내 계정에 종목과 투자 조건을 저장했습니다.':'조회한 종목의 예상 배당률로 계산했습니다.');
    } catch(error){if(current===sequence){market(null);message(error.message);}}
  }
  get('dividend-form').oninput=()=>{dirty=true;sequence++;get('dividend-results').replaceChildren();};
  get('dividend-symbol').oninput=()=>{quoteSequence++;market(null);};
  get('dividend-form').onsubmit=event=>{event.preventDefault();submit(false);};
  get('dividend-save').onclick=()=>submit(true);
  get('dividend-lookup').onclick=lookup;
  get('dividend-stock').onchange=event=>{
    const option=event.target.selectedOptions[0];
    get('dividend-symbol').value=option.value;
    dirty=true;lookup();
  };
  function stocks(items) {
    const select=get('dividend-stock'),previous=select.value;
    select.replaceChildren(new Option('종목 선택',''));
    for(const item of items)if(['KRW','USD'].includes(item.currency))select.append(new Option(item.name||item.symbol,item.symbol));
    if(previous&&![...select.options].some(o=>o.value===previous))select.append(new Option(previous,previous));
    select.value=previous;
  }
  window.addEventListener('investpilot-holdings',event=>stocks(event.detail));
  async function load() {
    try {
      stocks((await api('broker/holdings'))?.items||[]);
      const saved=await api('broker/dividends/scenario');
      if(saved&&!dirty) {
        if(saved.assumptions){
          for(const [key,id]of Object.entries(fields))get(id).value=saved.assumptions[key]??'';
          get('dividend-fractional').checked=saved.assumptions.fractional;
          get('dividend-symbol').value=saved.assumptions.symbol;
        }
        if(saved.status==='available')display(saved);
        else {market(null);get('dividend-note').textContent=saved.note;}
        message(saved.status==='available'?'저장된 종목과 투자 조건을 불러왔습니다.':saved.note);
      }
    } catch(error){message(error.message);}
  }
  load();
})();
