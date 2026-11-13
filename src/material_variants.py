"""Local, non-destructive material processing; optional future clip-selection boundary."""
from __future__ import annotations

import hashlib
import math
import os
import re
import random
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.batch import save_json
from src.media import (
    FFmpegCancelled, FFmpegError, MAXIMUM_UPLOAD_FILE_SIZE_BYTES,
    probe, run, transcode_for_upload_bitrate, validate_video,
)
from src.upload import safe_filename_part
from src.text_tracks import normalize_track,timing_expression,motion_coordinates,SCROLLS
from src.bookends import TRANSITIONS,plan_bookends,compose_bookends
from src.subtitle_cover import validate_assets,prepare_subtitles,subtitle_filter,prepare_cover
from src.picture_effects import validate_picture_effects,picture_effect_chain,grid_chain
from src.region_effects import normalize_region,validate_crop,crop_filter,region_chain


class ClipSelectionProvider(Protocol):
    """Future model adapter: return ordered source-time ranges, never edit files.

    The caller must validate ranges and obtain human approval before rendering.
    No network request or model client is configured by this module.
    """
    def select_clips(self, video_path: str, metadata: dict, instruction: str) -> list[dict]: ...


def validate_clip_ranges(ranges, duration):
    if not ranges:
        raise ValueError('至少需要一个时间段')
    previous_end = 0.0
    for segment in ranges:
        start, end = float(segment['start']), float(segment['end'])
        if not (math.isfinite(start) and math.isfinite(end) and previous_end <= start < end <= duration):
            raise ValueError('时间段必须有序、不重叠，并在原视频时长内')
        previous_end = end
    return ranges


@dataclass(frozen=True)
class VariantOptions:
    mode: str = 'micro'
    variants: int = 1
    uploader: str = ''
    background: str = 'blur'
    trim_start: float = 0.15
    trim_end: float = 0.15
    speed: float = 1.02
    color_adjust: bool = True
    title: str = ''
    output_width: int = 720
    output_height: int = 1280
    foreground_scale: float = .9
    vertical_position: float = .5
    mirror: bool = False
    rotation: int = 0
    crop_percent: float = 0
    brightness: float = 0
    contrast: float = 1
    saturation: float = 1
    sharpen: float = 0
    denoise: float = 0
    output_fps: int = 0
    drop_every: int = 0
    title_position: str = 'top'
    title_size: int = 28
    title_color: str = 'FFFFFF'
    watermark_path: str = ''
    watermark_position: str = 'top_right'
    watermark_scale: float = .15
    watermark_opacity: float = .8
    audio_mode: str = 'original'
    music_path: str = ''
    original_volume: float = 1
    music_volume: float = .25
    mask_mode: str = 'none'
    mask_x: float = 0
    mask_y: float = 0
    mask_w: float = 20
    mask_h: float = 10
    zoom_mode: str = 'none'
    zoom_amount: float = .08
    zoom_period: float = 6
    background_path: str = ''
    pip_path: str = ''
    pip_scale: float = .25
    pip_x: float = 1
    pip_y: float = 1
    pip_opacity: float = 1
    randomize: bool = False
    random_seed: int = 1
    random_ranges: dict = field(default_factory=dict)
    resource_pools: dict = field(default_factory=dict)
    text_tracks: list = field(default_factory=list)
    watermark_start: float = 0
    watermark_duration: float = 0
    watermark_scroll: str = 'none'
    watermark_scroll_speed: float = 60
    music_delay: float = 0
    music_duration: float = 0
    music_fade_in: float = 0
    music_fade_out: float = 0
    intro_path: str = ''
    outro_path: str = ''
    intro_duration: float = 3
    outro_duration: float = 3
    transition: str = 'cut'
    transition_duration: float = .3
    bookend_audio: bool = True
    regions: list = field(default_factory=list)
    crop_mode: str = 'uniform'
    crop_left: float = 0
    crop_right: float = 0
    crop_top: float = 0
    crop_bottom: float = 0

    subtitle_path: str = ''
    subtitle_encoding: str = 'utf-8'
    subtitle_timing: str = 'source'
    subtitle_shift: float = 0
    subtitle_keep_ass_style: bool = True
    subtitle_size: int = 32
    subtitle_color: str = 'FFFFFF'
    subtitle_outline: float = 2
    subtitle_margin: int = 36
    subtitle_position: str = 'bottom'
    cover_mode: str = 'none'
    cover_path: str = ''
    cover_time: float = 0
    cover_duration: float = .2
    cover_fit: str = 'contain'
    grid_layout: str = 'none'
    grid_fit: str = 'contain'
    picture_style: str = 'original'
    vignette: float = 0
    border_width: int = 0
    border_color: str = 'FFFFFF'

    def validate(self):
        if self.mode not in {'micro', 'md5'} or self.background not in {'blur', 'black'}:
            raise ValueError('不支持的处理方式或背景')
        if not 1 <= self.variants <= 10:
            raise ValueError('每条生成数量须为 1–10')
        if not all(math.isfinite(v) for v in (self.trim_start, self.trim_end, self.speed)):
            raise ValueError('时间和速度必须是有效数字')
        if self.trim_start < 0 or self.trim_end < 0 or not 0.8 <= self.speed <= 1.2:
            raise ValueError('裁剪秒数不能为负；速度须为 0.8–1.2 倍')
        if len(self.title) > 40 or '\n' in self.title or '\r' in self.title:
            raise ValueError('标题限一行、40 字以内')
        if self.mode == 'micro' and self.variants > 1 and not self.color_adjust and not self.randomize:
            raise ValueError('生成多个微创新版本需启用轻度调色，以区分版本')
        if any(not isinstance(v, int) or v % 2 or not 240 <= v <= 3840 for v in (self.output_width, self.output_height)):
            raise ValueError('输出宽高须为 240–3840 的偶数')
        ranges = [(self.foreground_scale, .5, 1), (self.vertical_position, 0, 1), (self.crop_percent, 0, 15),
                  (self.brightness, -.2, .2), (self.contrast, .5, 1.5), (self.saturation, 0, 2),
                  (self.sharpen, 0, 2), (self.denoise, 0, 10), (self.watermark_scale, .05, .5),
                  (self.watermark_opacity, .1, 1), (self.original_volume, 0, 2), (self.music_volume, 0, 2),
                  (self.mask_x, 0, 99), (self.mask_y, 0, 99), (self.mask_w, 1, 100), (self.mask_h, 1, 100)]
        if any(not math.isfinite(v) or not low <= v <= high for v, low, high in ranges):
            raise ValueError('画面或音频参数超出允许范围')
        if self.rotation not in {0, 90, 180, 270} or self.output_fps not in {0, 24, 25, 30, 50, 60}:
            raise ValueError('不支持的旋转角度或帧率')
        if not isinstance(self.drop_every, int) or (self.drop_every != 0 and not 2 <= self.drop_every <= 300):
            raise ValueError('抽帧间隔须为 2–300，0 表示关闭')
        positions = {'top', 'bottom', 'top_left', 'top_right', 'bottom_left', 'bottom_right'}
        if self.title_position not in positions or self.watermark_position not in positions:
            raise ValueError('文字或水印位置无效')
        if not isinstance(self.title_size, int) or not 16 <= self.title_size <= 64 or not re.fullmatch(r'[0-9A-Fa-f]{6}', self.title_color):
            raise ValueError('字号须为 16–64，文字颜色须为六位十六进制颜色')
        if self.audio_mode not in {'original', 'mute', 'mix', 'replace'}:
            raise ValueError('音频处理方式无效')
        if self.mask_mode not in {'none', 'blur', 'cover'} or (self.mask_mode != 'none'
                and (self.mask_x+self.mask_w > 100 or self.mask_y+self.mask_h > 100)):
            raise ValueError('区域范围不能越过画面边界')
        if self.mode == 'micro':
            validate_picture_effects(self)
            validate_assets(self)
            validate_crop(self)
            if not isinstance(self.regions,list) or len(self.regions)>6:raise ValueError('最多添加 6 个原片处理区域')
            for region in self.regions:normalize_region(region)
            if self.transition not in TRANSITIONS or not isinstance(self.bookend_audio,bool):
                raise ValueError('片头尾转场或声音设置无效')
            for value,low,high in ((self.intro_duration,.5,30),(self.outro_duration,.5,30),(self.transition_duration,.1,2)):
                if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                    raise ValueError('片头尾长度须为 0.5–30 秒，转场为 0.1–2 秒')
            if not isinstance(self.text_tracks,list) or len(self.text_tracks)>6:
                raise ValueError('最多添加 6 条文字轨')
            for track in self.text_tracks:normalize_track(track)
            for value in (self.watermark_start,self.watermark_duration,self.music_delay,self.music_duration,
                          self.music_fade_in,self.music_fade_out):
                if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=86400:
                    raise ValueError('文字、水印或音乐时段须为 0–86400 秒')
            if self.watermark_scroll not in SCROLLS or not math.isfinite(self.watermark_scroll_speed) or not 10<=self.watermark_scroll_speed<=300:
                raise ValueError('水印滚动参数无效')
            if self.zoom_mode not in {'none','in','out','pulse'}:
                raise ValueError('动态缩放模式无效')
            for value,low,high in ((self.zoom_amount,0,.25),(self.zoom_period,1,60),
                (self.pip_scale,.1,.8),(self.pip_x,0,1),(self.pip_y,0,1),(self.pip_opacity,.1,1)):
                if not math.isfinite(value) or not low<=value<=high:
                    raise ValueError('动态构图或画中画参数超出范围')
            if not isinstance(self.random_seed,int) or not 0<=self.random_seed<=2147483647:
                raise ValueError('随机种子须为 0–2147483647 的整数')
            if not isinstance(self.random_ranges,dict) or not isinstance(self.resource_pools,dict):
                raise ValueError('随机范围和资源池格式无效')
            for key,bounds in self.random_ranges.items():
                if key not in RANDOM_LIMITS or not isinstance(bounds,(list,tuple)) or len(bounds)!=2:
                    raise ValueError('不支持的随机参数')
                low,high=RANDOM_LIMITS[key]
                if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in bounds) or not low<=bounds[0]<=bounds[1]<=high:
                    raise ValueError('随机参数范围无效：'+key)
            for key,folder in self.resource_pools.items():
                if key not in RESOURCE_TYPES or not isinstance(folder,str):
                    raise ValueError('资源池类型无效')
                if self.randomize and not Path(folder).is_dir():
                    raise ValueError('资源池文件夹不存在：'+folder)
            if self.randomize:
                if not self.color_adjust and any(k in self.random_ranges for k in ('brightness','contrast','saturation')):
                    raise ValueError('随机调色范围需先启用调色')
                if 'zoom_amount' in self.random_ranges and self.zoom_mode=='none':
                    raise ValueError('随机动态幅度需先启用动态缩放')
                if self.resource_pools.get('music_path') and self.audio_mode not in {'mix','replace'}:
                    raise ValueError('音乐资源池需选择混音或仅背景音乐')
                if self.variants>1 and not any(a!=b for a,b in self.random_ranges.values()) and not self.resource_pools:
                    raise ValueError('随机多版本至少启用一项非零范围或资源池')
            for key in ('background_path','pip_path','intro_path','outro_path'):
                path=getattr(self,key)
                if path and not (self.randomize and self.resource_pools.get(key)) and (not Path(path).is_file() or Path(path).suffix.lower() not in VISUAL_TYPES):
                    raise ValueError('请选择存在的背景、叠片或片头尾图片／视频文件')
            if self.watermark_path and not (self.randomize and self.resource_pools.get('watermark_path')) and (not Path(self.watermark_path).is_file() or Path(self.watermark_path).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}):
                raise ValueError('请选择存在的 PNG/JPG/WebP 水印图片')
            if self.audio_mode in {'mix', 'replace'} and not (self.randomize and self.resource_pools.get('music_path')) and (not self.music_path or not Path(self.music_path).is_file()):
                raise ValueError('请先选择背景音乐文件')
        return self


IMAGE_TYPES={'.png','.jpg','.jpeg','.webp'}
VISUAL_TYPES=IMAGE_TYPES|{'.mp4','.mov','.mkv','.webm','.m4v'}
RESOURCE_TYPES={'background_path':VISUAL_TYPES,'pip_path':VISUAL_TYPES,
    'intro_path':VISUAL_TYPES,'outro_path':VISUAL_TYPES,
    'watermark_path':IMAGE_TYPES,'music_path':{'.mp3','.wav','.m4a','.aac','.flac','.ogg'}}
RANDOM_LIMITS={'foreground_scale':(.5,1),'speed':(.8,1.2),'brightness':(-.2,.2),
    'contrast':(.5,1.5),'saturation':(0,2),'zoom_amount':(0,.25),'vertical_position':(0,1)}


def resolve_variant_options(options, source_key, version):
    """Stable per-source/version plan; seed and sorted pools make preview repeatable."""
    options.validate()
    if not options.randomize:
        return options
    rng=random.Random(f'{options.random_seed}|{source_key}|{version}')
    changes={key:round(rng.uniform(*bounds),6) for key,bounds in sorted(options.random_ranges.items())}
    for key,folder in sorted(options.resource_pools.items()):
        paths=sorted((p.resolve() for p in Path(folder).iterdir() if p.is_file()
                      and p.suffix.lower() in RESOURCE_TYPES[key]),key=lambda p:str(p).casefold())
        if not paths:
            raise ValueError('资源池没有可用素材：'+folder)
        changes[key]=str(rng.choice(paths))
    return replace(options,**changes,randomize=False,variants=1,resource_pools={},random_ranges={}).validate()


def extra_input_indexes(options):
    keys=[]
    if options.watermark_path:keys.append('watermark_path')
    if options.audio_mode in {'mix','replace'}:keys.append('music_path')
    keys.extend(k for k in ('background_path','pip_path','intro_path','outro_path') if getattr(options,k))
    return {key:i+1 for i,key in enumerate(keys)}


def file_md5(path, should_stop=None):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        while True:
            if should_stop and should_stop():
                raise FFmpegCancelled('已停止素材再加工')
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _filter_path(path):
    return str(Path(path).resolve()).replace('\\', '/').replace(':', '\\:').replace("'", "'\\''")


def _font_file(name='default'):
    windows=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    preferred={'default':windows/'msyh.ttc','sans':windows/'simhei.ttf','serif':windows/'simsun.ttc'}
    candidates = [
        preferred[name],windows/'msyh.ttc',
        Path('/System/Library/Fonts/PingFang.ttc'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    ]
    font = next((p for p in candidates if p.is_file()), None)
    if font is None:
        raise ValueError('未找到标题字体，请先关闭标题选项')
    return font


def _title_filter(text_path, options):
    font=_font_file()
    x, y = _position(options.title_position, 'text_w', 'text_h')
    size = min(options.title_size, max(1, (options.output_width-64)//max(1, len(options.title))))
    return (f"drawtext=fontfile='{_filter_path(font)}':textfile='{_filter_path(text_path)}':"
            f"expansion=none:fontsize={size}:fontcolor=0x{options.title_color}:box=1:boxcolor=black@0.6:"
            f"boxborderw=12:x={x}:y={y}")


def _track_filter(value,text_path,canvas_width,offset):
    track=normalize_track(value)
    x,y=_position(track['position'],'text_w','text_h')
    if track['position']=='center':x,y='(w-text_w)/2','(h-text_h)/2'
    if track['position']=='custom':x,y=f"(w-text_w)*{track['x']}",f"(h-text_h)*{track['y']}"
    moving=motion_coordinates(track['scroll'],track['scroll_speed'],track['start'],offset,
        track['loop'],'text_w','text_h','w','h')
    x,y=moving[0] or x,moving[1] or y
    longest=max(map(len,track['text'].splitlines()))
    size=(track['font_size'] if track['scroll']!='none'
          else min(track['font_size'],max(1,(canvas_width-64)//longest)))
    return (f"drawtext=fontfile='{_filter_path(_font_file(track['font_name']))}':"
        f"textfile='{_filter_path(text_path)}':expansion=none:fontsize={size}:"
        f"fontcolor=0x{track['font_color']}@{track['opacity']}:borderw={track['outline']}:bordercolor=black:"
        f"shadowx={track['shadow']}:shadowy={track['shadow']}:shadowcolor=black:"
        f"box={int(track['box'])}:boxcolor=black@0.5:boxborderw=8:x='{x}':y='{y}':"
        f"enable='{timing_expression(track['start'],track['duration'],offset)}'")


def _position(position, width, height, canvas_w='w', canvas_h='h'):
    x = '24' if position.endswith('left') else f'{canvas_w}-{width}-24' if position.endswith('right') else f'({canvas_w}-{width})/2'
    y = f'{canvas_h}-{height}-32' if position.startswith('bottom') else '32'
    return x, y


def build_video_filter(options, version=1, text_path=None, source_metadata=None, timeline_offset=0,track_paths=None):
    meta = source_metadata or {}
    width, height = options.output_width, options.output_height
    fw, fh = int(width*options.foreground_scale)//2*2, int(height*options.foreground_scale)//2*2
    filters = [f'setpts=(PTS-STARTPTS)/{options.speed}'+region_chain(options.regions,meta,timeline_offset)]
    if options.crop_mode=='edges':filters.append(crop_filter(options))
    if options.drop_every:
        filters.append(f"select='not(eq(mod(n+1,{options.drop_every}),0))'")
    if options.output_fps or options.drop_every:
        filters.append(f"fps={options.output_fps or meta.get('frame_rate') or 30}")
    if options.mirror:
        filters.append('hflip')
    if options.rotation:
        filters.append({90: 'transpose=1', 180: 'hflip,vflip', 270: 'transpose=2'}[options.rotation])
    if options.crop_mode=='uniform' and options.crop_percent:
        ratio = 1-options.crop_percent/50
        filters.append(f'crop=trunc(iw*{ratio}/2)*2:trunc(ih*{ratio}/2)*2')
    prepared = '[0:v]' + ','.join(filters)
    if options.mask_mode == 'cover':
        prepared += (f',drawbox=x=iw*{options.mask_x/100}:y=ih*{options.mask_y/100}:'
                     f'w=iw*{options.mask_w/100}:h=ih*{options.mask_h/100}:color=black:t=fill')
    if options.mask_mode == 'blur':
        # Bound the radius by the actual cropped region, including after rotation.
        prepared += (f',split[clear][region];[region]crop=max(2\,trunc(iw*{options.mask_w/100}/2)*2):'
            f'max(2\,trunc(ih*{options.mask_h/100}/2)*2):iw*{options.mask_x/100}:ih*{options.mask_y/100},'
            "boxblur=luma_radius='min(6,min(w,h)/2)':luma_power=1:chroma_radius=0:chroma_power=0[masked];"
            f'[clear][masked]overlay=main_w*{options.mask_x/100}:main_h*{options.mask_y/100}')
    time_filter = prepared+grid_chain(options)
    y = f'(H-h)*{options.vertical_position}'
    indexes=extra_input_indexes(options)
    if options.background_path:
        graph=(f'{time_filter},scale={fw}:{fh}:force_original_aspect_ratio=decrease:force_divisible_by=2[front];'
            f'[{indexes["background_path"]}:v]setpts=PTS-STARTPTS,scale={width}:{height}:'
            f'force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[back];'
            f'[back][front]overlay=(W-w)/2:{y}:shortest=1,setsar=1')
    elif options.background == 'blur':
        graph = (f'{time_filter},split=2[bg][fg];'
                 f'[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},'
                 'boxblur=20:2[back];'
                 f'[fg]scale={fw}:{fh}:force_original_aspect_ratio=decrease:force_divisible_by=2[front];'
                 f'[back][front]overlay=(W-w)/2:{y}:shortest=1,setsar=1')
    else:
        graph = (f'{time_filter},scale={fw}:{fh}:force_original_aspect_ratio=decrease:'
                 f'force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)*{options.vertical_position}:black,setsar=1')
    if options.color_adjust:
        graph += f',eq=brightness={options.brightness+0.002*version:.3f}:contrast={options.contrast+0.003*version:.3f}:saturation={options.saturation+0.015:.3f}'
    if options.sharpen:
        graph += f',unsharp=5:5:{options.sharpen}:5:5:0'
    if options.denoise:
        graph += f',hqdn3d={options.denoise}'
    if options.zoom_mode!='none' and options.zoom_amount:
        fps=options.output_fps or meta.get('frame_rate') or 30
        time=f'(on/{fps}+{timeline_offset})'
        phase={'in':f'min(1,{time}/{options.zoom_period})',
               'out':f'1-min(1,{time}/{options.zoom_period})',
               'pulse':f'(1-cos(2*PI*{time}/{options.zoom_period}))/2'}[options.zoom_mode]
        graph+=(f",fps={fps},zoompan=z='1+{options.zoom_amount}*({phase})':"
                f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:fps={fps}:s={width}x{height}")
    graph+=picture_effect_chain(options)
    if options.pip_path:
        graph+=(f'[basepip];[{indexes["pip_path"]}:v]setpts=PTS-STARTPTS,'
            f'scale={int(width*options.pip_scale)//2*2}:{int(height*options.pip_scale)//2*2}:'
            f'force_original_aspect_ratio=decrease:force_divisible_by=2,format=rgba,'
            f'colorchannelmixer=aa={options.pip_opacity}[pip];'
            f'[basepip][pip]overlay=(W-w)*{options.pip_x}:(H-h)*{options.pip_y}:shortest=1')
    if options.title and text_path:
        graph += ',' + _title_filter(text_path, options)
    for track,path in zip(options.text_tracks,track_paths or []):
        graph+=','+_track_filter(track,path,width,timeline_offset)
    if options.watermark_path:
        x, y = _position(options.watermark_position, 'overlay_w', 'overlay_h', 'main_w', 'main_h')
        moving=motion_coordinates(options.watermark_scroll,options.watermark_scroll_speed,
            options.watermark_start,timeline_offset,True,'overlay_w','overlay_h','main_w','main_h')
        x,y=moving[0] or x,moving[1] or y
        graph += (f'[basev];[1:v]scale={int(width*options.watermark_scale)}:-1,format=rgba,'
                  f"colorchannelmixer=aa={options.watermark_opacity}[wm];[basev][wm]overlay=x='{x}':y='{y}':shortest=1:"
                  f"enable='{timing_expression(options.watermark_start,options.watermark_duration,timeline_offset)}'")
    return graph + ',format=yuv420p[outv]'


def build_audio_graph(options, metadata, duration,*,timeline_offset=0,total_duration=None):
    original = f'asetpts=PTS-STARTPTS,atempo={options.speed},volume={options.original_volume}'
    if options.audio_mode not in {'mix', 'replace'}:
        return '', original, None
    music_index = extra_input_indexes(options)['music_path']
    end=min(total_duration if total_duration is not None else duration,
        options.music_delay+options.music_duration if options.music_duration else float('inf'))
    time=f'(t+{timeline_offset})'
    gain=f'{options.music_volume}*gte({time},{options.music_delay})*lt({time},{end})'
    if options.music_fade_in:gain+=f'*clip(({time}-{options.music_delay})/{options.music_fade_in},0,1)'
    if options.music_fade_out:gain+=f'*clip(({end}-{time})/{options.music_fade_out},0,1)'
    delay=max(0,options.music_delay-timeline_offset)
    graph = (f';[{music_index}:a:0]atrim=duration={duration},asetpts=PTS-STARTPTS,'
             f"adelay={round(delay*1000)}:all=1,apad=whole_dur={duration},atrim=duration={duration},"
             f"volume='{gain}':eval=frame[music]")
    if options.audio_mode == 'mix' and metadata.get('audio'):
        graph += f';[0:a:0]{original},atrim=duration={duration}[voice];[voice][music]amix=inputs=2:duration=longest:normalize=0[outa]'
    else:
        graph += ';[music]anull[outa]'
    return graph, None, '[outa]'


def _render_micro(source, target, options, metadata, clip_start, clip_duration,
                  *, version=1, progress=None, should_stop=None, timeline_offset=0,text_context=None,cover_offset=0):
    with tempfile.TemporaryDirectory(prefix='dz-variant-') as work:
        text_path = Path(work) / 'title.txt'
        text_path.write_text(options.title, encoding='utf-8')
        context={'文件名':Path(source).stem,'剧名':(text_context or {}).get('drama','未命名剧集')}
        tracks=[];track_paths=[]
        for i,value in enumerate(options.text_tracks):
            track=normalize_track(value)
            for key,replacement in context.items():track['text']=track['text'].replace('{'+key+'}',replacement)
            track=normalize_track(track)
            path=Path(work)/f'track-{i}.txt';path.write_text(track['text'],encoding='utf-8')
            tracks.append(track);track_paths.append(path)
        render_options=replace(options,text_tracks=tracks)
        duration = clip_duration / options.speed
        audio_graph, audio_filter, audio_label = build_audio_graph(options, metadata, duration,
            timeline_offset=timeline_offset,total_duration=(metadata['duration']-options.trim_start-options.trim_end)/options.speed)
        video_graph=build_video_filter(render_options, version, text_path, metadata,timeline_offset,track_paths)
        if options.subtitle_path:
            subtitles,_=prepare_subtitles(options,work,clip_start,timeline_offset,duration,should_stop)
            video_graph=video_graph.removesuffix('[outv]')+','+subtitle_filter(subtitles,_filter_path)+'[outv]'
        bookend_inputs=[];plan=None
        if options.intro_path or options.outro_path:
            video_graph,audio_label,plan=compose_bookends(video_graph,audio_graph,audio_filter,audio_label,
                options,metadata,duration,extra_input_indexes(options))
            audio_filter=None
            bookend_inputs=[(s['path'],s['duration']) for s in plan['segments'] if s['kind']!='body']
        else:video_graph+=audio_graph
        cover=None
        if options.cover_mode!='none':
            cover=prepare_cover(source,options,metadata,Path(work)/'cover.png',should_stop)
            index=len(extra_input_indexes(options))+1
            video_graph=video_graph.replace('[outv]','[before_cover]')
            video_graph+=f";[{index}:v]format=yuv420p[cover_frame];[before_cover][cover_frame]overlay=0:0:enable='lt(t+{cover_offset},{options.cover_duration})'[outv]"
        result=transcode_for_upload_bitrate(
            source, target, video_filter=video_graph,
            audio_filter=audio_filter, clip_start=clip_start, clip_duration=clip_duration,
            output_duration=plan['duration'] if plan else duration, should_stop=should_stop, progress=progress,
            image_overlay_path=options.watermark_path or None,
            background_audio_path=options.music_path if options.audio_mode in {'mix', 'replace'} else None,
            audio_output_label=audio_label, mute_audio=options.audio_mode == 'mute',
            visual_inputs=[getattr(options,k) for k in ('background_path','pip_path') if getattr(options,k)],
            auxiliary_start=timeline_offset,background_audio_start=max(0,timeline_offset-options.music_delay),
            bookend_inputs=bookend_inputs,cover_overlay_path=cover)
        if cover:
            sidecar=Path(target).with_suffix('.cover.png')
            shutil.copyfile(cover,sidecar)
            result['cover']={'path':str(sidecar.resolve()),'mode':options.cover_mode,'duration':options.cover_duration}
        if plan:result['bookends']=plan
        return result


def render_micro_preview(source, target, options, *, start=0, seconds=10, progress=None, should_stop=None,text_context=None,
                         preview_section='body'):
    """Render a bounded excerpt with the production filters, without registering a product."""
    options.validate()
    requested=asdict(options)
    options=resolve_variant_options(options,str(Path(source).resolve()),1)
    if options.mode != 'micro' or not math.isfinite(start) or start < 0 or not 1 <= seconds <= 30:
        raise ValueError('预览起点须非负，时长须为 1–30 秒')
    if Path(source).resolve() == Path(target).resolve():
        raise ValueError('预览不能覆盖原片')
    metadata = probe(source)
    full_body=(metadata['duration']-options.trim_start-options.trim_end)/options.speed
    if preview_section not in {'body','head','tail'}:raise ValueError('预览类型无效')
    if preview_section=='head':
        if not options.intro_path:raise ValueError('请先选择片头素材')
        clip_start=options.trim_start
        render_options=replace(options,outro_path='')
    elif preview_section=='tail':
        if not options.outro_path:raise ValueError('请先选择片尾素材')
        clip_start=max(options.trim_start,metadata['duration']-options.trim_end-seconds*options.speed)
        render_options=replace(options,intro_path='')
    else:
        clip_start = max(options.trim_start, start)
        render_options=replace(options,intro_path='',outro_path='')
    clip_duration = min(seconds * options.speed, metadata['duration'] - options.trim_end - clip_start)
    if clip_duration < .5:
        raise ValueError('预览起点已接近或超出裁剪后的片尾，请减小起点')
    if preview_section!='body' and options.transition!='cut' and clip_duration/options.speed<2*options.transition_duration:
        raise ValueError(f'转场预览的主体时长至少需 {2*options.transition_duration:g} 秒')
    if (options.intro_path or options.outro_path) and full_body>0:
        plan_bookends(options,full_body)  # Validate the actual full composition before previewing a seam.
    cover_offset=(clip_start-options.trim_start)/options.speed
    if preview_section=='head':cover_offset=0
    elif options.intro_path:
        full_plan=plan_bookends(options,full_body)
        cover_offset+=full_plan['segments'][0]['duration']-full_plan['overlap']
    result = _render_micro(source, target, render_options, metadata, clip_start, clip_duration,
                           progress=progress, should_stop=should_stop,
                           timeline_offset=(clip_start-options.trim_start)/options.speed,text_context=text_context,cover_offset=cover_offset)
    return {'path': str(Path(target).resolve()), 'metadata': result, 'clip_start': clip_start,
            'resolved_options':asdict(options),'requested_options':requested,
            'source_path':str(Path(source).resolve()),'preview_section':preview_section}


def generate_variants(items, output_root, options, *, progress=None, should_stop=None, resolved_plans=None):
    options.validate()
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    root = Path(output_root) / run_id
    root.mkdir(parents=True, exist_ok=False)
    result = {'outputs': [], 'failed': [], 'stopped': False, 'manifest': str(root / 'manifest.json')}
    total = len(items) * options.variants
    index = 0

    def persist():
        save_json(Path(result['manifest']), {'options': asdict(options), **result})

    persist()
    for item in items:
        source_metadata = None
        source_md5 = None
        for version in range(1, options.variants + 1):
            if should_stop and should_stop():
                result['stopped'] = True
                persist()
                return result
            index += 1
            target = None
            if progress:
                progress({'phase': 'started', 'index': index, 'total': total, 'video_id': item['video_id']})
            try:
                source = Path(item['path']).resolve()
                frozen=(resolved_plans or {}).get((str(source),version))
                resolved=(replace(frozen,uploader=options.uploader).validate() if frozen is not None
                    else resolve_variant_options(options,str(source),version)) if options.mode=='micro' else options
                if source_metadata is None:
                    source_metadata = probe(source)
                    source_md5 = file_md5(source, should_stop)
                mode_name = '改md5' if options.mode == 'md5' else '微创新'
                drama = safe_filename_part(item.get('drama') or '未命名剧集') or '未命名剧集'
                uploader = safe_filename_part(options.uploader) or '未填'
                target_dir = root / drama / mode_name
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f'APP-繁花-王俨-{mode_name}-{drama}-{uploader}-{datetime.now():%y%m%d}-{index:03d}.mp4'
                if options.mode == 'md5':
                    run(['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-map', '0:v:0',
                         '-map', '0:a?', '-c', 'copy', '-metadata', f'comment=variant-{uuid.uuid4().hex}',
                         '-movflags', '+faststart', str(target)],
                        timeout=max(600, int(source_metadata['duration'] * 2)), should_stop=should_stop)
                    metadata = validate_video(target, should_stop=should_stop)
                    if metadata['file_size_bytes'] > MAXIMUM_UPLOAD_FILE_SIZE_BYTES:
                        raise ValueError('文件超过平台 510 MB 上限；仅改 MD5 不会缩小文件，请先剪辑或压缩')
                else:
                    clip_duration = source_metadata['duration'] - resolved.trim_start - resolved.trim_end
                    if clip_duration < 0.5:
                        raise ValueError('去头尾后不足 0.5 秒，请减少裁剪时长')
                    metadata = _render_micro(source, target, resolved, source_metadata,
                        resolved.trim_start, clip_duration, version=1 if options.randomize else version, should_stop=should_stop,
                        text_context=item,
                        progress=(lambda phase: progress({'phase': phase, 'index': index, 'total': total,
                                                         'video_id': item['video_id']})) if progress else None)
                output_md5 = file_md5(target, should_stop)
                if output_md5 == source_md5:
                    raise ValueError('输出与原文件 MD5 相同，请检查处理参数')
                result['outputs'].append({
                    'path': str(target.resolve()), 'metadata': metadata, 'drama': drama,
                    'source_path': str(source), 'source_video_id': item['video_id'],
                    'source_md5': source_md5, 'output_md5': output_md5,
                    'mode': options.mode, 'version': version, 'options': asdict(resolved),
                    'requested_options':asdict(options),
                    'upload_drama_info': item.get('upload_drama_info', {}),
                })
                if progress:
                    progress({'phase': 'completed', 'index': index, 'total': total, 'video_id': item['video_id']})
            except FFmpegCancelled:
                if target:
                    target.unlink(missing_ok=True)
                    target.with_suffix('.cover.png').unlink(missing_ok=True)
                result['stopped'] = True
                persist()
                return result
            except (OSError, ValueError, FFmpegError, subprocess.SubprocessError) as exc:
                if target:
                    target.unlink(missing_ok=True)
                    target.with_suffix('.cover.png').unlink(missing_ok=True)
                message = str(exc) if isinstance(exc, ValueError) else ('本地视频处理失败：' + str(exc)[-600:])
                result['failed'].append({'video_id': item['video_id'], 'version': version, 'error': message})
                if progress:
                    progress({'phase': 'failed', 'index': index, 'total': total,
                              'video_id': item['video_id'], 'error': message})
            persist()
    return result
