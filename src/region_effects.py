"""Percent-based source-frame regions and independent cropping."""
import math
from src.text_tracks import timing_expression

DEFAULT_REGION={'mode':'blur','x':10,'y':10,'w':20,'h':10,'start':0,'duration':0,'strength':6,'enabled':True}


def normalize_region(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_REGION):raise ValueError('处理区域格式无效')
    region={**DEFAULT_REGION,**value}
    if region['mode'] not in {'blur','cover','repair'} or not isinstance(region['enabled'],bool):
        raise ValueError('区域处理方式无效')
    for key,low,high in [('x',0,99),('y',0,99),('w',1,100),('h',1,100),
        ('start',0,86400),('duration',0,86400),('strength',2,30)]:
        v=region[key]
        if not isinstance(v,(float,int)) or not math.isfinite(v) or not low<=v<=high:
            raise ValueError('区域参数超出范围：'+key)
    if region['x']+region['w']>100+1e-7 or region['y']+region['h']>100+1e-7:
        raise ValueError('区域不能超出原片边界')
    if region['mode']=='repair' and (region['x']<=0 or region['y']<=0 or
        region['x']+region['w']>=100 or region['y']+region['h']>=100):
        raise ValueError('修补区域需留出边缘；贴边区域请使用模糊或遮挡')
    return region


def validate_crop(options):
    if options.crop_mode not in {'uniform','edges'}:raise ValueError('裁剪方式无效')
    for value in (options.crop_left,options.crop_right,options.crop_top,options.crop_bottom):
        if not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=90:
            raise ValueError('独立裁边须为 0–90%')
    if options.crop_mode=='edges' and (options.crop_left+options.crop_right>95 or options.crop_top+options.crop_bottom>95):
        raise ValueError('裁剪后至少保留原片宽高的 5%')


def crop_filter(options):
    width=1-(options.crop_left+options.crop_right)/100
    height=1-(options.crop_top+options.crop_bottom)/100
    return (f'crop=max(2\\,trunc(iw*{width}/2)*2):max(2\\,trunc(ih*{height}/2)*2):'
        f'iw*{options.crop_left/100}:ih*{options.crop_top/100}')


def region_chain(regions,metadata,offset):
    result=''
    for i,value in enumerate(regions):
        region=normalize_region(value)
        if not region['enabled']:continue
        x,y,w,h=(region[key]/100 for key in ('x','y','w','h'))
        enabled=timing_expression(region['start'],region['duration'],offset)
        if region['mode']=='cover':
            result+=f",drawbox=x=iw*{x}:y=ih*{y}:w=iw*{w}:h=ih*{h}:color=black:t=fill:enable='{enabled}'"
        elif region['mode']=='repair':
            width=metadata.get('display_width',metadata.get('width'))
            height=metadata.get('display_height',metadata.get('height'))
            if not width or not height:raise ValueError('区域修补需要原片尺寸')
            px,py,pw,ph=int(width*x),int(height*y),int(width*w),int(height*h)
            if pw<4 or ph<4 or px<1 or py<1 or px+pw>=width or py+ph>=height:
                raise ValueError('修补区域至少 4 像素且需留出原片边缘，请扩大或移动选区')
            result+=f",delogo=x={px}:y={py}:w={pw}:h={ph}:show=0:enable='{enabled}'"
        else:
            result+=(f',split[roi_base{i}][roi_cut{i}];[roi_cut{i}]'
                f'crop=max(2\\,trunc(iw*{w}/2)*2):max(2\\,trunc(ih*{h}/2)*2):iw*{x}:ih*{y},'
                f"boxblur=luma_radius='min({region['strength']},trunc((min(w,h)-1)/2))':luma_power=1:chroma_radius=0:chroma_power=0[roi_mask{i}];"
                f"[roi_base{i}][roi_mask{i}]overlay=x=main_w*{x}:y=main_h*{y}:enable='{enabled}'")
    return result
