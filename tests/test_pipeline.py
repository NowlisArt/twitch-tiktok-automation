import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import buffer_publish as buffer
import distribute
import pipeline
import quality
import storage

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 25, 8, tzinfo=UTC)


def candidate(cid='a', **changes):
    clip = dict(clip_id=cid, clip_slug=cid, streamer='papaplatte',
        source_url='https://clips.twitch.tv/' + cid,
        original_created_at='2026-10-25T06:00:00Z', views_at_selection=1500,
        status='approved_for_distribution', technical_qa_passed=True,
        subtitle_verified=True, editorial_review_status='approved',
        rights_status='verified_permission', quality_score_verified=True,
        quality_score=90, video_sha256='a'*64, subtitle_sha256='b'*64,
        caption='Original moment #papaplatte',
        video_url='https://github.com/NowlisArt/twitch-tiktok-automation/releases/download/test/'+cid+'.mp4')
    clip.update(changes)
    return clip


class PublishingTests(unittest.TestCase):
    def test_historical_cross_field_identity(self):
        used = candidate('old', clip_slug='same', buffer_post_id='used')
        new = candidate('same', clip_slug='different')
        self.assertTrue(distribute.clip_keys(used) & distribute.clip_keys(new))
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertEqual([], buffer.plan({'created': [used, new]}, [], NOW))

    def test_five_distinct_slots_and_no_reuse(self):
        state = {'created': [candidate(str(i)) for i in range(9)]}
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            plan = buffer.plan(state, [], NOW)
        self.assertEqual(5, len(plan))
        self.assertEqual(5, len({c['clip_id'] for c, _ in plan}))
        self.assertTrue(all(t.astimezone(buffer.ZONE).date() == NOW.date() for _, t in plan))

    def test_manual_posts_consume_daily_cap(self):
        posts = [dict(id=str(i), channelId=buffer.CHANNEL, dueAt=f'2026-10-25T0{i}:00:00Z', assets=[]) for i in range(5)]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertFalse(buffer.plan({'created': [candidate()]}, posts, NOW))

    def test_unscheduled_manual_sent_posts_consume_cap(self):
        posts = [dict(id=str(i), channelId=buffer.CHANNEL, sentAt=f'2026-10-25T0{i}:00:00Z', assets=[]) for i in range(5)]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertFalse(buffer.plan({'created': [candidate()]}, posts, NOW))

    def test_unknown_pending_counts_toward_cap(self):
        intents = [candidate(str(i), status='buffer_submission_pending',
                             buffer_channel_id=buffer.CHANNEL, buffer_due_at=f'2026-10-25T0{i}:00:00Z') for i in range(5)]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertFalse(buffer.plan({'created': intents + [candidate('new')]}, [], NOW))

    def test_dst_berlin_slots(self):
        winter = next(buffer.slot(dt.datetime(2026, 10, 25, 8, tzinfo=UTC)))
        summer = next(buffer.slot(dt.datetime(2026, 7, 25, 7, tzinfo=UTC)))
        self.assertEqual(dt.timedelta(hours=1), winter.utcoffset())
        self.assertEqual(dt.timedelta(hours=2), summer.utcoffset())
        self.assertEqual(11, winter.hour)
        self.assertEqual(11, summer.hour)

    def test_all_pages_channel_filter(self):
        page1 = {'posts': {'edges': [{'node': {'id': '1', 'channelId': buffer.CHANNEL}}],
                          'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}}}
        page2 = {'posts': {'edges': [{'node': {'id': '2', 'channelId': 'sunshine'}}],
                          'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        with patch.object(buffer, 'request', side_effect=[page1, page2]) as request:
            self.assertEqual(['1'], [p['id'] for p in buffer.fetch_posts('org')])
            self.assertEqual('next', request.call_args.args[1]['after'])
            self.assertEqual([buffer.CHANNEL], request.call_args.args[1]['input']['filter']['channelIds'])

    def test_incomplete_page_blocks(self):
        with patch.object(buffer, 'request', return_value={'posts': {'edges': [], 'pageInfo': {'hasNextPage': True, 'endCursor': None}}}):
            with self.assertRaises(RuntimeError):
                buffer.fetch_posts('org')

    def test_durable_intent_before_network_timeout(self):
        clip, events = candidate(), []
        state = {'created': [clip]}
        def persist(value):
            self.assertEqual('buffer_submission_pending', value['created'][0]['status'])
            events.append('persisted')
        def fail(*args):
            self.assertEqual(['persisted'], events)
            raise TimeoutError('ambiguous response')
        with patch.object(buffer, 'plan', return_value=[(clip, next(buffer.slot(NOW)))]), \
             patch.object(buffer, 'verify_media'), patch.object(buffer, 'checkpoint', side_effect=persist), \
             patch.object(buffer, 'request', side_effect=fail):
            with self.assertRaises(TimeoutError):
                buffer.publish(state, [], NOW)
        self.assertTrue(distribute.unavailable(clip))

    def test_failed_checkpoint_prevents_post(self):
        clip = candidate()
        with patch.object(buffer, 'plan', return_value=[(clip, next(buffer.slot(NOW)))]), \
             patch.object(buffer, 'verify_media'), patch.object(buffer, 'checkpoint', side_effect=RuntimeError('push rejected')), \
             patch.object(buffer, 'request') as request:
            with self.assertRaises(RuntimeError):
                buffer.publish({'created': [clip]}, [], NOW)
            request.assert_not_called()

    def test_reconcile_sent_is_distinct_from_scheduled(self):
        clip = candidate(buffer_post_id='post', status='buffer_scheduled')
        state = {'created': [clip]}
        post = dict(id='post', status='scheduled', dueAt=NOW.isoformat())
        buffer.reconcile(state, [post], NOW)
        self.assertNotIn('buffer_sent_at', clip)
        post.update(status='sent', sentAt=NOW.isoformat(), externalLink='https://www.tiktok.com/@dreamvoid26/video/123')
        buffer.reconcile(state, [post], NOW)
        self.assertEqual('buffer_reported_published', clip['status'])
        self.assertEqual(post['externalLink'], clip['buffer_public_url'])

    def test_pending_recovery_exact_media_only(self):
        clip = candidate(status='buffer_submission_pending')
        buffer.reconcile({'created': [clip]}, [dict(id='post', status='scheduled', assets=[{'source': clip['video_url']}])], NOW)
        self.assertEqual('post', clip['buffer_post_id'])

    def test_wrong_or_paused_channel_blocks(self):
        for change in ({'name': 'sunshine'}, {'isQueuePaused': True}, {'isDisconnected': True}):
            channel = dict(id=buffer.CHANNEL, name='dreamvoid26', service='tiktok', isDisconnected=False, isLocked=False, isQueuePaused=False)
            channel.update(change)
            with patch.object(buffer, 'request', side_effect=[{'account': {'organizations': [{'id': 'org'}]}}, {'channels': [channel]}]):
                with self.assertRaises(RuntimeError):
                    buffer.verify_channel()


class EvidenceTests(unittest.TestCase):
    def test_claims_are_not_evidence(self):
        reasons = quality.publication_reasons(candidate(), NOW)
        self.assertTrue(any('permission' in r for r in reasons))
        self.assertTrue(any('review' in r for r in reasons))

    def test_freshness_at_scheduled_time(self):
        with patch.object(quality, 'rights_for', return_value={'id': 'evidence'}), \
             patch.object(quality, 'review_for', return_value={'reviewer': 'human'}):
            self.assertFalse(quality.publication_reasons(candidate(), NOW))
            reasons = quality.publication_reasons(candidate(), NOW + dt.timedelta(days=4))
            self.assertIn('source older than 72 hours at publication', reasons)

    def test_evidence_expiry_and_scope(self):
        permission = dict(id='p', streamer='papaplatte', status='verified_permission', evidence_reference='private-record',
            verified_by='owner', verified_at='2026-10-24T00:00:00Z', scope=['edit','subtitles','tiktok','public_hosting'])
        for change, expected in [({}, True), ({'revoked': True}, False),
                                  ({'expires_at': '2026-10-25T07:00:00Z'}, False), ({'scope': ['tiktok']}, False)]:
            with patch.object(Path, 'read_text', return_value=json.dumps({'permissions': [dict(permission, **change)]})):
                self.assertEqual(expected, bool(quality.rights_for('papaplatte', NOW)))

    def test_subtitle_review_bound_to_exact_hashes(self):
        clip = candidate()
        review = dict(clip_id='a', video_sha256=clip['video_sha256'], subtitle_sha256=clip['subtitle_sha256'],
            reviewer='reviewer', reviewed_at='2026-10-24T00:00:00Z', notes='Listened and watched exact final video.',
            subtitle_accuracy=True, readability=True, audio_video=True, context=True, rights_in_clip=True, quality_score=90)
        with patch.object(Path, 'read_text', return_value=json.dumps({'reviews': [review]})):
            self.assertIsNotNone(quality.review_for(clip))
            self.assertIsNone(quality.review_for(dict(clip, subtitle_sha256='changed')))

    def test_atomic_json_has_real_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            storage.write_json(path, {'created': []})
            self.assertEqual({'created': []}, json.loads(path.read_text()))
            self.assertTrue(path.read_bytes().endswith(b'\n'))
            self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_no_public_release_during_preparation(self):
        source = Path(pipeline.__file__).read_text(encoding='utf-8')
        main = source.split('def main():', 1)[1].split('def self_test', 1)[0]
        self.assertNotIn('= release(', main)


if __name__ == '__main__':
    unittest.main()
