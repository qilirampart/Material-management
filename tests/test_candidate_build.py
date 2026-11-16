import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CandidateBuildTests(unittest.TestCase):
    def test_custom_build_directories_do_not_replace_existing_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'ffmpeg.exe';binary.write_bytes(b'0'*1000001)
            dist=root/'candidate';work=root/'candidate-work'
            with patch('sys.argv',['build_windows.py','--dist-dir',str(dist),'--work-dir',str(work)]),patch('shutil.which',return_value=str(binary)),patch('subprocess.run') as run:
                runpy.run_path('scripts/build_windows.py',run_name='__main__')
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('--distpath')+1],str(dist.resolve()))
            self.assertEqual(command[command.index('--workpath')+1],str(work.resolve()))
            self.assertEqual(command[command.index('--specpath')+1],str(work.resolve()))
