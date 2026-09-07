const base = 'http://127.0.0.1:9222';
const targets = await (await fetch(`${base}/json/list`)).json();
const target = targets.find(item => item.type === 'page' && item.url.includes('market.wuread.cn/market-admin'));
if (!target) throw new Error('market page not found');

const ws = new WebSocket(target.webSocketDebuggerUrl);
let sequence = 0;
const pending = new Map();
ws.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  }
};
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, message => message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result));
  ws.send(JSON.stringify({ id, method, params }));
});

const expression = `(() => {
  const main = document.querySelector('#iframe9')?.contentDocument;
  const upload = [...(main?.querySelectorAll('iframe') || [])]
    .filter(frame => frame.src.includes('material_add'))
    .at(-1)?.contentDocument;
  if (!upload) return { error: 'upload form is not open' };
  const wanted = ['类型','性质一级','需求方','素材类别','投放内容','产品','免费付费','可见范围','可见部门'];
  const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
  return [...upload.querySelectorAll('.form-group')].map((group, index) => {
    const label = clean(group.querySelector('.control-label')?.textContent).replace(/^＊\\s*/, '');
    if (!wanted.includes(label)) return null;
    const controls = [...group.querySelectorAll('select,input:not([type=hidden]),textarea')].map(control => ({
      tag: control.tagName,
      type: control.type || '',
      id: control.id || '',
      name: control.name || '',
      value: control.value,
      checked: control.checked,
      options: control.tagName === 'SELECT' ? [...control.options].map(option => ({ text: clean(option.textContent), value: option.value, selected: option.selected })) : undefined
    }));
    const texts = [...group.querySelectorAll('label,span')].map(node => clean(node.textContent)).filter(Boolean).slice(0, 100);
    const xm = [...group.querySelectorAll('[xm-select]')].map(node => ({tag:node.tagName,id:node.id||'',xmSelect:node.getAttribute('xm-select'),text:clean(node.textContent).slice(0,300)}));
    return { index, label, controls, texts, xm };
  }).filter(Boolean);
})()`;
const result = await call('Runtime.evaluate', { expression, returnByValue: true });
console.log(JSON.stringify(result.result?.value ?? result.exceptionDetails, null, 2));
ws.close();
