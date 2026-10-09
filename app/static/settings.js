const el=id=>document.getElementById(id);
let busy=false;
async function api(method='GET',data){const response=await fetch('/api/settings/toss'+(method==='TEST'?'/test':''),{method:method==='TEST'?'POST':method,headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined,cache:'no-store'});if(response.status===401){location.href='/login';throw Error('로그인이 필요합니다.')}const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'설정을 처리하지 못했습니다.');return result;}
let formDirty=false;
el('toss-form').addEventListener('input',()=>formDirty=true);
function show(s){
 const source=s.config_source==='environment'?'서버 환경설정(.env / 환경변수) 사용 중':s.config_source==='saved_account'?'내 계정에 저장된 설정 사용 중'+(s.configured?'':' · 인증정보 미설정'):s.configured?'인증정보 저장됨':'인증정보 미설정';
 const storage=s.storage_error||(!s.storage_ready?'암호화 키 미설정: 화면에서 키 저장·변경은 사용할 수 없습니다. 환경설정의 키로 조회·연결 테스트는 가능합니다.':'');
 el('status').textContent=source+' · Client ID '+(s.client_id_set?'설정됨':'미설정')+' · Secret '+(s.client_secret_set?'설정됨':'미설정')+' · 계좌 '+(s.account_set?'저장됨':'미설정')+' · 시세 '+(s.connected?'연결됨':s.stream_enabled?'연결 대기':'꺼짐')+(storage?' · '+storage:'');
 el('client-id').placeholder=s.client_id_set?'이미 설정됨 · 변경할 때만 입력':'Client ID 입력';
 el('client-secret').placeholder=s.client_secret_set?'이미 설정됨 · 변경할 때만 입력':'Client Secret 입력';
 if(!formDirty)el('stream-enabled').checked=s.stream_enabled;
 el('save').disabled=!s.storage_ready;
 el('load-accounts').disabled=!s.configured||!!s.storage_error;
 el('test').disabled=!s.configured||!!s.storage_error;
 el('disconnect').disabled=!s.storage_ready||!s.configured;
}

async function action(fn){if(busy)return;busy=true;el('toss-form').querySelectorAll('button').forEach(b=>b.disabled=true);try{await fn();}catch(e){el('message').textContent=e.message;}finally{busy=false;try{show(await api());}catch(e){el('message').textContent=e.message;}}}
el('toss-form').onsubmit=e=>{e.preventDefault();action(async()=>{const data={client_id:el('client-id').value.trim()||null,client_secret:el('client-secret').value||null,account_seq:el('account-seq').value.trim()||null,stream_enabled:el('stream-enabled').checked};try{formDirty=false;show(await api('PUT',data));el('message').textContent='설정을 저장했습니다. 연결 테스트로 인증을 확인하세요.';}finally{el('client-secret').value='';el('account-seq').value='';}});};
el('test').onclick=()=>action(async()=>{el('message').textContent=(await api('TEST')).message;});
el('load-accounts').onclick=()=>action(async()=>{const response=await fetch('/api/broker/accounts',{cache:'no-store'});const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'계좌 조회 실패');el('accounts').replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent='계좌를 선택하세요';el('accounts').append(blank);result.forEach((a,i)=>{const option=document.createElement('option');option.value=a.account_seq;option.textContent=(i+1)+'번 계좌 · '+a.account_type;el('accounts').append(option);});el('accounts-label').hidden=false;el('message').textContent=result.length?'계좌를 선택한 뒤 저장하세요.':'조회된 계좌가 없습니다.';});
el('accounts').onchange=()=>{el('account-seq').value=el('accounts').value;};
el('disconnect').onclick=()=>{if(!confirm('저장된 토스 연결 정보를 해제할까요?'))return;action(async()=>{show(await api('DELETE'));el('toss-form').reset();formDirty=false;el('accounts').replaceChildren();el('accounts-label').hidden=true;el('message').textContent='토스 연결을 해제했습니다.';});};
api().then(s=>{show(s);if(s.configured&&!s.storage_error)el('load-accounts').click();}).catch(e=>el('message').textContent=e.message);
setInterval(()=>{if(!busy)api().then(show).catch(e=>el('message').textContent=e.message);},10000);

async function loadUsers(){const response=await fetch('/api/auth/users',{cache:'no-store'});if(response.status===403)return;if(!response.ok)return;const users=await response.json();el('user-management').hidden=false;el('user-list').replaceChildren();users.forEach(u=>{const item=document.createElement('li');item.textContent=u.username+(u.admin?' · 관리자':'');el('user-list').append(item);});}
el('user-form').onsubmit=async e=>{e.preventDefault();el('add-user').disabled=true;try{const response=await fetch('/api/auth/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:el('new-username').value.trim(),password:el('new-password').value})});const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'계정 추가 실패');el('user-message').textContent='새 계정을 추가했습니다.';el('user-form').reset();await loadUsers();}catch(err){el('user-message').textContent=err.message;}finally{el('new-password').value='';el('add-user').disabled=false;}};
loadUsers().catch(()=>{});

let outboundIP='';
el('check-ip').onclick=async()=>{el('check-ip').disabled=true;el('copy-ip').hidden=true;outboundIP='';el('ip-result').textContent='서버 IP 확인 중…';try{const response=await fetch('/api/settings/outbound-ip',{cache:'no-store'});if(response.status===401){location.href='/login';return;}const result=await response.json();if(!response.ok)throw Error(result.detail||'IP 확인 실패');outboundIP=result.ip;el('ip-result').textContent='현재 서버 발신 IP: '+outboundIP+' · 확인 시각: '+new Date(result.checked_at*1000).toLocaleTimeString();el('copy-ip').hidden=false;}catch(e){el('ip-result').textContent=e.message;}finally{el('check-ip').disabled=false;}};
el('copy-ip').onclick=async()=>{try{await navigator.clipboard.writeText(outboundIP);el('ip-result').textContent='IP를 복사했습니다: '+outboundIP;}catch(e){el('ip-result').textContent='아래 IP를 직접 복사하세요: '+outboundIP;}};
