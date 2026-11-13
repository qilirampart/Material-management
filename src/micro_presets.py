"""Local named micro-innovation settings, separate from batches and credentials."""
import json
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
    'crop_mode','crop_left','crop_right','crop_top','crop_bottom'}-set(SUBTITLE_DEFAULTS)-set(PICTURE_DEFAULTS)
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
