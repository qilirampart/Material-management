from __future__ import annotations

import json

from src.upload import FIXED_DEPARTMENTS


def build_read_upload_selection_script():
    return """(() => {
  const mainFrame = document.querySelector('#iframe9, iframe[src*="/material/material"]');
  const main = mainFrame?.contentDocument;
  if (!main) return {ok:false, code:'MATERIAL_PAGE_MISSING', message:'请先进入素材管理页面'};
  const uploadFrame = [...main.querySelectorAll('iframe')]
    .filter(frame => frame.src.includes('material_add')).at(-1);
  const doc = uploadFrame?.contentDocument;
  if (!doc) return {ok:false, code:'UPLOAD_FORM_MISSING', message:'请先打开上传素材表单'};
  const readSelected = name => {
    const select = doc.querySelector(`[xm-select="${name}"]`);
    if (!select) return null;
    const option = [...select.selectedOptions].find(item => String(item.value).trim());
    if (option) return {value:String(option.value).trim(), label:String(option.textContent || '').trim()};
    const api = uploadFrame.contentWindow.formSelects || uploadFrame.contentWindow.layui?.formSelects;
    const values = api?.value?.(name, 'val') || [];
    const labels = api?.value?.(name, 'name') || [];
    return values[0] ? {value:String(values[0]).trim(), label:String(labels[0] || values[0]).trim()} : null;
  };
  const director = readSelected('directorSelect');
  const drama = readSelected('bookIdSelect');
  const prefix = drama?.value ? `${drama.value}-` : '';
  const dramaName = prefix && drama.label.startsWith(prefix) ? drama.label.slice(prefix.length).trim() : (drama?.label || '');
  if (!director?.value || !drama?.value)
    return {
      ok:false,
      code:'SELECTION_MISSING',
      message:'请先在平台选择编导和建议书籍/短剧',
      director:director?.value || '',
      directorLabel:director?.label || '',
      dramaId:drama?.value || '',
      dramaName,
    };
  return {
    ok:true,
    code:'SELECTION_READ',
    director:director.value,
    directorLabel:director.label,
    dramaId:drama.value,
    dramaName,
  };
})()"""


def build_upload_file_input_script():
    return """(() => {
  const mainFrame = document.querySelector('#iframe9, iframe[src*="/material/material"]');
  const main = mainFrame?.contentDocument;
  const uploadFrame = main ? [...main.querySelectorAll('iframe')]
    .filter(frame => frame.src.includes('material_add')).at(-1) : null;
  return uploadFrame?.contentDocument?.querySelector('#uploadVideoFile') || null;
})()"""


def build_upload_form_script(*, director, drama_name, drama_platform_id, file_count, request_file_dialog=True):
    payload = json.dumps({
        "director": str(director).strip(),
        "dramaName": str(drama_name).strip(),
        "dramaId": str(drama_platform_id).strip(),
        "departments": FIXED_DEPARTMENTS,
        "fileCount": int(file_count),
        "requestFileDialog": bool(request_file_dialog),
    }, ensure_ascii=False)
    return f"""(() => {{
  const data = {payload};
  const mainFrame = document.querySelector('#iframe9, iframe[src*="/material/material"]');
  const main = mainFrame?.contentDocument;
  if (!main) return {{ok:false, code:'MATERIAL_PAGE_MISSING', message:'请先进入素材管理页面'}};
  const uploadFrame = [...main.querySelectorAll('iframe')]
    .filter(frame => frame.src.includes('material_add')).at(-1);
  if (!uploadFrame?.contentDocument) {{
    const openButton = [...main.querySelectorAll('button,a')]
      .find(element => element.innerText.trim() === '上传素材');
    if (!openButton) return {{ok:false, code:'UPLOAD_ENTRY_MISSING', message:'未找到上传素材入口'}};
    openButton.click();
    return {{ok:false, code:'OPENING_FORM', message:'正在打开上传表单'}};
  }}
  const doc = uploadFrame.contentDocument;
  const win = uploadFrame.contentWindow;
  const api = win.formSelects || win.layui?.formSelects;
  if (!api?.value) return {{ok:false, code:'FORM_API_MISSING', message:'页面多选组件尚未加载'}};
  const dispatch = element => {{
    element.dispatchEvent(new win.Event('input', {{bubbles:true}}));
    element.dispatchEvent(new win.Event('change', {{bubbles:true}}));
  }};
  const radio = (name, value) => {{
    const element = [...doc.querySelectorAll(`input[type=radio][name="${{name}}"]`)]
      .find(item => item.value === value);
    if (!element) throw new Error(`字段不存在：${{name}}=${{value}}`);
    element.checked = true;
    dispatch(element);
  }};
  const setXm = (name, values, additions=[]) => {{
    const select = doc.querySelector(`[xm-select="${{name}}"]`);
    if (!select) throw new Error(`字段不存在：${{name}}`);
    for (const item of additions) {{
      if (![...select.options].some(option => option.value === item.value))
        select.add(new win.Option(item.name, item.value));
    }}
    api.render(name);
    api.value(name, values, true);
  }};
  try {{
    const sourceType = doc.querySelector('#sourceType');
    sourceType.value = 'video';
    dispatch(sourceType);
    radio('propertiesFirst', '原创');
    setXm('sponsorSelect', ['张雯燕']);
    setXm('directorSelect', [data.director]);
    radio('secondLevelLabel_2', '短剧');
    radio('adTargetType', 'play');
    setXm('bookIdSelect', [data.dramaId], [{{name:data.dramaName, value:data.dramaId}}]);
    radio('appName', '-1');
    radio('payFlag', '1');
    radio('viewRange', '1');
    setXm('deptSelect', data.departments);
    const fileInput = doc.querySelector('#uploadVideoFile');
    if (!fileInput) throw new Error('未找到视频文件选择控件');
    if (data.requestFileDialog) {{
      fileInput.click();
      return {{ok:true, code:'FILES_REQUESTED', message:`已填写页面并选择 ${{data.fileCount}} 个文件`}};
    }}
    return {{ok:true, code:'FILE_INPUT_READY', message:'页面字段已填写，正在选择文件'}};
  }} catch (error) {{
    return {{ok:false, code:'FILL_FAILED', message:String(error?.message || error)}};
  }}
}})()"""
