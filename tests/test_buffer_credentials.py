import io
import json
import unittest
from unittest.mock import patch
from test_pipeline import candidate,NOW
from test_two_accounts import DREAM,SUN
from test_purelife import PURE
import buffer_publish as b

NOVEL={'id':'novel','channel_id':'6ae262582f1f5ed648022a42','expected_handle':'novel.novel601',
       'api_key_env':'BUFFER_API_KEY_NOVEL','optional':True}

class SeparateBufferTests(unittest.TestCase):
    def test_four_exact_targets(self):
        self.assertEqual([DREAM,SUN,PURE,NOVEL],b.ACCOUNTS)

    def test_twenty_unique_allocations_five_each(self):
        with patch.object(b,'publication_reasons',return_value=[]):
            result=b.plan_all({'created':[candidate(str(i)) for i in range(24)]},[],NOW)
        self.assertEqual(20,len(result))
        self.assertEqual(20,len({c['clip_id'] for c,_,_ in result}))
        for account in [DREAM,SUN,PURE,NOVEL]:
            self.assertEqual(5,sum(a['id']==account['id'] for _,_,a in result))

    def test_keys_isolated_and_context_restored(self):
        headers=[]
        def response(req,**kwargs):
            headers.append(req.get_header('Authorization'))
            return io.BytesIO(json.dumps({'data':{'ok':True}}).encode())
        with patch.dict(b.os.environ,{'BUFFER_API_KEY':'primary-placeholder','BUFFER_API_KEY_NOVEL':'secondary-placeholder'}), \
             patch.object(b.urllib.request,'urlopen',side_effect=response):
            b.account_request(NOVEL,'query { account { id } }')
            b.account_request(DREAM,'query { account { id } }')
        self.assertEqual(['Bearer secondary-placeholder','Bearer primary-placeholder'],headers)
        self.assertEqual('BUFFER_API_KEY',b.KEY_ENV.get())

    def test_missing_secondary_key_does_not_block_primary(self):
        with patch.dict(b.os.environ,{},clear=True),patch.object(b,'verify_channel',return_value='org'), \
             patch.object(b,'contract_check'),patch.object(b,'fetch_posts',return_value=[]):
            accounts,posts,blocked=b.collect_accounts([DREAM,NOVEL])
        self.assertEqual([DREAM],accounts)
        self.assertEqual('missing_api_key',blocked[0]['reason'])
        self.assertEqual('novel',blocked[0]['id'])

    def test_invalid_secondary_connection_does_not_block_primary(self):
        with patch.dict(b.os.environ,{'BUFFER_API_KEY_NOVEL':'placeholder'}), \
             patch.object(b,'verify_channel',side_effect=['org',RuntimeError('wrong channel')]), \
             patch.object(b,'contract_check'),patch.object(b,'fetch_posts',return_value=[]):
            accounts,posts,blocked=b.collect_accounts([DREAM,NOVEL])
        self.assertEqual([DREAM],accounts)
        self.assertEqual('verification_failed',blocked[0]['reason'])

    def test_primary_connection_failure_still_blocks_submission(self):
        with patch.object(b,'verify_channel',side_effect=RuntimeError('disconnected')):
            with self.assertRaises(RuntimeError):b.collect_accounts([DREAM])

    def test_novel_mutation_uses_secondary_key_and_keeps_timeout_lock(self):
        clip=candidate()
        def create(query,variables):
            self.assertEqual('BUFFER_API_KEY_NOVEL',b.KEY_ENV.get())
            self.assertEqual(NOVEL['channel_id'],variables['input']['channelId'])
            self.assertEqual('novel',clip['reserved_for'])
            raise TimeoutError('unknown submission')
        with patch.object(b,'verify_media'),patch.object(b,'checkpoint'),patch.object(b,'request',side_effect=create) as request:
            with self.assertRaises(TimeoutError):b.publish({'created':[clip]},[],NOW,NOVEL,planned=[(clip,NOW)])
        self.assertEqual(1,request.call_count)
        self.assertEqual('buffer_submission_pending',clip['status'])
        self.assertEqual('BUFFER_API_KEY',b.KEY_ENV.get())

    def test_ready_only_without_eligible_media_skips_network_reads(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state.json';state.write_text('{"created":[]}')
            with patch.object(b,'STATE',state),patch.object(b,'collect_accounts') as fetch:
                b.main(['--ready-only'])
        fetch.assert_not_called()

    def test_ready_only_with_media_still_verifies_live_accounts(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state.json';state.write_text('{"created":[]}')
            with patch.object(b,'STATE',state),patch.object(b,'has_ready_clip',return_value=True), \
                 patch.object(b,'collect_accounts',return_value=([DREAM],[],[])) as fetch, \
                 patch.object(b,'plan_all',return_value=[]),patch.object(b,'write_json'), \
                 patch.dict(b.os.environ,{'GITHUB_STEP_SUMMARY':''}):
                b.main(['--ready-only','--preflight'])
        fetch.assert_called_once()
