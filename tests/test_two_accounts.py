import datetime as dt
import unittest
from unittest.mock import patch
from test_pipeline import candidate, NOW
import buffer_publish as buffer
import pipeline

DREAM = {'id': 'dreamvoid', 'channel_id': '6ad6c095778b240e2f624d3b', 'expected_handle': 'dreamvoid26'}
SUN = {'id': 'sunshine', 'channel_id': '6ade2e8c2f1f5ed648cabd2c', 'expected_handle': 'suhshine28'}


class TwoAccountTests(unittest.TestCase):
    def test_both_exact_existing_accounts_enabled(self):
        self.assertEqual([DREAM, SUN], buffer.ACCOUNTS)

    def test_ten_unique_videos_five_per_account(self):
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            result = buffer.plan_all({'created': [candidate(str(i)) for i in range(12)]}, [], NOW)
        self.assertEqual(10, len(result))
        self.assertEqual(10, len({c['clip_id'] for c, _, _ in result}))
        for account in (DREAM, SUN):
            self.assertEqual(5, sum(a['id'] == account['id'] for _, _, a in result))

    def test_shortage_shared_fairly(self):
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            result = buffer.plan_all({'created': [candidate(str(i)) for i in range(3)]}, [], NOW)
        counts = [sum(a['id'] == account['id'] for _, _, a in result) for account in (DREAM, SUN)]
        self.assertEqual(3, sum(counts))
        self.assertLessEqual(abs(counts[0] - counts[1]), 1)

    def test_unserved_account_gets_single_candidate(self):
        past = [{'id': 'old', 'channelId': DREAM['channel_id'], 'sentAt': '2026-10-24T16:00:00Z', 'assets': []}]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            result = buffer.plan_all({'created': [candidate()]}, past, NOW)
        self.assertEqual('sunshine', result[0][2]['id'])

    def test_daily_cap_is_independent(self):
        past = [{'id': str(i), 'channelId': DREAM['channel_id'], 'sentAt': f'2026-10-25T0{i}:00:00Z', 'assets': []} for i in range(5)]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            result = buffer.plan_all({'created': [candidate(str(i)) for i in range(6)]}, past, NOW)
        self.assertEqual(5, len(result))
        self.assertTrue(all(a['id'] == 'sunshine' for _, _, a in result))

    def test_sunshine_remote_use_blocks_both(self):
        clip = candidate()
        post = {'id': 'sun-post', 'channelId': SUN['channel_id'], 'assets': [{'source': clip['video_url']}]}
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertFalse(buffer.plan_all({'created': [clip]}, [post], NOW))

    def test_shared_slug_not_allocated_twice_across_accounts(self):
        clips = [candidate('a', clip_slug='same'), candidate('b', clip_slug='same')]
        with patch.object(buffer, 'publication_reasons', return_value=[]):
            self.assertEqual(1, len(buffer.plan_all({'created': clips}, [], NOW)))

    def test_sunshine_pending_receipt_not_assigned_to_dreamvoid(self):
        clip = candidate(status='buffer_submission_pending', buffer_channel_id=SUN['channel_id'], reserved_for='sunshine')
        post = dict(id='sun-post', channelId=SUN['channel_id'], status='scheduled', assets=[{'source': clip['video_url']}])
        buffer.reconcile({'created': [clip]}, [post], NOW, DREAM)
        self.assertNotIn('buffer_post_id', clip)
        buffer.reconcile({'created': [clip]}, [post], NOW, SUN)
        self.assertEqual('sun-post', clip['buffer_post_id'])
        self.assertEqual(SUN['channel_id'], clip['buffer_channel_id'])

    def test_sunshine_intent_and_payload_use_sunshine_id(self):
        clip = candidate()
        state = {'created': [clip]}
        def persist(value):
            self.assertEqual('sunshine', value['created'][0]['reserved_for'])
            self.assertEqual(SUN['channel_id'], value['created'][0]['buffer_channel_id'])
        def create(query, variables):
            self.assertEqual(SUN['channel_id'], variables['input']['channelId'])
            raise TimeoutError('uncertain')
        with patch.object(buffer, 'verify_media'), patch.object(buffer, 'checkpoint', side_effect=persist), \
             patch.object(buffer, 'request', side_effect=create):
            with self.assertRaises(TimeoutError):
                buffer.publish(state, [], NOW, SUN, planned=[(clip, next(buffer.slot(NOW)))])
        self.assertEqual('buffer_submission_pending', clip['status'])

    def test_budget_allows_both_accounts(self):
        stamp = NOW.strftime('%Y-%m-%dT07:00:00Z')
        item = {'created_at': stamp, 'original_created_at': stamp, 'rendered_duration': 20, 'views_at_selection': 9000}
        self.assertTrue(pipeline.can_prepare({'created': [item] * 10}, NOW)[0])
        self.assertFalse(pipeline.can_prepare({'created': [item] * 12}, NOW)[0])

    def test_exact_sunshine_connection_required(self):
        for changes, allowed in [({}, True), ({'name': 'wrong'}, False), ({'isDisconnected': True}, False)]:
            channel = dict(id=SUN['channel_id'], name='suhshine28', service='tiktok',
                           isDisconnected=False, isLocked=False, isQueuePaused=False)
            channel.update(changes)
            with patch.object(buffer, 'request', side_effect=[{'account': {'organizations': [{'id': 'org'}]}}, {'channels': [channel]}]):
                if allowed:
                    self.assertEqual('org', buffer.verify_channel(SUN))
                else:
                    with self.assertRaises(RuntimeError):
                        buffer.verify_channel(SUN)


if __name__ == '__main__':
    unittest.main()
