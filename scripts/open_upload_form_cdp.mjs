const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const target = targets.find(item => item.type === 'page' && item.url.startsWith('https://market.wuread.cn/market-admin/'));
const socket = new WebSocket(target.webSocketDebuggerUrl); let seq=0; const pending=new Map();
socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id)}};
await new Promise((r,j)=>{socket.onopen=r;socket.onerror=j});
const evaluate=expression=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,m=>m.error?reject(m.error):resolve(m.result.result.value));socket.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}))});
const result=await evaluate(`(()=>{const d=document.querySelector('#iframe9')?.contentDocument;if(!d)return 'iframe unavailable';const button=[...d.querySelectorAll('button')].find(b=>b.innerText.trim()==='上传素材');if(!button)return 'upload button unavailable';button.click();return 'clicked upload form';})()`);
console.log(result); socket.close();
