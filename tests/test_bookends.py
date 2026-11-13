import tempfile
import unittest
import subprocess
import array
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path
from src.material_variants import VariantOptions,generate_variants,render_micro_preview
from src.media import run


class BookendTests(unittest.TestCase):
    def test_final_size_budget_uses_composed_duration_not_body_duration(self):
        from src.material_variants import _render_micro
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'intro.png';image.write_bytes(b'fixture')
            options=VariantOptions(intro_path=str(image),outro_path=str(image),intro_duration=2,
                outro_duration=3,trim_start=0,trim_end=0,speed=1,transition='fade',transition_duration=.5)
            with patch('src.material_variants.transcode_for_upload_bitrate',return_value={}) as transcode:
                _render_micro(root/'source.mp4',root/'out.mp4',options,{'duration':10,'audio':False},0,10)
            self.assertEqual(transcode.call_args.kwargs['output_duration'],14)
            self.assertEqual(transcode.call_args.kwargs['clip_duration'],10)
            self.assertEqual(len(transcode.call_args.kwargs['bookend_inputs']),2)

    def test_plan_counts_transition_overlap_and_rejects_short_segments(self):
        from src.bookends import plan_bookends
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'intro.png';image.write_bytes(b'fixture')
            options=VariantOptions(intro_path=str(image),outro_path=str(image),intro_duration=2,
                outro_duration=3,transition='fade',transition_duration=.5)
            plan=plan_bookends(options,10)
            self.assertEqual(plan['duration'],14)
            self.assertEqual([x['kind'] for x in plan['segments']],['intro','body','outro'])
            with self.assertRaises(ValueError):
                plan_bookends(VariantOptions(intro_path=str(image),intro_duration=.5,
                    transition='fade',transition_duration=.4),10)

    def test_real_bookends_keep_audio_and_match_head_tail_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';intro=root/'intro.png';outro=root/'outro.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=4',
                '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=240x320','-frames:v','1',str(intro)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=blue:size=320x240:rate=25:duration=1',
                '-f','lavfi','-i','sine=frequency=880:duration=1','-c:v','libx264','-c:a','aac','-shortest',str(outro)])
            for transition in ('cut','fade','dissolve','wipeleft','wiperight','slideup'):
                options=VariantOptions(intro_path=str(intro),outro_path=str(outro),intro_duration=1,
                    outro_duration=2,transition=transition,transition_duration=.2)
                result=generate_variants([{'video_id':'book','path':str(source),'drama':'test'}],root/'out',options)
                self.assertFalse(result['failed'],result['failed'])
                meta=result['outputs'][0]['metadata']
                expected=3.7/1.02+2-(.4 if transition!='cut' else 0)
                self.assertAlmostEqual(meta['duration'],expected,delta=.2)
                self.assertTrue(meta['audio'])
                self.assertGreater(meta['video_bitrate_bps'],3500000)
                self.assertLessEqual(meta['video_bitrate_bps'],5000000)
                if transition=='cut':
                    def samples(second):
                        data=subprocess.run(['ffmpeg','-v','error','-ss',str(second),'-i',result['outputs'][0]['path'],
                            '-t','0.2','-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'],capture_output=True,check=True).stdout
                        return array.array('h',data)
                    self.assertLess(max(map(abs,samples(.3))),20)  # Still-image intro is silent.
                    for second,frequency in [(1.5,440),(expected-.5,880)]:
                        values=samples(second)
                        crossings=sum(a<0<=b for a,b in zip(values,values[1:]))
                        self.assertAlmostEqual(crossings*8000/len(values),frequency,delta=25)
                if transition=='fade':
                    for section in ('body','head','tail'):
                        preview=render_micro_preview(source,root/(section+'.mp4'),options,
                            seconds=1,preview_section=section)
                        self.assertEqual(preview['preview_section'],section)
                        self.assertAlmostEqual(preview['metadata']['duration'],1 if section=='body' else 1.8,delta=.2)
            muted=generate_variants([{'video_id':'mute','path':str(source)}],root/'muted',replace(options,audio_mode='mute'))
            self.assertFalse(muted['failed'],muted['failed'])
            self.assertFalse(muted['outputs'][0]['metadata']['audio'])
