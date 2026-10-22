/* Saved account categories. Financial totals are computed on the server with Decimal. */
(() => {
  const get = id => document.getElementById(id);
  let report = null;
  function money(value, currency) {
    if (value === null || value === undefined) return '확인 필요';
    return new Intl.NumberFormat('ko-KR', {style: 'currency', currency, maximumFractionDigits: currency === 'KRW' ? 0 : 2}).format(Number(value));
  }
  function text(tag, value, className) {
    const node = document.createElement(tag); node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  function loss(value, currency) {
    return text('span', money(value, currency), value === null ? 'muted' : Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '');
  }
  function selected() {
    return [...get('category-symbols').querySelectorAll('input:checked')].map(input => input.value);
  }
  function draw() {
    if (!report) return;
    const mode = get('portfolio-currency').value, filter = get('portfolio-filter').value;
    const totals = get('portfolio-totals'), groups = get('category-breakdown'), body = get('portfolio-positions');
    totals.replaceChildren(); groups.replaceChildren(); body.replaceChildren();
    get('portfolio-note').textContent = report.note;
    get('portfolio-asof').textContent = report.retrieved_at ? '보유종목 조회: ' + new Date(report.retrieved_at).toLocaleString('ko-KR') + ' · 현재 단가는 마지막 조회값입니다.' : '보유종목을 조회하면 원금과 평가금액을 표시합니다.';
    get('portfolio-fx').textContent = report.fx ? '참고 환율: 1 USD = ' + report.fx.rate + ' KRW · 기준 ' + new Date(report.fx.valid_from).toLocaleString('ko-KR') + ' · 유효기한 ' + new Date(report.fx.valid_until).toLocaleString('ko-KR') : '유효한 환율 없음 · 거래통화 금액은 표시하며 환산이 필요한 합계는 확인 필요로 표시합니다.';
    if (!report.loaded || !report.converted.some(view => view.positions.length)) {
      groups.append(text('p', report.loaded ? '보유종목이 없습니다.' : '위의 보유종목 조회 버튼을 눌러주세요.', 'empty')); return;
    }
    const views = mode === 'native' ? report.currencies : report.converted.filter(view => view.currency === mode);
    for (const view of views) {
      if (!['KRW', 'USD'].includes(view.currency)) continue;
      const visibleGroups = view.categories.filter(group => !filter || group.category === filter);
      // Filtered totals use the category's server-calculated metrics, never client-side sums.
      const summary = filter ? visibleGroups[0] : view;
      if (!summary) continue;
      const card = text('article', '', 'portfolio-total'); card.append(text('h3', (filter || '전체 보유자산') + ' · ' + view.currency));
      for (const [key, label] of [['cost','매입 원금'], ['value','현재 평가금액'], ['profit','총 평가손익']]) {
        const row = text('div', '', 'portfolio-metric'); row.append(text('span', label), key === 'profit' ? loss(summary[key], view.currency) : text('strong', money(summary[key], view.currency))); card.append(row);
      }
      card.append(text('small', '수익률 ' + (summary.return_pct === null ? '확인 필요' : summary.return_pct.toFixed(2) + '%'))); totals.append(card);
      for (const group of visibleGroups) {
        const box = text('article', '', 'portfolio-category'); box.append(text('h3', group.category), text('small', view.currency));
        box.append(text('p', '원금 ' + money(group.cost, view.currency)), text('p', '평가금액 ' + money(group.value, view.currency)));
        const profit = text('p','평가손익 '); profit.append(loss(group.profit, view.currency)); box.append(profit);
        groups.append(box);
      }
      const positions = mode === 'native' ? report.converted.find(v => v.currency === view.currency).positions.filter(p => p.currency === view.currency) : view.positions;
      for (const position of positions.filter(p => !filter || p.category === filter)) {
        const row = document.createElement('tr');
        const label = text('td', position.name + ' (' + position.symbol + ')'); label.append(text('small', position.category, 'portfolio-position-category')); row.append(label);
        row.append(text('td', position.quantity ?? '확인 필요'), text('td', ['KRW','USD'].includes(position.currency) ? money(position.last_price, position.currency) : '지원 외 통화'), text('td', money(position.cost, view.currency)), text('td', money(position.value, view.currency)));
        const profit = document.createElement('td'); profit.append(loss(position.profit, view.currency)); row.append(profit);
        const labels=['종목 / 카테고리','수량','현재 단가','매입 원금','평가금액','평가손익'];
        [...row.children].forEach((cell,index)=>cell.setAttribute('data-label',labels[index]));
        body.append(row);
      }
    }
    get('portfolio-table-caption').textContent = (filter || '전체 카테고리') + ' · ' + (mode === 'native' ? '거래통화별 금액' : mode + ' 환산 금액');
  }
  async function save(category) {
    const symbols = selected();
    if (!symbols.length) {get('portfolio-message').textContent = '분류할 종목을 선택하세요.'; return;}
    const button = get('category-save'); button.disabled = true;
    try {
      await api('broker/categories/batch', 'PUT', {symbols, category});
      const updated = await api('broker/breakdown');
      window.portfolioView.render(updated);
      get('portfolio-message').textContent = '내 계정에 카테고리를 저장했습니다.';
    } catch (error) {get('portfolio-message').textContent = error.message;}
    finally {button.disabled = false;}
  }
  window.portfolioView = {render(value) {
    report = value;
    const oldFilter = get('portfolio-filter').value;
    const names = [...new Set(value.converted.flatMap(view => view.categories.map(group => group.category)))].sort();
    get('portfolio-filter').replaceChildren(new Option('전체 카테고리', ''), ...names.map(name => new Option(name, name)));
    get('portfolio-filter').value = names.includes(oldFilter) ? oldFilter : '';
    get('portfolio-category-names').replaceChildren(...names.map(name => new Option(name, name)));
    const checked = new Set(selected()), options = get('category-symbols'); options.replaceChildren();
    const positions = value.converted[0].positions;
    window.dispatchEvent(new CustomEvent('investpilot-holdings', {detail: positions}));
    for (const position of positions) {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = position.symbol; input.checked = checked.has(position.symbol);
      label.append(input, document.createTextNode(position.name + ' · ' + position.category)); options.append(label);
    }
    get('category-save').disabled = !positions.length;
    get('category-unassign').disabled = !positions.length;
    draw();
  }};
  document.addEventListener('DOMContentLoaded', () => {
    get('portfolio-currency').onchange = draw;
    get('portfolio-filter').onchange = draw;
    get('category-form').onsubmit = event => {event.preventDefault(); save(get('category-name').value.trim());};
    get('category-unassign').onclick = () => save('미분류');
    get('portfolio-fx-refresh').onclick = async () => {
      const button = get('portfolio-fx-refresh'); button.disabled = true;
      try {await api('broker/exchange-rate/refresh', 'POST'); window.portfolioView.render(await api('broker/breakdown')); await window.fxView.refresh(); get('portfolio-message').textContent = '환율을 갱신했습니다.';}
      catch (error) {get('portfolio-message').textContent = error.message;}
      finally {button.disabled = false;}
    };
  });
})();
