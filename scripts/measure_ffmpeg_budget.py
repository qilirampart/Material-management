"""Bounded CPU encode comparison; synthetic compressed input lives only in RAM."""
import json,os,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import psutil
from src.material_variants import VariantOptions,build_video_filter
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
encoded=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=1920x1080:rate=30:duration=4',
 '-c:v','libx264','-threads','2','-preset','ultrafast','-pix_fmt','yuv420p','-f','matroska','pipe:1'],
 capture_output=True,timeout=60,creationflags=flags,check=True).stdout
options=VariantOptions(foreground_scale=.8,speed=1.06)
graph=build_video_filter(options,source_metadata={'frame_rate':30})
reports=[]
for count in (0,4,8,8,4,0):
 args=['ffmpeg','-v','error']
 if count:args+=['-filter_complex_threads','4','-filter_threads','4']
 args+=['-threads',str(count),'-i','pipe:0','-filter_complex',graph,'-map','[outv]','-an',
        '-c:v','libx264','-threads',str(count),'-preset','veryfast','-b:v','4200k','-pix_fmt','yuv420p','-f','null','-']
 start=time.perf_counter();p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=flags)
 result={}
 def feed():
  try:result['stderr']=p.communicate(encoded,timeout=90)[1]
  except BaseException as exc:
   p.kill();p.communicate();result['error']=type(exc).__name__
 thread=threading.Thread(target=feed);thread.start();process=psutil.Process(p.pid)
 peak_threads=peak_rss=peak_private=0
 while thread.is_alive():
  try:
   memory=process.memory_info();peak_threads=max(peak_threads,process.num_threads())
   peak_rss=max(peak_rss,memory.rss);peak_private=max(peak_private,memory.private)
  except psutil.NoSuchProcess:break
  time.sleep(.01)
 thread.join()
 if p.returncode or result.get('error'):raise RuntimeError(result.get('error') or result['stderr'].decode(errors='replace')[-1000:])
 reports.append({'codec_threads':count,'filter_threads':4 if count else 'auto','seconds':round(time.perf_counter()-start,3),
   'peak_os_threads':peak_threads,'peak_rss_mib':round(peak_rss/1048576,1),'peak_private_mib':round(peak_private/1048576,1)})
 print(json.dumps(reports[-1]),flush=True)
folder=ROOT/'output/ffmpeg-budget-acceptance';folder.mkdir(parents=True,exist_ok=True)
(folder/'report.json').write_text(json.dumps({'logical_cpus':os.cpu_count(),'source':'4s 1080p30 synthetic H264 in RAM; blur background to 720x1280; CPU libx264 veryfast; null output',
 'input_bytes':len(encoded),'runs':reports},indent=2),encoding='utf-8')
