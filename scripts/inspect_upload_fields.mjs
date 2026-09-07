const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const target = targets.find(item => item.type === 'page' && item.url.startsWith('https://market.wuread.cn/market-admin/'));
const socket = new WebSocket(target.webSocketDebuggerUrl); let seq=0; const pending=new Map();
socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id)}};
await new Promise((r,j)=>{socket.onopen=r;socket.onerror=j});
const evaluate=expression=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,m=>m.error?reject(m.error):resolve(m.result.result.value));socket.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}))});
const result=await evaluate(`(()=>{const d=document.querySelector('#iframe9')?.contentDocument;if(!d)return{error:'iframe unavailable'};const clean=x=>String(x||'').replace(/\\s+/g,' ').trim();const all=[...d.querySelectorAll('input,select,textarea,button,[role=button]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0});return {url:d.location.href, fields:all.map((e,i)=>({i,tag:e.tagName.toLowerCase(),type:e.type||'',id:e.id||'',name:e.name||'',placeholder:clean(e.placeholder),text:clean(e.innerText).slice(0,80),value:e.type==='password'?'[hidden]':(e.value||'').slice(0,80),options:e.tagName==='SELECT'?[...e.options].slice(0,20).map(o=>clean(o.textContent)):undefined}))}})()`);
console.log(JSON.stringify(result,null,2));socket.close();
