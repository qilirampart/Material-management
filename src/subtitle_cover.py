"""Local subtitle timing and cover assets shared by preview and production."""
import math
import re
from pathlib import Path
from src.media import run


SUBTITLE_DEFAULTS = dict(subtitle_path='', subtitle_encoding='utf-8', subtitle_timing='source',
    subtitle_shift=0, subtitle_keep_ass_style=True, subtitle_size=32, subtitle_color='FFFFFF',
    subtitle_outline=2, subtitle_margin=36, subtitle_position='bottom', cover_mode='none',
    cover_path='', cover_time=0, cover_duration=.2, cover_fit='contain')


def validate_assets(options, check_files=True):
    if options.subtitle_encoding not in {'utf-8','gb18030','utf-16'} or options.subtitle_timing not in {'source','body'}:
        raise ValueError('字幕编码或时间轴无效')
    if options.subtitle_position not in {'top','bottom'} or not re.fullmatch(r'[0-9A-Fa-f]{6}',options.subtitle_color):
        raise ValueError('字幕颜色或位置无效')
    if not isinstance(options.subtitle_keep_ass_style,bool):raise ValueError('字幕样式设置无效')
    for value,low,high in ((options.subtitle_size,16,64),(options.subtitle_outline,0,8),
            (options.subtitle_margin,0,200),(options.subtitle_shift,-300,300),(options.cover_time,0,86400),
            (options.cover_duration,.1,3)):
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('字幕或封面参数超出范围')
    if options.cover_mode not in {'none','image','frame'} or options.cover_fit not in {'contain','fill'}:
        raise ValueError('封面模式无效')
    if not isinstance(options.subtitle_path,str) or not isinstance(options.cover_path,str):raise ValueError('字幕或封面路径无效')
    if check_files and options.subtitle_path:
        path=Path(options.subtitle_path)
        if not path.is_file() or path.suffix.lower() not in {'.srt','.ass'}:raise ValueError('请选择本地 SRT／ASS 字幕文件')
    if check_files and options.cover_mode=='image':
        path=Path(options.cover_path)
        if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('请选择本地封面图片')


def ass_seconds(value):
    h,m,s=value.split(':');return int(h)*3600+int(m)*60+float(s)


def ass_time(seconds):
    ticks=max(0,round(seconds*100));h,ticks=divmod(ticks,360000);m,ticks=divmod(ticks,6000)
    return f'{h}:{m:02d}:{ticks//100:02d}.{ticks%100:02d}'


def unified_style(options):
    color=options.subtitle_color
    bgr=color[4:6]+color[2:4]+color[:2]
    return ('Style: Default,Microsoft YaHei,'+str(options.subtitle_size)+f',&H00{bgr},&H00FFFFFF,'
        '&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,'+str(options.subtitle_outline)+',0,'+
        str(2 if options.subtitle_position=='bottom' else 8)+f',24,24,{options.subtitle_margin},1')


def prepare_subtitles(options, work, clip_start, timeline_offset, duration, should_stop=None):
    """Retime events instead of video PTS, so audio and other effect clocks stay intact."""
    source=Path(options.subtitle_path);normalized=Path(work)/'subtitles.ass'
    run(['ffmpeg','-y','-v','error','-protocol_whitelist','file','-f',source.suffix[1:].lower(),
        '-sub_charenc',options.subtitle_encoding,'-i',str(source),'-map','0:s:0','-c:s','ass',str(normalized)],
        timeout=60,should_stop=should_stop)
    keep=source.suffix.lower()=='.ass' and options.subtitle_keep_ass_style
    lines=[];style_added=False
    for line in normalized.read_text(encoding='utf-8-sig').splitlines():
        if not keep and line.startswith('PlayResX:'):line=f'PlayResX: {options.output_width}'
        if not keep and line.startswith('PlayResY:'):line=f'PlayResY: {options.output_height}'
        if not keep and line.startswith('Style:'):
            if style_added:continue
            line=unified_style(options);style_added=True
        if line.startswith('Dialogue:'):
            parts=line.split(',',9)
            scale=options.speed if options.subtitle_timing=='source' else 1
            origin=clip_start if options.subtitle_timing=='source' else timeline_offset
            start=(ass_seconds(parts[1])-origin)/scale+options.subtitle_shift
            end=(ass_seconds(parts[2])-origin)/scale+options.subtitle_shift
            if end<=0 or start>=duration:continue
            parts[1]=ass_time(max(0,start));parts[2]=ass_time(min(duration,end))
            if not keep:
                parts[3]='Default';parts[5:8]=['0','0','0']
                parts[9]=re.sub(r'\{[^}]*\}','',parts[9])
            line=','.join(parts)
        lines.append(line)
    normalized.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return normalized,keep


def subtitle_filter(path,filter_path):
    # Write canonical ASS styles above: libass force_style interprets Alignment
    # using SSA legacy numbering, which would put ASS top-center 8 at middle-left.
    return f"subtitles=filename='{filter_path(path)}'"


def prepare_cover(source, options, metadata, target, should_stop=None):
    image=options.cover_mode=='image'
    if not image and options.cover_time>=metadata['duration']:raise ValueError('封面取帧位置超出原视频时长')
    width,height=options.output_width,options.output_height
    if options.cover_fit=='contain':
        vf=f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black'
    else:vf=f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}'
    run(['ffmpeg','-y','-v','error']+([] if image else ['-ss',str(options.cover_time)])+
        ['-i',str(options.cover_path if image else source),'-vf',vf+',setsar=1','-frames:v','1',str(target)],
        timeout=60,should_stop=should_stop)
    return Path(target)
