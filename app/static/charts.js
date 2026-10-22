/* Labelled charts from observed data only; all displayed timestamps use Asia/Seoul. */
(() => {
  'use strict';
  const configs=new WeakMap();
  const svgNode=(tag,attrs={},text)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))el.setAttribute(key,value);if(text!=null)el.textContent=text;return el;};
  const number=value=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(value);
  function stamp(value,dateOnly=false){const parts=Object.fromEntries(new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'2-digit',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));return [parts.year+'.'+parts.month+'.'+parts.day,...(dateOnly?[]:[parts.hour+':'+parts.minute])];}
  function setup(svg,config){let state=configs.get(svg);if(!state){state={};configs.set(svg,state);if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{const width=Math.round(svg.getBoundingClientRect().width);if(width>0&&width!==state.width)paint(svg,state);});observer.observe(svg);state.observer=observer;}}state.config=config;paint(svg,state);}
  function paint(svg,state){const config=state.config,width=Math.round(svg.getBoundingClientRect().width);state.width=width;const w=Math.max(240,width||600),h=300;svg.replaceChildren();svg.classList.add('unit-chart');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',config.title);svg.style.height=h+'px';svg.style.maxHeight='none';svg.append(svgNode('title',{},config.title));const add=(tag,attrs,text)=>{const el=svgNode(tag,attrs,text);svg.append(el);return el;};const text=(x,y,value,anchor='start')=>add('text',{x,y,'text-anchor':anchor,fill:'#b6c6df','font-size':12},value);
    if(config.type==='bars'){
      const left=86,right=w-62,zero=(left+right)/2,valid=config.values.filter(p=>Number.isFinite(p.value)),bound=Math.max(5,...valid.map(p=>Math.abs(p.value)))*1.25,scale=(right-left)/2/bound;
      text(8,20,'모델 / 실제 결과');text(w-8,20,'수익률 (%)','end');
      for(const tick of [-bound,0,bound]){const x=zero+tick*scale;add('line',{x1:x,x2:x,y1:38,y2:210,stroke:tick===0?'#637b9e':'#26364d','stroke-dasharray':'4 4'});text(x,235,number(tick)+'%',tick<0?'start':tick>0?'end':'middle');}
      config.values.forEach((p,index)=>{const y=65+index*52;text(8,y+15,p.label);if(!Number.isFinite(p.value)){text(zero,y+15,'자료 대기');return;}const length=Math.abs(p.value)*scale;const bar=add('rect',{x:p.value<0?zero-length:zero,y,width:length,height:23,rx:3,fill:p.color});bar.append(svgNode('title',{},p.label+' · '+p.value+'%'));text(w-6,y+16,(p.value>0?'+':'')+number(p.value)+'%','end');});
      text(w/2,279,config.periodLabel,'middle');return;
    }
    const points=config.points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)).slice().sort((a,b)=>a.x-b.x);
    const left=Math.min(100,Math.max(72,w*.2)),right=w-18,top=42,bottom=216;
    text(8,20,config.yLabel);text(w-8,287,config.dateOnly?'날짜 (년.월.일)':'일시 (한국시간)','end');
    add('line',{x1:left,x2:left,y1:top,y2:bottom,stroke:'#506784'});add('line',{x1:left,x2:right,y1:bottom,y2:bottom,stroke:'#506784'});
    if(!points.length){text((left+right)/2,130,'조회 기록이 없습니다.','middle');return;}
    const first=points[0].x,last=points.at(-1).x,low=Math.min(...points.map(p=>p.y)),high=Math.max(...points.map(p=>p.y));
    const pad=high===low?Math.max(Math.abs(low)*.002,1):0,min=low-pad,max=high+pad,span=max-min||1;
    const x=value=>last===first?(left+right)/2:left+(value-first)/(last-first)*(right-left),y=value=>bottom-(value-min)/span*(bottom-top);
    for(let i=0;i<4;i++){const value=min+span*i/3;add('line',{x1:left,x2:right,y1:y(value),y2:y(value),stroke:'#26364d'});text(left-8,y(value)+4,(config.formatY||number)(value),'end');}
    if(points.length>1)add('polyline',{points:points.map(p=>x(p.x)+','+y(p.y)).join(' '),fill:'none',stroke:config.color||'#7cd6b4','stroke-width':2.5});
    for(const p of points){const dot=add('circle',{cx:x(p.x),cy:y(p.y),r:points.length===1?4:2.5,fill:config.color||'#7cd6b4'});dot.append(svgNode('title',{},stamp(p.x,config.dateOnly).join(' ')+' · '+(config.formatY||number)(p.y)+' '+config.tooltipUnit));}
    const ticks=last===first?[first]:w>=550?[first,(first+last)/2,last]:[first,last];
    for(const value of ticks){const anchor=last===first?'middle':value===first?'start':value===last?'end':'middle';stamp(value,config.dateOnly).forEach((label,i)=>text(x(value),240+i*16,label,anchor));}
    if(Number.isFinite(config.marker)&&config.marker>=first&&config.marker<=last){const marker=x(config.marker);add('line',{x1:marker,x2:marker,y1:top,y2:bottom,stroke:'#ffc184','stroke-dasharray':'5 4'});text(Math.min(Math.max(left,marker),right-70),34,'예측 기준일');}
  }
  window.investpilotCharts={line:(svg,config)=>setup(svg,{...config,type:'line'}),bars:(svg,config)=>setup(svg,{...config,type:'bars'})};
})();
