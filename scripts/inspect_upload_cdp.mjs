// Read-only inspection of the logged-in upload page. Never requests cookies,
// storage, headers, passwords, or file values.
const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const target = targets.find(item => item.type === 'page' && item.url.startsWith('https://market.wuread.cn/market-admin/'));
if (!target) throw new Error('上传页面未找到，请保持 Edge 页面打开');
const socket = new WebSocket(target.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
socket.onmessage = event => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
};
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
function evaluate(expression) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, msg => msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result.result.value));
    socket.send(JSON.stringify({id, method:'Runtime.evaluate', params:{expression, returnByValue:true, awaitPromise:true}}));
  });
}
const result = await evaluate(`(() => {
  const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
  const field = el => ({tag: el.tagName.toLowerCase(), type: el.type || '', name: el.name || '', id: el.id || '',
    placeholder: clean(el.placeholder), aria: clean(el.getAttribute('aria-label')), text: clean(el.innerText),
    options: el.tagName === 'SELECT' ? [...el.options].map(o => clean(o.textContent)).slice(0, 100) : undefined});
  const elements = [...document.querySelectorAll('input,select,textarea,button,[role=button]')]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).map(field);
  const frames = [...document.querySelectorAll('iframe')].map(el => ({src: el.src, id: el.id, name: el.name, title: el.title}));
  const forms = [...document.forms].map(form => ({action: form.action, method: form.method, fields: [...form.elements].map(field)}));
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,.modal-title,.title')].map(el => clean(el.innerText)).filter(Boolean);
  const body = clean(document.body.innerText).slice(0, 12000);
  const iframe = document.querySelector('#iframe9');
  const frameDoc = iframe && iframe.contentDocument;
  const frameElements = frameDoc ? [...frameDoc.querySelectorAll('input,select,textarea,button,[role=button]')]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).map(field) : [];
  const frameBody = frameDoc ? clean(frameDoc.body.innerText).slice(0, 12000) : '';
  return {url: location.href, title: document.title, headings, elements, forms, frames, body, frameBody, frameElements};
})()`);
console.log(JSON.stringify(result, null, 2));
socket.close();
