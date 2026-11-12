"""Serializable text overlay contract, independent of the desktop widgets."""
import math

DEFAULT_TRACK={'text':'','font_name':'default','font_size':28,'font_color':'FFFFFF',
    'position':'top','x':.5,'y':.5,'opacity':1,'outline':2,'shadow':0,'box':False,
    'start':0,'duration':0,'scroll':'none','scroll_speed':60,'loop':True}
POSITIONS={'top','bottom','top_left','top_right','bottom_left','bottom_right','center','custom'}
SCROLLS={'none','left','right','up','down'}


def normalize_track(value):
    import re
    if not isinstance(value,dict) or set(value)-set(DEFAULT_TRACK):
        raise ValueError('文字轨格式无效')
    track={**DEFAULT_TRACK,**value}
    text=track['text']
    if not isinstance(text,str) or not text.strip() or len(text)>160 or len(text.splitlines())>3:
        raise ValueError('每条文字需有内容，最多 160 字、3 行')
    if track['font_name'] not in {'default','sans','serif'} or track['position'] not in POSITIONS or track['scroll'] not in SCROLLS:
        raise ValueError('文字字体、位置或滚动方式无效')
    if not isinstance(track['font_color'],str) or not re.fullmatch('[0-9A-Fa-f]{6}',track['font_color']):
        raise ValueError('文字颜色须为六位十六进制颜色')
    for key,low,high in [('font_size',12,96),('x',0,1),('y',0,1),('opacity',.1,1),
        ('outline',0,8),('shadow',0,8),('start',0,86400),('duration',0,86400),('scroll_speed',10,300)]:
        number=track[key]
        if not isinstance(number,(int,float)) or not math.isfinite(number) or not low<=number<=high:
            raise ValueError('文字参数超出范围：'+key)
    if not isinstance(track['font_size'],int) or not all(isinstance(track[k],bool) for k in ('loop','box')):
        raise ValueError('字号或文字开关格式无效')
    return track


def timing_expression(start,duration,offset):
    time=f'(t+{offset})'
    result=f'gte({time},{start})'
    if duration:result+=f'*lt({time},{start+duration})'
    return result


def motion_coordinates(direction,speed,start,offset,loop,width,height,canvas_w,canvas_h):
    distance=f'((t+{offset}-{start})*{speed})'
    span=f'{canvas_w}+{width}' if direction in {'left','right'} else f'{canvas_h}+{height}'
    travel=f'mod({distance},{span})' if loop else distance
    if direction=='left':return f'{canvas_w}-{travel}',None
    if direction=='right':return f'-{width}+{travel}',None
    if direction=='up':return None,f'{canvas_h}-{travel}'
    if direction=='down':return None,f'-{height}+{travel}'
    return None,None
