import unittest
from unittest.mock import patch
from test_pipeline import candidate,NOW
from test_two_accounts import DREAM,SUN
import buffer_publish as buffer
import pipeline

PURE={'id':'purelife','channel_id':'6adfa6322f1f5ed648ddec86','expected_handle':'pure.life.26'}

class PureLifeTests(unittest.TestCase):
    def test_three_exact_buffer_targets(self):
        self.assertEqual([DREAM,SUN,PURE],buffer.ACCOUNTS)

    def test_fifteen_distinct_videos_five_per_account(self):
        with patch.object(buffer,'publication_reasons',return_value=[]):
            result=buffer.plan_all({'created':[candidate(str(i)) for i in range(18)]},[],NOW)
        self.assertEqual(15,len(result))
        self.assertEqual(15,len({c['clip_id'] for c,_,_ in result}))
        for account in [DREAM,SUN,PURE]:
            self.assertEqual(5,sum(a['id']==account['id'] for _,_,a in result))

    def test_three_scarce_clips_shared_one_per_account(self):
        with patch.object(buffer,'publication_reasons',return_value=[]):
            result=buffer.plan_all({'created':[candidate(str(i)) for i in range(3)]},[],NOW)
        self.assertEqual({'dreamvoid','sunshine','purelife'},{a['id'] for _,_,a in result})

    def test_purelife_remote_post_blocks_other_accounts(self):
        c=candidate()
        post={'id':'pure-post','channelId':PURE['channel_id'],'assets':[{'source':c['video_url']}]}
        with patch.object(buffer,'publication_reasons',return_value=[]):
            self.assertFalse(buffer.plan_all({'created':[c]},[post],NOW))

    def test_exact_purelife_connection_and_handle_required(self):
        for change,allowed in [({},True),({'name':'wrong'},False),({'isDisconnected':True},False)]:
            row=dict(id=PURE['channel_id'],name=PURE['expected_handle'],service='tiktok',
                     isDisconnected=False,isLocked=False,isQueuePaused=False,**{})
            row.update(change)
            with patch.object(buffer,'request',side_effect=[{'account':{'organizations':[{'id':'org'}]}},{'channels':[row]}]):
                if allowed:self.assertEqual('org',buffer.verify_channel(PURE))
                else:
                    with self.assertRaises(RuntimeError):buffer.verify_channel(PURE)

    def test_shared_capacity_supports_three_targets(self):
        self.assertEqual(18,pipeline.SETTINGS['max_daily_renders'])
        self.assertEqual(558,pipeline.SETTINGS['max_monthly_renders'])
        self.assertEqual(3,pipeline.SETTINGS['max_renders_per_run'])
        self.assertEqual(6,pipeline.SETTINGS['max_attempts_per_run'])
