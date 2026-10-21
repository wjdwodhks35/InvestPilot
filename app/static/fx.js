(() => {
  const get=id=>document.getElementById(id);
  let state={latest:null,history:[]};
  const format=value=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:4}).format(Number(value));
  function draw() {
    const svg=get('fx-chart'); svg.replaceChildren();
    const days=get('fx-period').value, from=days==='all'?0:Date.now()-Number(days)*86400000;
    const points=state.history.filter(row=>Date.parse(row.observed_at)>=from);
    get('fx-detail').textContent=state.latest ? '1 USD = '+format(state.latest.rate)+' KRW · '+(state.latest.valid?'유효한 참고 환율':'유효기한 지난 조회값') : '아직 조회한 환율이 없습니다.';
    get('fx-chart-caption').textContent=points.length+'개 관측 · '+(state.note||'조회 기록만 표시합니다.');
    const el=(tag,attrs,content)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);if(content)node.textContent=content;svg.append(node);return node;};
    if (!points.length) {el('text',{x:360,y:140,'text-anchor':'middle',fill:'#b8c6d9'},'표시할 조회 기록이 없습니다.');return;}
    const rates=points.map(p=>Number(p.rate)), times=points.map(p=>Date.parse(p.observed_at));
    const min=Math.min(...rates),max=Math.max(...rates),spread=max-min||1,first=times[0],last=times.at(-1);
    const coords=points.map((p,i)=>[last===first?360:70+(times[i]-first)/(last-first)*600,220-(Number(p.rate)-min)/spread*170]);
    for(const value of [min,max])el('text',{x:8,y:220-(value-min)/spread*170,fill:'#b8c6d9','font-size':13},format(value));
    el('line',{x1:70,y1:235,x2:670,y2:235,stroke:'#62738d'});
    if(points.length>1)el('polyline',{points:coords.map(c=>c.join(',')).join(' '),fill:'none',stroke:'#64b5f6','stroke-width':3});
    coords.forEach(([x,y],i)=>{const dot=el('circle',{cx:x,cy:y,r:4,fill:'#80cbc4'});const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=new Date(points[i].observed_at).toLocaleString('ko-KR')+' · '+format(points[i].rate)+' KRW';dot.append(title);});
    el('text',{x:70,y:265,fill:'#b8c6d9','font-size':12},new Date(first).toLocaleString('ko-KR'));
    if(last!==first)el('text',{x:670,y:265,'text-anchor':'end',fill:'#b8c6d9','font-size':12},new Date(last).toLocaleString('ko-KR'));
  }
  window.fxView={async refresh(){
    state=await api('broker/exchange-rate');
    get('fx-open').textContent=state.latest?'1 USD = '+format(state.latest.rate)+' KRW · '+(state.latest.valid?'그래프 보기':'기간 만료 · 그래프 보기'):'USD/KRW 환율 확인 필요 · 그래프 보기';
    get('fx-top-time').textContent=state.latest?'최근 조회 '+new Date(state.latest.observed_at).toLocaleString('ko-KR'):'';
    if(get('fx-dialog').open)draw();
  }};
  document.addEventListener('DOMContentLoaded',()=>{
    get('fx-open').onclick=()=>{get('fx-dialog').showModal();draw();};
    get('fx-close').onclick=()=>get('fx-dialog').close();
    get('fx-period').onchange=draw;
    get('fx-dialog-refresh').onclick=async()=>{
      const button=get('fx-dialog-refresh');button.disabled=true;
      try {await api('broker/exchange-rate/refresh','POST');await window.fxView.refresh();get('fx-dialog-message').textContent='환율을 조회해 기록했습니다.';await refresh();}
      catch(error){get('fx-dialog-message').textContent=error.message;}
      finally{button.disabled=false;}
    };
  });
})();
