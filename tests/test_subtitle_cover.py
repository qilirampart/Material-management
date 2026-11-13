import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from PIL import Image
from src.material_variants import VariantOptions,generate_variants,render_micro_preview
from src.media import run,FFmpegCancelled
from src.subtitle_cover import prepare_subtitles,ass_seconds


class SubtitleCoverTests(unittest.TestCase):
    def test_new_settings_are_validated_without_changing_old_defaults(self):
        VariantOptions().validate()
        for kwargs in ({'subtitle_encoding':'command'},{'subtitle_size':2},{'cover_mode':'unknown'},
            {'cover_duration':0},{'subtitle_timing':'unknown'}):
            with self.assertRaises(ValueError):VariantOptions(**kwargs).validate()

    def test_encoded_subtitle_timing_style_preservation_and_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);srt=root/'captions.srt'
            srt.write_text('1\n00:00:03,000 --> 00:00:05,000\n中文字幕\n',encoding='gb18030')
            options=VariantOptions(subtitle_path=str(srt),subtitle_encoding='gb18030',
                subtitle_timing='body',subtitle_shift=.5)
            path,_=prepare_subtitles(options,root,1,2,5)
            text=path.read_text(encoding='utf-8')
            self.assertIn('中文字幕',text)
            line=next(line for line in text.splitlines() if line.startswith('Dialogue:')).split(',',9)
            self.assertEqual(ass_seconds(line[1]),1.5);self.assertEqual(ass_seconds(line[2]),3.5)
            ass=root/'original.ass';ass.write_text(text.replace('Microsoft YaHei','SimHei').replace('中文字幕',r'{\an7}中文字幕'),encoding='utf-8')
            preserved,keep=prepare_subtitles(replace(options,subtitle_path=str(ass),subtitle_encoding='utf-8'),root,0,0,5)
            self.assertTrue(keep);self.assertIn('SimHei',preserved.read_text(encoding='utf-8'))
            self.assertIn(r'{\an7}',preserved.read_text(encoding='utf-8'))
            unified,keep=prepare_subtitles(replace(options,subtitle_path=str(ass),subtitle_encoding='utf-8',subtitle_keep_ass_style=False),root,0,0,5)
            self.assertFalse(keep);self.assertNotIn(r'{\an7}',unified.read_text(encoding='utf-8'))
            with self.assertRaises(FFmpegCancelled):prepare_subtitles(options,root,0,0,5,lambda:True)

    def test_real_subtitles_follow_trim_speed_and_cover_does_not_extend_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';subtitle=root/'captions.srt';image=root/'cover.png'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=black:size=320x240:rate=30:duration=4',
                 '-c:v','libx264',str(source)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=720x1280','-frames:v','1',str(image)])
            subtitle.write_text('1\n00:00:02,000 --> 00:00:03,000\nTEST SUBTITLE\n',encoding='utf-8')
            options=VariantOptions(trim_start=1,trim_end=0,speed=1.2,background='black',color_adjust=False,
                subtitle_path=str(subtitle),subtitle_timing='source',cover_mode='image',cover_path=str(image),cover_duration=.2)
            result=generate_variants([{'video_id':'sub','path':str(source)}],root/'out',options)
            self.assertFalse(result['failed'],result['failed'])
            output=result['outputs'][0]
            self.assertAlmostEqual(output['metadata']['duration'],2.5,delta=.15)
            self.assertTrue(Path(output['metadata']['cover']['path']).is_file())
            preview=render_micro_preview(source,root/'preview.mp4',options,start=2,seconds=1)
            self.assertAlmostEqual(preview['metadata']['duration'],1,delta=.15)
            def frame(path,when):
                png=root/'frame.png'
                run(['ffmpeg','-y','-v','error','-ss',str(when),'-i',str(path),'-frames:v','1',str(png)])
                with Image.open(png) as im:return im.convert('RGB').copy()
            # Cover replaces first picture only; at .4s the source remains black.
            self.assertGreater(frame(output['path'],.05).getpixel((360,640))[0],200)
            self.assertLess(max(frame(output['path'],.4).getpixel((360,640))),15)
            def white_pixels(image):return sum(min(p)>180 for p in image.crop((0,1100,720,1280)).getdata())
            self.assertGreater(white_pixels(frame(output['path'],1.1)),100)
            self.assertEqual(white_pixels(frame(output['path'],.4)),0)
            self.assertGreater(white_pixels(frame(preview['path'],.1)),100)
            self.assertLess(max(frame(preview['path'],.1).getpixel((360,640))),15)
            # Adding an intro does not move the raw-source subtitle clock, or
            # make a body-only preview repeat the final cover.
            with_intro=replace(options,intro_path=str(image),intro_duration=.5,cover_mode='frame',cover_time=1)
            headed=render_micro_preview(source,root/'headed.mp4',with_intro,seconds=2,preview_section='head')
            self.assertAlmostEqual(headed['metadata']['duration'],2.5,delta=.15)
            self.assertLess(max(frame(headed['path'],.05).getpixel((360,640))),15)
            self.assertGreater(white_pixels(frame(headed['path'],1.6)),100)
            body=render_micro_preview(source,root/'body.mp4',replace(options,intro_path=str(image),intro_duration=.5),seconds=1)
            self.assertLess(max(frame(body['path'],.05).getpixel((360,640))),15)
            top=render_micro_preview(source,root/'top.mp4',replace(options,subtitle_position='top',subtitle_margin=88),start=2,seconds=1)
            top_frame=frame(top['path'],.1)
            self.assertGreater(sum(min(p)>180 for p in top_frame.crop((200,70,520,160)).getdata()),100)
            self.assertEqual(white_pixels(top_frame),0)
