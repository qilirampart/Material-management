import fs from 'node:fs/promises';

const base = 'http://127.0.0.1:9222';
const targets = await (await fetch(`${base}/json/list`)).json();
const target = targets.find(t => t.type === 'page' && t.url.includes('market.wuread.cn/market-admin'));
if (!target) throw new Error('logged-in market page not found');
const ws = new WebSocket(target.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq; pending.set(id, m => m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)); ws.send(JSON.stringify({id, method, params}));
});
const expression = `(() => {
  const docs = [{name:'top', doc:document}];
  for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) docs.push({name:f.id||f.name||'iframe',doc:f.contentDocument}); } catch {} }
  const out=[];
  const clean=s=>String(s||'').replace(/\\s+/g,' ').trim().slice(0,500);
  const inspect=(root, docName, depth=0)=>{
    if (!root || depth>3) return;
    const all = root.querySelectorAll ? [...root.querySelectorAll('*')] : [];
    for (const el of all) {
      const txt=clean(el.textContent);
      if (txt.includes('添加素材')) {
        const r=el.getBoundingClientRect();
        out.push({doc:docName,tag:el.tagName,id:el.id||'',cls:clean(el.className),text:txt.slice(0,180),visible:!!(r.width||r.height),html:clean(el.outerHTML).slice(0,900)});
      }
      if (el.shadowRoot) inspect(el.shadowRoot, docName+'::shadow', depth+1);
    }
  };
  for (const d of docs) inspect(d.doc,d.name);
  const frames=[...document.querySelectorAll('iframe')].map(f=>({id:f.id,name:f.name,src:f.src,title:f.title}));
  const dialogs=[...document.querySelectorAll('[role=dialog],.modal,.layui-layer,.el-dialog')].map(el=>{const r=el.getBoundingClientRect();return {tag:el.tagName,id:el.id||'',cls:clean(el.className),visible:!!(r.width||r.height),text:clean(el.textContent).slice(0,300),html:clean(el.outerHTML).slice(0,1200)}});
  return {matches:out.slice(-30),frames,dialogs};
})()`;
const res = await call('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
const value = res.result?.value ?? res.exceptionDetails;
await fs.writeFile('output/add-modal-structure.json', JSON.stringify(value,null,2), 'utf8');
console.log(JSON.stringify(value,null,2));
ws.close();
