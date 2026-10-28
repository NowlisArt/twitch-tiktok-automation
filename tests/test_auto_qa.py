import datetime as dt
import json
import tempfile
import os
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from test_pipeline import candidate, NOW
import quality
import distribute
import pipeline
import auto_qa
import review_release


def auto_clip(**changes):
    clip = candidate(subtitle_verified=False, editorial_review_status='automatic_checks_passed',
                     quality_score_verified=False, quality_score=None)
    clip['automated_qa'] = {'version': 1, 'status': 'passed',
        'checked_at': '2026-10-25T07:00:00Z',
        'video_sha256': clip['video_sha256'], 'subtitle_sha256': clip['subtitle_sha256'],
        'transcript_agreement': .92, 'avg_logprob': -.35,
        'checks': {k: True for k in auto_qa.REQUIRED_CHECKS}}
    clip.update(changes)
    return clip


class AutomaticQATests(unittest.TestCase):
    def test_honest_automatic_approval_needs_no_fake_manual_flags(self):
        clip = auto_clip()
        self.assertTrue(quality.automatic_review_for(clip))
        self.assertTrue(distribute.eligible(clip, 85))
        self.assertFalse(clip['subtitle_verified'])
        self.assertFalse(clip['quality_score_verified'])

    def test_changed_media_cannot_reuse_machine_check(self):
        self.assertFalse(quality.automatic_review_for(auto_clip(video_sha256='changed')))

    def test_failed_check_and_low_agreement_block(self):
        for mode in ('timing', 'agreement', 'confidence'):
            clip = auto_clip()
            if mode == 'timing': clip['automated_qa']['checks']['subtitle_timing'] = False
            if mode == 'agreement': clip['automated_qa']['transcript_agreement'] = .5
            if mode == 'confidence': clip['automated_qa']['avg_logprob'] = -1.1
            self.assertFalse(quality.automatic_review_for(clip))

    def test_human_rejection_is_not_silently_overridden(self):
        clip = auto_clip()
        review = {'clip_id': clip['clip_id'], 'video_sha256': clip['video_sha256'],
                  'subtitle_sha256': clip['subtitle_sha256'], 'decision': 'changes_requested'}
        with patch.object(quality, 'review_records', return_value=[review]):
            self.assertFalse(quality.automatic_review_for(clip))

    def test_automatic_checks_do_not_replace_rights_and_freshness(self):
        with patch.object(quality, 'rights_for', return_value=None):
            self.assertTrue(any('permission' in r for r in quality.publication_reasons(auto_clip(), NOW)))
        self.assertTrue(any('older' in r for r in quality.publication_reasons(auto_clip(), NOW+dt.timedelta(days=4))))

    def test_transcript_comparison_uses_words_not_punctuation(self):
        self.assertEqual(1, auto_qa.transcript_agreement('Oh mein Gott, ich bin tot!', 'oh mein gott ich bin tot'))
        self.assertLess(auto_qa.transcript_agreement('ich spiele heute minecraft', 'vielen dank fürs zuschauen'), .5)

    def test_wrong_caption_text_fails_even_when_source_and_rendered_audio_agree(self):
        expected='Heute spielen wir zusammen ein spannendes Minecraft Abenteuer'
        def transcribe(path):
            return [(i,i+.5,w) for i,w in enumerate(expected.split())]
        transcribe.last_confidence=-.3
        with tempfile.TemporaryDirectory() as temp:
            video,subs=Path(temp)/'v.mp4',Path(temp)/'s.ass'
            video.write_bytes(b'video'); subs.write_bytes(b'subs')
            with patch.object(auto_qa,'caption_checks',return_value={'passed':True,'text':'Ganz anderer falscher Text'}):
                with self.assertRaisesRegex(ValueError,'transcript mismatch'):
                    auto_qa.verify(video,subs,15,expected,-.3,transcribe)

    def test_overlapping_or_unreadable_subtitles_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'subs.ass'
            p.write_text('Dialogue: 0,0:00:00.00,0:00:02.00,TikTok,,0,0,0,,Hallo Welt\n'
                         'Dialogue: 0,0:00:01.00,0:00:02.50,TikTok,,0,0,0,,Noch ein Satz\n')
            self.assertFalse(auto_qa.caption_checks(p, 15)['passed'])

    def test_long_german_word_wraps_instead_of_wasting_render(self):
        words = [(0, 1.8, 'Donaudampfschifffahrtsgesellschaft'), (2.1, 3.3, 'wirklich?'),
                 (4, 5.2, 'Noch'), (5.3, 6.4, 'ein'), (6.5, 7.7, 'Satz.'),
                 (9, 10.2, 'Das'), (10.3, 11.5, 'war'), (11.6, 13, 'gut.')]
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'subs.ass'
            self.assertTrue(pipeline.write_subs(words, 0, 15, p))
            self.assertTrue(auto_qa.caption_checks(p, 15)['passed'])

    def test_release_failure_does_not_block_other_candidates(self):
        state={'created':[dict(clip_id='broken',qa_run_id='1'),dict(clip_id='good',qa_run_id='2')]}
        with patch.object(review_release,'read_state',return_value=state), \
             patch.object(review_release,'save_state'), \
             patch.object(review_release,'promote_one',side_effect=[ValueError('expired'),True]) as promote:
            review_release.main()
            self.assertEqual(2,promote.call_count)
            self.assertEqual('ValueError',state['created'][0]['release_error'])

    def test_same_run_machine_checked_clip_can_release_without_manual_review(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                folder = Path('rendered/qa_samples/accepted-sample')
                folder.mkdir(parents=True)
                (folder/'tiktok.mp4').write_bytes(b'accepted-media')
                (folder/'cover.jpg').write_bytes(b'cover')
                (folder/'subs.ass').write_bytes(b'accepted-captions')
                clip = auto_clip(qa_run_id='123',qa_sample_folder='accepted-sample',
                    video_sha256=hashlib.sha256(b'accepted-media').hexdigest(),
                    subtitle_sha256=hashlib.sha256(b'accepted-captions').hexdigest())
                with patch.object(review_release,'publication_reasons',return_value=[]), \
                     patch.object(review_release,'verify_render_media'), \
                     patch.object(review_release,'review_for',return_value=None), \
                     patch.object(review_release,'automatic_review_for',return_value={'status':'passed'}), \
                     patch.object(review_release,'rights_for',return_value={'id':'oral','status':'user_attested_oral'}), \
                     patch.object(review_release,'release',return_value=('https://host/video.mp4','https://host/cover.jpg')), \
                     patch.object(review_release.subprocess,'run') as download:
                    self.assertTrue(review_release.promote_one(clip))
                    download.assert_not_called()
                self.assertEqual('approved_for_distribution',clip['status'])
                self.assertEqual('automatic_machine_checks',clip['approval_method'])
                self.assertFalse(clip['subtitle_verified'])
                self.assertFalse(clip['quality_score_verified'])
            finally:
                os.chdir(previous)


class CaptionPackingRegressionTests(unittest.TestCase):
    def test_only_old_layout_failures_are_retried_after_the_fix(self):
        stamp=NOW.isoformat()
        state={'failed_attempts':{
            'old-layout':{'at':stamp,'reason':'Unreadable or missing captions'},
            'current-layout':{'at':stamp,'reason':'Unreadable or missing captions','caption_layout_version':2},
            'no-speech':{'at':stamp,'reason':'Insufficient reliable speech'},
            'network':{'at':stamp,'reason':'Download timed out'}}}
        self.assertEqual({'current-layout','no-speech','network'},pipeline.current_failed_ids(state,NOW))

    def test_long_german_words_form_two_line_cards_without_losing_speech(self):
        words=['Geschwindigkeiten','Unglaublicherweise','Aufmerksamkeit']*3
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'subs.ass'
            self.assertTrue(pipeline.write_subs([(i*1.5,(i+1)*1.5,w) for i,w in enumerate(words)],0,15,path))
            result=auto_qa.caption_checks(path,15)
            self.assertTrue(result['passed'],result['reasons'])
            self.assertEqual(words,result['text'].split())

    def test_fast_speech_remains_rejected_without_creating_three_line_cards(self):
        words=['Geschwindigkeiten','Unglaublicherweise','Aufmerksamkeit']*3
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'subs.ass'
            self.assertFalse(pipeline.write_subs([(i*.4,(i+1)*.4,w) for i,w in enumerate(words)],0,15,path))
            reasons=auto_qa.caption_checks(path,15)['reasons']
            self.assertIn('caption too fast',reasons)
            self.assertNotIn('caption exceeds two readable lines',reasons)


if __name__ == '__main__':
    unittest.main()
