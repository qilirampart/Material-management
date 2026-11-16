"""Normalize and join optional bookends without changing the body-effect timeline."""
import math
from pathlib import Path
from src.media import probe

IMAGE_SUFFIXES={'.png','.jpg','.jpeg','.webp'}
TRANSITIONS={'cut','fade','dissolve','wipeleft','wiperight','slideup'}


def plan_bookends(options,body_duration, *, should_stop=None):
    if not math.isfinite(body_duration) or body_duration<=0:
        raise ValueError('主体视频时长无效')
    segments=[]
    for kind in ('intro','body','outro'):
        if kind=='body':
            segments.append({'kind':'body','duration':body_duration});continue
        path=getattr(options,kind+'_path')
        if not path:continue
        image=Path(path).suffix.lower() in IMAGE_SUFFIXES
        meta={} if image else probe(path, **({'should_stop':should_stop} if should_stop else {}))
        duration=min(getattr(options,kind+'_duration'),float(meta.get('duration') or 0)) if not image else getattr(options,kind+'_duration')
        if duration<.5:raise ValueError('片头／片尾素材不足 0.5 秒')
        segments.append({'kind':kind,'path':path,'duration':duration,'image':image,'audio':bool(meta.get('audio'))})
    overlap=options.transition_duration if options.transition!='cut' and len(segments)>1 else 0
    if overlap and overlap>min(s['duration'] for s in segments)/2:
        raise ValueError('转场时长不能超过最短片段的一半，请缩短转场或延长片头尾')
    return {'segments':segments,'overlap':overlap,
        'duration':sum(s['duration'] for s in segments)-overlap*(len(segments)-1)}


def compose_bookends(video_graph,audio_graph,audio_filter,audio_label,options,metadata,body_duration,indexes, *, should_stop=None):
    plan=plan_bookends(options,body_duration,should_stop=should_stop)
    fps=options.output_fps or metadata.get('frame_rate') or 30
    width,height=options.output_width,options.output_height
    graph=video_graph.removesuffix('[outv]')+'[join_body_raw]'
    muted=options.audio_mode=='mute'
    if not muted and audio_label:
        graph+=audio_graph.replace('[outa]','[join_body_audio_raw]')
    for i,segment in enumerate(plan['segments']):
        duration=segment['duration'];kind=segment['kind']
        if kind=='body':
            video='[join_body_raw]'
            audio=('[join_body_audio_raw]' if audio_label else
                '[0:a:0]'+audio_filter if metadata.get('audio') else None)
        else:
            index=indexes[kind+'_path']
            video=f'[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease:'
            video+=f'force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,'
            audio=f'[{index}:a:0]anull' if segment['audio'] and options.bookend_audio else None
        graph+=(f';{video}fps={fps},setsar=1,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS,'
            f'tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration}[join_v{i}]')
        if not muted:
            if audio is None:audio='anullsrc=r=48000:cl=stereo'
            elif kind=='body' and audio_label:audio+= 'anull'
            graph+=(f';{audio},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                f'apad=whole_dur={duration},atrim=duration={duration},asetpts=PTS-STARTPTS[join_a{i}]')
    count=len(plan['segments']);overlap=plan['overlap']
    if not overlap:
        chain=''.join(f'[join_v{i}]'+('' if muted else f'[join_a{i}]') for i in range(count))
        graph+=f';{chain}concat=n={count}:v=1:a={0 if muted else 1}[join_video]'+('' if muted else '[outa]')
    else:
        video_label='join_v0';audio_label='join_a0';elapsed=plan['segments'][0]['duration']
        for i in range(1,count):
            target='join_video' if i==count-1 else f'join_xv{i}'
            graph+=(f';[{video_label}][join_v{i}]xfade=transition={options.transition}:'
                f'duration={overlap}:offset={elapsed-overlap}[{target}]')
            video_label=target
            if not muted:
                target_audio='outa' if i==count-1 else f'join_xa{i}'
                graph+=f';[{audio_label}][join_a{i}]acrossfade=d={overlap}:c1=tri:c2=tri[{target_audio}]'
                audio_label=target_audio
            elapsed+=plan['segments'][i]['duration']-overlap
    graph+=';[join_video]format=yuv420p[outv]'
    return graph,None if muted else '[outa]',plan
