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
  const frame = [...(main?.querySelectorAll('iframe') || [])].filter(item => item.src.includes('material_add')).at(-1);
  const doc = frame?.contentDocument;
  const win = frame?.contentWindow;
  if (!doc || !win) return {error:'upload form is not open'};
  const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
  const api = win.formSelects || win.layui?.formSelects;
  const result = [];
  for (const group of doc.querySelectorAll('.form-group')) {
    const labelNode = group.querySelector('.control-label');
    const rawLabel = clean(labelNode?.textContent);
    if (!rawLabel.includes('＊')) continue;
    const label = rawLabel.replace(/^＊\\s*/, '');
    const radios = [...group.querySelectorAll('input[type=radio]')];
    const select = group.querySelector('select');
    const xmName = select?.getAttribute('xm-select');
    const xmValues = xmName && api?.value ? api.value(xmName).map(item => item?.value ?? item?.name ?? item) : null;
    result.push({
      label,
      radio: radios.length ? {selected:radios.find(item=>item.checked)?.value || null, values:radios.map(item=>item.value)} : null,
      select: select ? {xmName, value:select.value, xmValues, selectedText:clean(select.selectedOptions?.[0]?.textContent)} : null,
      fileCount: [...group.querySelectorAll('input[type=file]')].reduce((sum,input)=>sum+(input.files?.length||0),0)
    });
  }
  return result;
})()`;
const response = await call('Runtime.evaluate', {expression, returnByValue:true});
console.log(JSON.stringify(response.result?.value ?? response.exceptionDetails, null, 2));
ws.close();
