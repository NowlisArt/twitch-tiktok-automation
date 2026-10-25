"""Honest readiness summary, also usable without provider credentials."""
import datetime as dt
import json
import os
from collections import Counter
from quality import publication_reasons
from storage import ROOT, STATE
from buffer_publish import ACCOUNTS, clip_channel

state = json.loads(STATE.read_text(encoding='utf-8'))
now = dt.datetime.now(dt.timezone.utc)
counts = Counter(reason for clip in state['created'] for reason in publication_reasons(clip, now))
report = {'starter': 'GitHub Actions schedule/workflow_dispatch', 'target': '3–5/day per account if eligible',
          'accounts': [{'id': a['id'], 'handle': a['expected_handle'],
                        'buffer_post_ids': [c['buffer_post_id'] for c in state['created']
                                            if c.get('buffer_post_id') and clip_channel(c) == a['channel_id']],
                        'provider_confirmed_sent': [c['buffer_post_id'] for c in state['created']
                                            if c.get('buffer_last_reported_status') == 'sent'
                                            and clip_channel(c) == a['channel_id']]}
                       for a in ACCOUNTS],
          'candidates': len(state['created']), 'blocking_reasons': dict(counts),
          'buffer_post_ids': [c['buffer_post_id'] for c in state['created'] if c.get('buffer_post_id')],
          'buffer_provider_confirmed_sent': [c['buffer_post_id'] for c in state['created']
                                             if c.get('buffer_last_reported_status') == 'sent'],
          'warning': 'Prepared, approved, scheduled and sent are different states.'}
text = json.dumps(report, ensure_ascii=False, indent=2)
print(text)
if os.getenv('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write('\n## Readiness\n\n```json\n' + text + '\n```\n')
