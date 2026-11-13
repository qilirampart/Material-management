"""Same-source grids and opt-in canvas effects; never alter audio or duration."""
import math
import re

PICTURE_DEFAULTS=dict(grid_layout='none',grid_fit='contain',picture_style='original',
    vignette=0,border_width=0,border_color='FFFFFF')
GRID_LAYOUTS={'none':(1,1),'two_rows':(1,2),'three_rows':(1,3),
    'two_columns':(2,1),'three_columns':(3,1),'quad':(2,2)}


def validate_picture_effects(options):
    if options.grid_layout not in GRID_LAYOUTS or options.grid_fit not in {'contain','fill'}:
        raise ValueError('分屏布局或适配方式无效')
    if options.picture_style not in {'original','monochrome','negative','sepia'}:
        raise ValueError('画面风格无效')
    if not isinstance(options.vignette,(int,float)) or not math.isfinite(options.vignette) or not 0<=options.vignette<=1:
        raise ValueError('暗角强度须为 0–100%')
    if not isinstance(options.border_width,int) or not 0<=options.border_width<=40:
        raise ValueError('边框宽度须为 0–40 像素')
    if not isinstance(options.border_color,str) or not re.fullmatch(r'[0-9A-Fa-f]{6}',options.border_color):
        raise ValueError('边框颜色须为六位十六进制色值')


def grid_chain(options):
    chain=''
    columns,rows=GRID_LAYOUTS[options.grid_layout]
    count=columns*rows
    if count>1:
        # Even cells preserve yuv420p; any residual 2 px go to the outer padding.
        width=options.output_width//columns//2*2;height=options.output_height//rows//2*2
        chain+=f',split={count}'+''.join(f'[grid_source{i}]' for i in range(count))
        for i in range(count):
            chain+=f';[grid_source{i}]scale={width}:{height}:force_original_aspect_ratio='
            if options.grid_fit=='contain':
                chain+=f'decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black'
            else:chain+=f'increase:force_divisible_by=2,crop={width}:{height}'
            chain+=f',setsar=1[grid_cell{i}]'
        layout='|'.join(f'{i%columns*width}_{i//columns*height}' for i in range(count))
        chain+=';'+''.join(f'[grid_cell{i}]' for i in range(count))+f'xstack=inputs={count}:layout={layout}:shortest=1'
        chain+=f',pad={options.output_width}:{options.output_height}:(ow-iw)/2:(oh-ih)/2:black'
    return chain


def picture_effect_chain(options):
    chain=''
    if options.picture_style=='monochrome':chain+=',hue=s=0'
    elif options.picture_style=='negative':chain+=',negate'
    elif options.picture_style=='sepia':
        chain+=',colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131'
    if options.vignette:chain+=f',vignette=angle=PI/2*{options.vignette}'
    if options.border_width:
        chain+=f',drawbox=x=0:y=0:w=iw:h=ih:color=0x{options.border_color}:t={options.border_width}'
    return chain
