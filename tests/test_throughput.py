import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pipeline
import auto_qa
import storage

class ThroughputTests(unittest.TestCase):
    def test_short_card_borrows_adjacent_display_time_without_losing_words(self):
        words=[(0,.4,'a'*28),(.41,2,'b'*28),(3,4,'c'*28)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'subs.ass'
            self.assertTrue(pipeline.write_subs(words,0,5,path))
            checks=auto_qa.caption_checks(path,5)
            self.assertEqual(' '.join(w[2] for w in words),checks['text'])
            self.assertTrue(checks['passed'],checks['reasons'])

    def test_checkpoint_recovers_from_transient_push_failure(self):
        pushed=[]
        def run(args,**kwargs):
            if args[1]=='push':
                pushed.append(1)
                if len(pushed)==1:
                    raise subprocess.CalledProcessError(1,args,stderr='temporary transport failure')
            return subprocess.CompletedProcess(args,0,stdout='',stderr='')
        with tempfile.TemporaryDirectory() as folder, patch.object(storage,'STATE',Path(folder)/'state.json'), patch.dict(storage.os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REF':'refs/heads/main'}), patch.object(storage.subprocess,'run',side_effect=run):
            storage.checkpoint({'created':[]})
            self.assertEqual({'created':[]},__import__('json').loads((Path(folder)/'state.json').read_text()))
