(() => {
  const get = id => document.getElementById(id);
  let dirty = false;
  const fields = {investment:'dividend-investment',currency:'dividend-currency',annual_yield_pct:'dividend-yield',assumed_tax_pct:'dividend-tax',payments_per_year:'dividend-frequency',share_price:'dividend-price'};
  function message(value) {get('dividend-message').textContent = value;}
  function values() {
    const result = Object.fromEntries(Object.entries(fields).map(([key,id]) => [key,get(id).value]));
    result.payments_per_year = Number(result.payments_per_year);
    result.share_price = result.share_price || null;
    result.fractional = get('dividend-fractional').checked;
    result.symbol = get('dividend-stock').value;
    return result;
  }
  function line(label,value) {
    const p = document.createElement('p'); p.textContent = label + ': ' + value; return p;
  }
  function display(report) {
    const container = get('dividend-results'); container.replaceChildren();
    for (const view of report.converted) {
      const box = document.createElement('article'); box.className = 'portfolio-total';
      const h = document.createElement('h3'); h.textContent = view.currency + ' 예상 배당'; box.append(h);
      const format = value => value === null ? '환율 확인 필요' : new Intl.NumberFormat('ko-KR',{style:'currency',currency:view.currency,maximumFractionDigits:view.currency==='KRW'?0:2}).format(Number(value));
      for (const [key,label] of [['invested','가정 투자금'],['unspent','미투자 잔액'],['annual_gross','연간 세전'],['annual_net','연간 차감 후'],['monthly_average_net','월평균 차감 후'],['per_payment_net','1회당 차감 후']]) box.append(line(label,format(view[key])));
      container.append(box);
    }
    get('dividend-note').textContent = (report.shares === null ? '매수 수량 미계산. ' : '가정 매수 수량 ' + report.shares + '주. ') + report.note + (report.fx ? ' 환산 기준: 1 USD = '+report.fx.rate+' KRW · '+new Date(report.fx.valid_from).toLocaleString('ko-KR') : ' 유효한 환율이 없어 다른 통화 환산은 표시하지 않습니다.');
  }
  async function submit(save) {
    if (!get('dividend-form').reportValidity()) return;
    try {
      const result = await api('broker/dividends/' + (save ? 'scenario' : 'calculate'),save?'PUT':'POST',values()); display(result);
      message(save ? '내 계정에 계산 조건을 저장했습니다.' : '입력한 가정으로 계산했습니다. 아직 저장하지 않았습니다.');
    } catch (error) {message(error.message);}
  }
  get('dividend-form').oninput = () => {dirty=true;};
  get('dividend-form').onsubmit = event => {event.preventDefault();submit(false);};
  get('dividend-save').onclick = () => submit(true);
  get('dividend-stock').onchange = event => {
    const option = event.target.selectedOptions[0];
    if (option.dataset.currency) get('dividend-currency').value = option.dataset.currency;
    if (option.dataset.price) get('dividend-price').value = option.dataset.price;
    dirty=true;
  };
  function stocks(items) {
    const select=get('dividend-stock'), previous=select.value;
    const savedOption=[...select.options].find(option=>option.value===previous);
    select.replaceChildren(new Option('직접 입력',''));
    for (const item of items) {
      if (!['KRW','USD'].includes(item.currency)) continue;
      const option=new Option(item.name||item.symbol,item.symbol);
      option.dataset.currency=item.currency;
      option.dataset.price=item.last_price||item.lastPrice||'';
      select.append(option);
    }
    if (previous && ![...select.options].some(option=>option.value===previous) && savedOption) select.append(savedOption);
    select.value=previous;
  }
  window.addEventListener('investpilot-holdings',event=>stocks(event.detail));
  // The holdings endpoint is a cached read. Opening the planner does not contact the broker.
  async function load() {
    try {
      const real = await api('broker/holdings');
      stocks(real?.items || []);
      const saved = await api('broker/dividends/scenario');
      if (saved && !dirty) {
        for (const [key,id] of Object.entries(fields)) get(id).value = saved.assumptions[key] ?? '';
        get('dividend-fractional').checked=saved.assumptions.fractional;
        const symbol=saved.assumptions.symbol;
        if (symbol && ![...get('dividend-stock').options].some(o=>o.value===symbol)) get('dividend-stock').append(new Option(symbol+' (저장된 가정)',symbol));
        get('dividend-stock').value=symbol; display(saved); message('저장한 계산 조건을 불러왔습니다.');
      }
    } catch (error) {message(error.message);}

  }
  load();
})();
