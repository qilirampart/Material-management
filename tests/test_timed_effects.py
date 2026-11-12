import tempfile
import unittest
import subprocess
import array
import math
from pathlib import Path
from src.material_variants import VariantOptions,build_video_filter,build_audio_graph


class TimedEffectsTests(unittest.TestCase):
    def test_real_text_watermark_windows_and_music_envelope(self):
        from src.material_variants import generate_variants,render_micro_preview
        from src.media import run
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';music=root/'music.wav';image=root/'logo.png'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=black:size=320x240:rate=30:duration=4',
                 '-c:v','libx264',str(source)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',str(music)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=64x64','-frames:v','1',str(image)])
            options=VariantOptions(trim_start=0,trim_end=0,speed=1,color_adjust=False,background='black',
                text_tracks=[{'text':'FIRST','font_size':60,'start':.5,'duration':1},
                    {'text':'SECOND','position':'bottom','start':2,'duration':1}],
                watermark_path=str(image),watermark_start=2,watermark_duration=1,
                audio_mode='replace',music_path=str(music),music_volume=.5,
                music_delay=.5,music_duration=2,music_fade_in=.25,music_fade_out=.25)
            result=generate_variants([{'video_id':'timed','path':str(source),'drama':'test'}],root/'out',options)
            self.assertFalse(result['failed'],result['failed'])
            path=result['outputs'][0]['path']
            def pixels(second):
                data=subprocess.run(['ffmpeg','-v','error','-ss',str(second),'-i',path,'-frames:v','1',
                    '-vf','scale=64:112','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],capture_output=True,check=True).stdout
                return sum(data)
            blank=pixels(.1)
            self.assertGreater(pixels(.8),blank+200)
            self.assertLess(pixels(1.7),blank+200)
            self.assertGreater(pixels(2.3),blank+200)
            self.assertLess(pixels(3.5),blank+200)
            def rms(video,second):
                data=subprocess.run(['ffmpeg','-v','error','-ss',str(second),'-i',str(video),'-t','0.15',
                    '-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'],capture_output=True,check=True).stdout
                samples=array.array('h',data)
                return math.sqrt(sum(v*v for v in samples)/max(1,len(samples)))
            self.assertLess(rms(path,.1),20)
            self.assertGreater(rms(path,1.2),500)
            self.assertLess(rms(path,3.5),20)
            self.assertLess(rms(path,.55),rms(path,1.2)*.7)
            self.assertLess(rms(path,2.35),rms(path,1.2)*.7)
            preview=render_micro_preview(source,root/'preview.mp4',options,start=1,seconds=1)
            self.assertAlmostEqual(rms(preview['path'],.2),rms(path,1.2),delta=200)
            self.assertLessEqual(result['outputs'][0]['metadata']['video_bitrate_bps'],5000000)
    def test_text_tracks_and_timing_are_validated_and_use_output_timeline(self):
        from src.text_tracks import normalize_track
        track=normalize_track({'text':'标题 {剧名}','start':1,'duration':2,'scroll':'left'})
        options=VariantOptions(text_tracks=[track],watermark_start=1,watermark_duration=2)
        options.validate()
        for invalid in ({'text':'x','start':-1},{'text':'x','scroll':'command'},
                        {'text':'x','font_color':'abc:bad'},{'text':'x','x':2}):
            with self.assertRaises(ValueError):normalize_track(invalid)
        with self.assertRaises(ValueError):VariantOptions(text_tracks=[track]*7).validate()
        with self.assertRaises(ValueError):VariantOptions(music_delay=-1).validate()
        with tempfile.TemporaryDirectory() as folder:
            text=Path(folder)/'text.txt';text.write_text('标题',encoding='utf-8')
            graph=build_video_filter(options,track_paths=[text],timeline_offset=1.5)
            self.assertIn('t+1.5',graph)
            self.assertIn('drawtext=',graph)
            self.assertIn('fontcolor=',graph)
            scrolling=VariantOptions(text_tracks=[{'text':'LONG '*25,'font_size':48,'scroll':'left'}])
            self.assertIn('fontsize=48',build_video_filter(scrolling,track_paths=[text]))

    def test_audio_envelope_keeps_global_delay_in_nonzero_preview(self):
        options=VariantOptions(audio_mode='replace',music_delay=1,music_duration=2,
            music_fade_in=.25,music_fade_out=.5)
        graph,_,_=build_audio_graph(options,{'audio':True},1,timeline_offset=1.5,total_duration=6)
        self.assertIn('eval=frame',graph)
        self.assertIn('t+1.5',graph)
        self.assertIn('apad',graph)
