import hashlib
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import buffer_publish as buffer

class MediaRetryTests(unittest.TestCase):
    def clip(self):
        return {'video_url':'https://github.com/NowlisArt/twitch-tiktok-automation/releases/download/test/clip.mp4',
                'video_sha256':hashlib.sha256(b'video').hexdigest()}

    def test_new_release_404_is_retried_before_submission(self):
        clip=self.clip()
        failure=urllib.error.HTTPError(clip['video_url'],404,'Not Found',{},None)
        with patch.object(buffer.urllib.request,'urlopen',side_effect=[failure,io.BytesIO(b'video')]) as fetch, \
             patch('time.sleep'):
            buffer.verify_media(clip)
        self.assertEqual(2,fetch.call_count)

    def test_exhausted_media_retry_leaves_no_submission_reservation(self):
        clip=self.clip()
        failure=urllib.error.HTTPError(clip['video_url'],404,'Not Found',{},None)
        with patch.object(buffer.urllib.request,'urlopen',side_effect=failure) as fetch, \
             patch('time.sleep'), patch.object(buffer,'checkpoint') as checkpoint, \
             patch.object(buffer,'request') as mutation:
            with self.assertRaises(buffer.MediaUnavailable):
                buffer.publish({'created':[clip]},[],None,planned=[(clip,None)])
        self.assertEqual(4,fetch.call_count)
        self.assertNotIn('reservation_id',clip)
        checkpoint.assert_not_called()
        mutation.assert_not_called()

    def test_mismatching_bytes_are_never_accepted_or_retried(self):
        with patch.object(buffer.urllib.request,'urlopen',return_value=io.BytesIO(b'wrong')) as fetch:
            with self.assertRaisesRegex(RuntimeError,'hash differs'):
                buffer.verify_media(self.clip())
        self.assertEqual(1,fetch.call_count)
