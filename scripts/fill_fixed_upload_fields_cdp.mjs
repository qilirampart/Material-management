const BASE = 'http://127.0.0.1:9222';
const APPLY = process.argv.includes('--apply');
const FIXED_DEPARTMENTS = [
  'IAP投放组', '代理组', '免费IAA投放部', '免费投放三组', '免费投放二组', '免费投放四组',
  '免费投放组', '厂商-代理', '合肥免费投放组', '客户端一组', '客户端二组', '小说投放一部',
  '广州-自投', '广州自投二组', '广点通投放组-广州', '快应用一组', '快应用三组', '快应用二组',
  '新媒体-自投', '新媒体-自投二组', '杭州小说投放三组', '杭州小说投放二组',
  '杭州小说投放四组', '杭州投放组', '杭州漫剧投放部', '杭州短剧投放一组', '河马代理组',
  '深圳免费投放组', '深圳小说投放部', '深圳投放组', '百度投放组', '自动化投放组',
  '自投四组', '设计部-短剧', '重庆-自投'
];

const targets = await (await fetch(`${BASE}/json/list`)).json();
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
  const apply = ${JSON.stringify(APPLY)};
  const wantedDepartments = ${JSON.stringify(FIXED_DEPARTMENTS)};
  const main = document.querySelector('#iframe9')?.contentDocument;
  const uploadFrame = [...(main?.querySelectorAll('iframe') || [])]
    .filter(frame => frame.src.includes('material_add'))
    .at(-1);
  const doc = uploadFrame?.contentDocument;
  const win = uploadFrame?.contentWindow;
  if (!doc || !win) return { ok: false, error: 'upload form is not open' };

  const selectByXm = name => doc.querySelector('[xm-select="' + name + '"]');
  const optionValues = select => [...(select?.options || [])].map(option => option.value);
  const sponsorSelect = selectByXm('sponsorSelect');
  const deptSelect = selectByXm('deptSelect');
  const missingDepartments = wantedDepartments.filter(name => !optionValues(deptSelect).includes(name));
  const capabilities = {
    jquery: typeof win.jQuery,
    formSelects: typeof win.formSelects,
    layuiFormSelects: typeof win.layui?.formSelects,
    sponsorFound: optionValues(sponsorSelect).includes('张雯燕'),
    missingDepartments
  };
  const xmApi = win.formSelects || win.layui?.formSelects;
  const readXm = name => {
    if (!xmApi?.value) return [];
    const value = xmApi.value(name);
    return Array.isArray(value) ? value.map(item => item?.value ?? item?.name ?? item) : [];
  };
  const checked = name => [...doc.querySelectorAll('input[type=radio][name="' + name + '"]')]
    .find(input => input.checked)?.value || null;
  const readState = () => ({
    sourceType: doc.querySelector('#sourceType')?.value || null,
    propertiesFirst: checked('propertiesFirst'),
    sponsor: readXm('sponsorSelect'),
    materialCategory: checked('secondLevelLabel_2'),
    adTargetType: checked('adTargetType'),
    product: checked('appName'),
    payFlag: checked('payFlag'),
    viewRange: checked('viewRange'),
    departments: readXm('deptSelect'),
    selectedFileCount: [...doc.querySelectorAll('input[type=file]')]
      .reduce((count, input) => count + (input.files?.length || 0), 0)
  });
  if (!apply) return {
    ok: true,
    mode: 'dry-run',
    capabilities,
    current: readState()
  };
  if (!capabilities.sponsorFound || missingDepartments.length) {
    return { ok: false, error: 'required options are missing', capabilities };
  }

  const dispatch = element => {
    element.dispatchEvent(new win.Event('input', { bubbles: true }));
    element.dispatchEvent(new win.Event('change', { bubbles: true }));
  };
  const setRadio = (name, value) => {
    const element = [...doc.querySelectorAll('input[type=radio][name="' + name + '"]')]
      .find(input => input.value === value);
    if (!element) throw new Error('radio not found: ' + name + '=' + value);
    element.checked = true;
    dispatch(element);
  };
  const setXm = (name, values) => {
    if (xmApi?.value) {
      xmApi.value(name, values, true);
      return;
    }
    const select = selectByXm(name);
    for (const option of select.options) option.selected = values.includes(option.value);
    dispatch(select);
  };

  const sourceType = doc.querySelector('#sourceType');
  sourceType.value = 'video';
  dispatch(sourceType);
  setRadio('propertiesFirst', '原创');
  setXm('sponsorSelect', ['张雯燕']);
  setRadio('secondLevelLabel_2', '短剧');
  setRadio('adTargetType', 'play');
  setRadio('appName', '-1');
  setRadio('payFlag', '1');
  setRadio('viewRange', '1');
  setXm('deptSelect', wantedDepartments);

  const verification = readState();
  return { ok: true, mode: 'applied', capabilities, verification };
})()`;

const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
console.log(JSON.stringify(result.result?.value ?? result.exceptionDetails, null, 2));
ws.close();
