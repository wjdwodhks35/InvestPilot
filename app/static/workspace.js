/* Shared navigation only. Account data and all actions stay in their existing views. */
(() => {
  'use strict';
  const main = document.querySelector('main');
  if (!main || main.classList.contains('login-surface')) return;
  const node = (tag, cls, text) => {const el=document.createElement(tag);if(cls)el.className=cls;if(text)el.textContent=text;return el;};
  const paths = {
    home:'M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
    wallet:'M3 6h17v14H3V6Zm0 0V3h14v3M15 11h6v5h-6Z',
    chart:'M4 3v17h17M7 14l4-5 4 3 6-8',
    lab:'M9 3h6m-5 0v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M8 14h8',
    globe:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z',
    settings:'M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8ZM9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z',
    menu:'M4 6h16M4 12h16M4 18h16', close:'M6 6l12 12M18 6 6 18', arrow:'m9 6 6 6-6 6'
  };
  function icon(key) {const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[key]||paths.chart);svg.append(p);return svg;}
  document.body.classList.add('workspace'); main.id ||= 'workspace-main'; main.tabIndex=-1;
  const skip=node('a','skip-link','본문으로 건너뛰기');skip.href='#'+main.id;document.body.prepend(skip);
  const rail=node('aside','workspace-rail');rail.id='workspace-rail';
  const brand=node('a','workspace-brand');brand.href='/';const mark=node('span','brand-mark','IP');brand.append(mark,node('span','','InvestPilot'));rail.append(brand,node('p','rail-caption','나의 투자 워크스페이스'));
  const menu=node('nav','workspace-menu');menu.setAttribute('aria-label','플랫폼 메뉴');
  const items=[['/','대시보드','home'],['/#real-area','자산·보유종목','wallet'],['/#dividend-section','배당 플래너','chart'],['/lab','국내 AI 실험실','lab'],['/lab/us','미국 AI 실험실','globe'],['/lab/comparison','예측 비교','chart'],['/settings','연결 설정','settings']];
  const research=node('details','workspace-research');research.id='workspace-research';research.open=location.pathname.startsWith('/lab');research.append(node('summary','','전략·AI 실험'));
  const selected=items.find(([href])=>href===location.pathname);
  for(const [href,title,key] of items){const a=node('a','workspace-link');a.href=href;a.append(icon(key),node('span','',title));if(selected?.[0]===href){a.setAttribute('aria-current','page');}if(href.startsWith('/lab')){if(!research.parentNode)menu.append(research);research.append(a);}else menu.append(a);}
  rail.append(menu);
  const top=node('header','workspace-top');const toggle=node('button','workspace-toggle');toggle.type='button';toggle.id='workspace-toggle';toggle.setAttribute('aria-label','메뉴 열기');toggle.setAttribute('aria-controls',rail.id);toggle.setAttribute('aria-expanded','false');toggle.append(icon('menu'));
  const crumbs=node('div','workspace-crumbs');crumbs.append(node('span','','워크스페이스'),icon('arrow'),node('strong','',selected?.[1]||'대시보드'));
  const account=node('div','workspace-account');account.id='workspace-account';top.append(toggle,crumbs,account);
  const backdrop=node('button','workspace-backdrop');backdrop.type='button';backdrop.setAttribute('aria-label','메뉴 닫기');backdrop.hidden=true;
  document.body.prepend(skip,rail,top,backdrop);
  const dock=node('nav','mobile-dock');dock.setAttribute('aria-label','모바일 바로가기');
  for(const [href,title,key] of [['/','홈','home'],['/#real-area','내 자산','wallet'],['/#dividend-section','배당','chart'],['/settings','설정','settings']]){
    const link=node('a','');link.href=href;link.append(icon(key),node('span','',title));dock.append(link);
  }
  function highlightDock(){for(const link of dock.querySelectorAll('a')){const url=new URL(link.href);const active=url.pathname===location.pathname&&(url.hash?url.hash===location.hash:!location.hash);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}}
  highlightDock();window.addEventListener('hashchange',highlightDock);document.body.append(dock);

  document.body.dataset.workspacePage = location.pathname === '/settings' ? 'settings' : location.pathname === '/' ? 'dashboard' : 'research';
  function closeMenu(returnFocus=false){document.body.classList.remove('nav-open');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','메뉴 열기');backdrop.hidden=true;if(returnFocus)toggle.focus();}
  toggle.onclick=()=>{if(document.body.classList.contains('nav-open')){closeMenu();return;}document.body.classList.add('nav-open');toggle.setAttribute('aria-expanded','true');toggle.setAttribute('aria-label','메뉴 닫기');backdrop.hidden=false;rail.querySelector('a').focus();};
  const railClose=node('button','workspace-rail-close');railClose.type='button';railClose.setAttribute('aria-label','탐색 메뉴 닫기');railClose.append(icon('close'));rail.insertBefore(railClose,menu);railClose.onclick=()=>closeMenu(true);
  backdrop.onclick=()=>closeMenu(true);
  rail.addEventListener('click',e=>{if(e.target.closest('a'))closeMenu();});
  document.addEventListener('keydown',e=>{if(!document.body.classList.contains('nav-open'))return;if(e.key==='Escape'){closeMenu(true);return;}if(e.key==='Tab'){const links=[...rail.querySelectorAll('a,button:not([disabled])')];const first=links[0],last=links.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
  window.matchMedia('(min-width: 961px)').addEventListener('change',()=>closeMenu());
  function revealDetails(target){
    for(let parent=target?.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
  }
  function revealHash(hash){
    try {const target=document.getElementById(decodeURIComponent(hash.slice(1)));if(target){revealDetails(target);if(target.tagName==='DETAILS')target.open=true;}}catch{}
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]');if(!link||event.defaultPrevented)return;
    const url=new URL(link.href,location.href);if(url.origin===location.origin&&url.pathname===location.pathname&&url.hash)revealHash(url.hash);
  });
  window.addEventListener('hashchange',()=>revealHash(location.hash));
  document.addEventListener('invalid',event=>revealDetails(event.target),true);
  revealHash(location.hash);
  main.querySelector('.appbar')?.remove();
})();
