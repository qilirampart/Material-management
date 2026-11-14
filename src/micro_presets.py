"""Local named micro-innovation settings, separate from batches and credentials."""
import json
import re
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from src.batch import save_json
from src.subtitle_cover import SUBTITLE_DEFAULTS,validate_assets
from src.picture_effects import PICTURE_DEFAULTS
from types import SimpleNamespace
from src.material_variants import VariantOptions, RESOURCE_TYPES


SETTING_KEYS = set(asdict(VariantOptions())) - {'mode', 'uploader', 'variants'}
LEGACY_KEYS=SETTING_KEYS-{'zoom_mode','zoom_amount','zoom_period','background_path','pip_path',
    'pip_scale','pip_x','pip_y','pip_opacity','randomize','random_seed','random_ranges','resource_pools',
    'text_tracks','watermark_start','watermark_duration','watermark_scroll','watermark_scroll_speed',
    'music_delay','music_duration','music_fade_in','music_fade_out','intro_path','outro_path',
    'intro_duration','outro_duration','transition','transition_duration','bookend_audio','regions',
    'crop_mode','crop_left','crop_right','crop_top','crop_bottom','clip_mode','range_start','range_duration'}-set(SUBTITLE_DEFAULTS)-set(PICTURE_DEFAULTS)
RECOMMENDED_NAME = '推荐 · 明显变化'
RECOMMENDED = {key: value for key, value in asdict(VariantOptions(
    foreground_scale=.8, vertical_position=.25, brightness=.02, contrast=1.12,
    saturation=1.18, sharpen=.4, trim_start=.3, trim_end=.3, speed=1.06,
    output_fps=30)).items() if key in SETTING_KEYS}


def validate_settings(settings):
    if not isinstance(settings, dict) or not LEGACY_KEYS<=set(settings)<=SETTING_KEYS:
        raise ValueError('收藏参数不完整或版本不兼容')
    settings={**{k:v for k,v in asdict(VariantOptions()).items() if k in SETTING_KEYS},**settings}
    if not isinstance(settings['resource_pools'],dict) or any(k not in RESOURCE_TYPES or not isinstance(v,str)
            for k,v in settings['resource_pools'].items()):
        raise ValueError('收藏资源池格式无效')
    validate_assets(SimpleNamespace(**settings),check_files=False)
    # A moved music/image file must not prevent loading the user's other favorites.
    values = dict(settings, watermark_path='', music_path='', background_path='',pip_path='',intro_path='',outro_path='',
        audio_mode='original',resource_pools={},subtitle_path='',cover_path='',cover_mode='none')
    VariantOptions(**values).validate()
    if settings['audio_mode'] not in {'original','mute','mix','replace'}:
        raise ValueError('收藏的音频模式无效')
    if not all(isinstance(settings[k], str) for k in ('watermark_path','music_path','background_path','pip_path','intro_path','outro_path','subtitle_path','cover_path')):
        raise ValueError('收藏文件路径无效')
    return dict(settings)


def read_presets(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('presets'), dict):
        raise ValueError('收藏文件格式不正确')
    for name, settings in data['presets'].items():
        if not name.strip() or len(name)>40 or name == RECOMMENDED_NAME:
            raise ValueError('收藏名称不正确')
        data['presets'][name]=validate_settings(settings)
    return data['presets']


def write_presets(path, presets):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, {'schema':1, 'presets':presets})


PACKAGE_FORMAT='dianzhong.micro-presets'
MAX_PACKAGE_BYTES=2*1024*1024
REFERENCE_LABELS={'watermark_path':'水印','music_path':'音乐','background_path':'背景',
    'pip_path':'叠片','intro_path':'片头','outro_path':'片尾','subtitle_path':'字幕','cover_path':'封面'}


def _validate_exchange_paths(values):
    paths=[values[key] for key in REFERENCE_LABELS]+list(values['resource_pools'].values())
    for path in paths:
        if (path.startswith(('\\\\','//')) or any(ord(c)<32 for c in path)
                or (re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',path) and not re.match(r'^[A-Za-z]:[\\/]',path))):
            raise ValueError('共享方案仅支持本地资源路径，不支持网络地址或共享目录')


def preset_references(values):
    """Called after package validation; no automatic downloads or file execution."""
    refs=[]
    for key,label in REFERENCE_LABELS.items():
        path=values[key]
        if path:refs.append({'label':label,'path':path,'exists':Path(path).is_file()})
    for key,path in values['resource_pools'].items():
        if path:refs.append({'label':REFERENCE_LABELS[key]+'资源池','path':path,'exists':Path(path).is_dir()})
    return refs


def _validated_name(name):
    if not isinstance(name,str) or name!=name.strip() or not 1<=len(name)<=40 or name==RECOMMENDED_NAME or any(ord(c)<32 for c in name):
        raise ValueError('方案名称须为 1–40 字，不能使用推荐方案名称')
    return name


def _unique_json_keys(pairs):
    data={}
    for key,value in pairs:
        if key in data:raise ValueError('方案文件有重复字段：'+key)
        data[key]=value
    return data


def read_preset_package(path):
    with Path(path).open('rb') as stream:payload=stream.read(MAX_PACKAGE_BYTES+1)
    if len(payload)>MAX_PACKAGE_BYTES:raise ValueError('方案文件超过 2 MB')
    data=json.loads(payload.decode('utf-8-sig'),object_pairs_hook=_unique_json_keys)
    if (not isinstance(data,dict) or set(data)!={'format','schema','presets'}
            or data['format']!=PACKAGE_FORMAT or data['schema']!=1):
        raise ValueError('请选择本软件导出的方案 JSON 文件')
    presets=data['presets']
    if not isinstance(presets,dict) or not 1<=len(presets)<=100:raise ValueError('方案文件须包含 1–100 个方案')
    result={}
    for name,values in presets.items():
        values=validate_settings(values);_validate_exchange_paths(values)
        result[_validated_name(name)]=deepcopy(values)
    return result


def export_preset_package(path,name,values):
    """Explicit options whitelist excludes credentials, batches and uploader identity."""
    values=validate_settings(values);_validate_exchange_paths(values)
    data={'format':PACKAGE_FORMAT,'schema':1,'presets':{_validated_name(name):values}}
    if len(json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))>MAX_PACKAGE_BYTES:
        raise ValueError('方案参数超过 2 MB，未导出')
    save_json(Path(path),data)


def merge_imported_presets(local,incoming,*,replace_existing=False):
    """Build a copy first; caller persists it before changing the visible state."""
    merged=deepcopy(local);names=[]
    for name,settings in incoming.items():
        _validated_name(name);values=deepcopy(validate_settings(settings));target=name
        if not replace_existing and target in merged:
            index=1
            while True:
                suffix='（导入'+(str(index) if index>1 else '')+'）'
                target=name[:40-len(suffix)]+suffix
                if target not in merged and target not in incoming:break
                index+=1
        merged[target]=values;names.append(target)
    return merged,names
