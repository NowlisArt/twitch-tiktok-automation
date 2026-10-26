import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_pipeline import candidate,NOW
import metricool_publish as m

class MetricoolTests(unittest.TestCase):
    def post(self,status='PENDING'):
        return {'id':123,'publicationDate':{'dateTime':'2026-10-25T14:00:00','timezone':'Europe/Berlin'},
                'providers':[{'network':'tiktok','status':status,'publicUrl':'https://www.tiktok.com/@novel.novel601/video/123'}],
                'media':['https://example/video.mp4']}

    def test_exact_brand_handle_required(self):
        good={'id':7451945,'userId':5794027,'tiktok':'novel.novel601','timezone':'Europe/Berlin'}
        for change,allowed in [({},True),({'id':1},False),({'tiktok':'wrong'},False),({'deleted':True},False)]:
            with patch.object(m,'request',return_value=[dict(good,**change)]):
                if allowed: m.verify_brand()
                else:
                    with self.assertRaises(RuntimeError): m.verify_brand()

    def test_receipt_distinguishes_scheduled_from_published(self):
        c=candidate(metricool_brand_id=7451945,metricool_post_id=123,reserved_for='novel')
        m.reconcile({'created':[c]},[self.post()],NOW)
        self.assertEqual('metricool_scheduled',c['status'])
        self.assertFalse(c.get('posted_to_tiktok',False))
        m.reconcile({'created':[c]},[self.post('PUBLISHED')],NOW)
        self.assertEqual('metricool_published',c['status'])
        self.assertTrue(c['metricool_public_url'])

    def test_unknown_submission_stays_locked(self):
        c=candidate(status='metricool_submission_pending',reserved_for='novel',metricool_brand_id=7451945)
        m.reconcile({'created':[c]},[],NOW)
        self.assertEqual('metricool_submission_pending',c['status'])

    def test_buffer_record_not_reconciled_as_metricool(self):
        c=candidate(buffer_post_id=123,reserved_for='dreamvoid')
        m.reconcile({'created':[c]},[self.post('PUBLISHED')],NOW)
        self.assertNotIn('metricool_post_id',c)

    def test_checkpoint_failure_prevents_creation(self):
        c=candidate()
        with patch.object(m,'verify_media'),patch.object(m,'checkpoint',side_effect=RuntimeError('push failed')),patch.object(m,'request') as request:
            with self.assertRaises(RuntimeError):m.publish({'created':[c]},[],c,NOW)
        request.assert_not_called()

    def test_timeout_preserves_intent_and_never_retries(self):
        c=candidate()
        def create(path,method='GET',**kw):
            self.assertEqual('metricool_submission_pending',c['status'])
            self.assertEqual('novel',c['reserved_for'])
            self.assertEqual('Europe/Berlin',kw['body']['publicationDate']['timezone'])
            self.assertTrue(kw['body']['autoPublish'])
            raise TimeoutError('uncertain')
        with patch.object(m,'verify_media'),patch.object(m,'checkpoint') as save,patch.object(m,'request',side_effect=create) as request:
            with self.assertRaises(TimeoutError):m.publish({'created':[c]},[],c,NOW)
        self.assertEqual(1,request.call_count)
        self.assertEqual(1,save.call_count)
        self.assertTrue(c['reservation_id'])

    def test_global_used_source_blocks_novel(self):
        used=candidate('same',buffer_post_id='old',reserved_for='dreamvoid')
        fresh=candidate('same')
        with patch.object(m.buffer,'publication_reasons',return_value=[]):
            self.assertEqual([],m.proposals({'created':[used,fresh]},[],NOW))

    def test_scarce_supply_caps_novel_priority(self):
        with patch.object(m.buffer,'publication_reasons',return_value=[]):
            result=m.proposals({'created':[candidate(str(i)) for i in range(10)]},[],NOW)
        self.assertEqual(1,sum(when.date()==NOW.astimezone(m.ZONE).date() for _,when in result))

    def test_unsafe_pagination_origin_rejected(self):
        with self.assertRaises(RuntimeError):m.page_path('https://evil.example/api/v2/scheduler/posts')

    def test_missing_secret_reports_blocked_without_call(self):
        with patch.dict(m.os.environ,{'METRICOOL_API_KEY':''}),patch.object(m,'request') as request,patch.object(m,'write_report') as report:
            m.main([])
        request.assert_not_called()
        self.assertEqual('blocked_missing_api_credential',report.call_args.args[0]['status'])

    def test_daily_cap_counts_existing_metricool_calendar_posts(self):
        posts=[dict(self.post(),id=i,publicationDate={'dateTime':f'2026-10-25T{10+i:02}:00:00','timezone':'Europe/Berlin'}) for i in range(5)]
        with patch.object(m.buffer,'publication_reasons',return_value=[]):
            result=m.proposals({'created':[candidate(str(i)) for i in range(10)]},posts,NOW)
        self.assertFalse(any(when.astimezone(m.ZONE).date()==NOW.astimezone(m.ZONE).date() for _,when in result))

    def test_preflight_with_credential_never_calls_publish(self):
        with patch.dict(m.os.environ,{'METRICOOL_API_KEY':'unit-test-placeholder','ENABLE_METRICOOL_POSTING':'true'}), \
             patch.object(m,'verify_brand'),patch.object(m,'fetch_posts',return_value=[]), \
             patch.object(m,'proposals',return_value=[(candidate(),NOW)]),patch.object(m,'write_json'), \
             patch.object(m,'write_report') as report,patch.object(m,'publish') as publish:
            m.main(['--preflight'])
        publish.assert_not_called()
        self.assertEqual('preflight_ok',report.call_args.args[0]['status'])
