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
    window.investpilotCharts.line(svg,{title:'USD/KRW 환율 · 1달러당 원화 · 한국시간',points:points.map(row=>({x:Date.parse(row.observed_at),y:row.rate==null?NaN:Number(row.rate)})),yLabel:'환율 (원 / 1 USD)',tooltipUnit:'원 / 1 USD',formatY:format,color:'#8db4ff'});

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
