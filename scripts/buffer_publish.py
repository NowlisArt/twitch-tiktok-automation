"""Buffer GraphQL publisher: durable intent, exact channel gates and receipts."""
import argparse
import datetime as dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from zoneinfo import ZoneInfo
from distribute import eligible, unavailable, clip_keys
from quality import publication_reasons, timestamp
from storage import ROOT, STATE, write_json, checkpoint

CONFIG = json.loads((ROOT / 'config/publishing.json').read_text(encoding='utf-8'))
ACCOUNTS = CONFIG['accounts']
if not ACCOUNTS or len({a['channel_id'] for a in ACCOUNTS}) != len(ACCOUNTS) or len({a['id'] for a in ACCOUNTS}) != len(ACCOUNTS):
    raise ValueError('Publishing accounts must have unique channel IDs and names')
CHANNEL = ACCOUNTS[0]['channel_id']  # Legacy untagged receipts belong to Dream Void.
ZONE = ZoneInfo(CONFIG['timezone'])
POST_FIELDS = 'id channelId dueAt text status sentAt externalLink assets { source }'


def request(query, variables=None):
    key = os.getenv('BUFFER_API_KEY')
    if not key:
        raise RuntimeError('Missing GitHub secret BUFFER_API_KEY')
    req = urllib.request.Request('https://api.buffer.com',
        data=json.dumps({'query': query, 'variables': variables or {}}).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Buffer HTTP {exc.code}; inspect connection/quota; no mutation retry') from None
    if data.get('errors') or not isinstance(data.get('data'), dict):
        raise RuntimeError('Buffer GraphQL rejected request; no mutation retry; inspect API contract')
    return data['data']


def verify_channel(account=None):
    account = account or ACCOUNTS[0]
    response = request('query { account { organizations { id } } }')
    for org in response['account']['organizations']:
        channels = request('query($input:ChannelsInput!){ channels(input:$input){ id name service isDisconnected isLocked isQueuePaused } }',
                           {'input': {'organizationId': org['id']}})['channels']
        for channel in channels:
            if channel['id'] != account['channel_id']:
                continue
            if channel['name'].lower().lstrip('@') != account['expected_handle'] or channel['service'].lower() != 'tiktok':
                raise RuntimeError('Target channel ID/handle/service mismatch')
            if any(channel[k] for k in ('isDisconnected', 'isLocked', 'isQueuePaused')):
                raise RuntimeError(account['id'] + ' disconnected, locked or queue paused')
            print('BUFFER CHANNEL VERIFIED', channel['id'], channel['name'], channel['service'])
            return org['id']
    raise RuntimeError(account['id'] + ' target channel not accessible')


def contract_check():
    result = request('query { __type(name:"CreatePostInput") { inputFields { name } } __schema { mutationType { fields { name } } } }')
    fields = {f['name'] for f in result['__type']['inputFields']}
    mutations = {f['name'] for f in result['__schema']['mutationType']['fields']}
    if not {'channelId', 'text', 'assets', 'mode', 'schedulingType', 'dueAt'} <= fields or 'createPost' not in mutations:
        raise RuntimeError('Buffer API contract changed')
    print('BUFFER CONTRACT VERIFIED: CreatePostInput/createPost; no mutation executed')


def fetch_posts(org, account=None):
    account = account or ACCOUNTS[0]
    channel_id = account['channel_id']
    """All target-channel pages; an incomplete queue never opens extra slots."""
    posts, after, seen = [], None, set()
    for _ in range(100):
        result = request('query($input:PostsInput!,$after:String){posts(input:$input,first:100,after:$after){edges{node{' +
                         POST_FIELDS + '}} pageInfo{hasNextPage endCursor}}}',
                         {'input': {'organizationId': org, 'filter': {'channelIds': [channel_id]}}, 'after': after})['posts']
        posts.extend(e['node'] for e in result['edges'] if e['node']['channelId'] == channel_id)
        page = result['pageInfo']
        if not page['hasNextPage']:
            return posts
        after = page.get('endCursor')
        if not after or after in seen:
            raise RuntimeError('Incomplete Buffer pagination; publishing blocked')
        seen.add(after)
    raise RuntimeError('Buffer pagination budget exceeded; publishing blocked')


def media_sources(post):
    return {a.get('source') for a in post.get('assets', []) if a.get('source')}


def clip_channel(clip):
    if clip.get('buffer_channel_id'):
        return clip['buffer_channel_id']
    for account in ACCOUNTS:
        if clip.get('reserved_for') in (account['id'], account['expected_handle']):
            return account['channel_id']
    return CHANNEL


def reconcile(state, posts, now, account=None):
    account = account or ACCOUNTS[0]
    channel_id = account['channel_id']
    posts = [p for p in posts if p.get('channelId', CHANNEL) == channel_id]
    by_id = {p['id']: p for p in posts}
    for clip in state['created']:
        if not clip.get('buffer_post_id') and clip.get('status') != 'buffer_submission_pending':
            continue
        if clip_channel(clip) != channel_id:
            continue
        post = by_id.get(clip.get('buffer_post_id'))
        if not post and clip.get('status') == 'buffer_submission_pending':
            matches = [p for p in posts if clip.get('video_url') in media_sources(p)]
            if len(matches) == 1:
                post = matches[0]
                clip['buffer_post_id'] = post['id']
        if not post:
            print('BUFFER STATUS UNKNOWN; reservation retained:', clip.get('clip_id'))
            continue
        clip.update(buffer_channel_id=channel_id, buffer_handle=account['expected_handle'],
                    buffer_last_reported_status=post['status'], buffer_last_checked_at=now.isoformat(),
                    buffer_due_at=post.get('dueAt'))
        if post['status'] == 'sent':
            clip.update(status='buffer_reported_published', buffer_sent_at=post.get('sentAt'),
                        buffer_public_url=post.get('externalLink'))
        elif post['status'] == 'error':
            clip['status'] = 'buffer_reported_failed'
        else:
            clip['status'] = 'buffer_' + post['status']
        print('BUFFER RECEIPT', clip['clip_id'], post['id'], post['status'], post.get('externalLink') or '')


def slot(now, account=None):
    local = now.astimezone(ZONE)
    for days in range(2):
        for hour in (account or {}).get('posting_hours', CONFIG['posting_hours']):
            value = (local + dt.timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
            if local + dt.timedelta(minutes=15) < value <= local + dt.timedelta(hours=24):
                yield value


def reservations(state, posts, account=None):
    account = account or ACCOUNTS[0]
    channel_id = account['channel_id']
    rows = {p['id']: dict(p, dueAt=p.get('sentAt') or p.get('dueAt')) for p in posts
            if p.get('channelId', CHANNEL) == channel_id}
    for c in state['created']:
        if clip_channel(c) == channel_id and c.get('buffer_due_at') and unavailable(c):
            key = c.get('buffer_post_id') or 'intent:' + c.get('reservation_id', c['clip_id'])
            rows.setdefault(key, {'dueAt': c['buffer_due_at']})
    return list(rows.values())


def plan(state, posts, now, account=None, used_extra=None):
    account = account or ACCOUNTS[0]
    used, all_media = set(used_extra or ()), set()
    for c in state['created']:
        if unavailable(c):
            used.update(clip_keys(c))
    for post in posts:
        all_media.update(media_sources(post))
    reserved, result = reservations(state, posts, account), []
    for when in slot(now, account):
        dated = []
        for row in reserved:
            try:
                dated.append(timestamp(row['dueAt']).astimezone(ZONE))
            except (KeyError, ValueError, TypeError):
                continue
        if sum(t.date() == when.date() for t in dated) >= CONFIG['maximum_daily']:
            continue
        if any(abs((t - when).total_seconds()) < 1800 for t in dated):
            continue
        for clip in state['created']:
            if not eligible(clip, CONFIG['minimum_quality']) or unavailable(clip):
                continue
            if clip_keys(clip) & used or clip.get('video_url') in all_media:
                continue
            if publication_reasons(clip, when):
                continue
            result.append((clip, when))
            used.update(clip_keys(clip))
            reserved.append({'dueAt': when.isoformat()})
            break
    return result


def plan_all(state, posts, now):
    """Balance scarce clips across accounts, preserving global source exclusivity."""
    working, used, result = list(posts), set(), []
    while True:
        choices = []
        for index, account in enumerate(ACCOUNTS):
            proposals = plan(state, working, now, account, used)
            if not proposals:
                continue
            clip, when = proposals[0]
            dated = []
            for row in reservations(state, working, account):
                try:
                    dated.append(timestamp(row['dueAt']).astimezone(ZONE))
                except (KeyError, ValueError, TypeError):
                    continue
            count = sum(t.date() == when.date() for t in dated)
            last = max(dated, default=dt.datetime.min.replace(tzinfo=dt.timezone.utc))
            choices.append(((when.date(), count, last, when, index), clip, when, account))
        if not choices:
            return result
        _, clip, when, account = min(choices, key=lambda c: c[0])
        result.append((clip, when, account))
        used.update(clip_keys(clip))
        working.append({'id': 'planned:' + str(len(result)), 'channelId': account['channel_id'],
                        'dueAt': when.isoformat(), 'status': 'scheduled',
                        'assets': [{'source': clip.get('video_url')}]})


class MediaUnavailable(RuntimeError):
    """Temporary failure before any Buffer mutation; safe to try next run."""


def verify_media(clip):
    url = str(clip.get('video_url') or '')
    prefix = 'https://github.com/NowlisArt/twitch-tiktok-automation/releases/download/'
    if not url.startswith(prefix) or not url.endswith('.mp4'):
        raise RuntimeError('Video must use this repository public MP4 release')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as stream:
                digest, count = hashlib.sha256(), 0
                while chunk := stream.read(1024 * 1024):
                    count += len(chunk)
                    if count > 200 * 1024 * 1024:
                        raise RuntimeError('Public video exceeds transfer budget')
                    digest.update(chunk)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (404, 408, 429, 500, 502, 503, 504):
                raise
            if attempt == 3:
                raise MediaUnavailable('Public video temporarily unavailable; no post submitted') from exc
            print('MEDIA FETCH RETRY', attempt + 1, type(exc).__name__)
            time.sleep(10 * (attempt + 1))
    if digest.hexdigest() != clip.get('video_sha256'):
        raise RuntimeError('Public video hash differs from reviewed bytes')


def publish(state, posts, now, account=None, planned=None):
    account = account or ACCOUNTS[0]
    channel_id = account['channel_id']
    if planned is None:
        planned = plan(state, posts, now) if account == ACCOUNTS[0] else plan(state, posts, now, account)
    for clip, when in planned:
        verify_media(clip)
        clip.update(status='buffer_submission_pending', reserved_for=account['id'],
                    reservation_id=str(uuid.uuid4()), buffer_channel_id=channel_id,
                    buffer_handle=account['expected_handle'],
                    buffer_due_at=when.astimezone(dt.timezone.utc).isoformat())
        checkpoint(state)  # Remote commit BEFORE mutation. Cancellation retains the lock.
        query = 'mutation($input:CreatePostInput!){createPost(input:$input){... on PostActionSuccess{post{' + POST_FIELDS + '}} ... on MutationError{message}}}'
        payload = {'text': clip['caption'], 'channelId': channel_id, 'schedulingType': 'automatic',
                   'mode': 'customScheduled', 'dueAt': clip['buffer_due_at'],
                   'assets': [{'video': {'url': clip['video_url']}}]}
        result = request(query, {'input': payload})['createPost']
        post = result.get('post')
        if not post or not post.get('id'):
            raise RuntimeError('Submission unconfirmed; reservation retained; inspect queue before retry')
        clip.update(buffer_post_id=post['id'], status='buffer_scheduled')
        posts.append(post)
        reconcile(state, posts, now, account)
        checkpoint(state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--reconcile', action='store_true')
    args = parser.parse_args()
    state = json.loads(STATE.read_text(encoding='utf-8'))
    now = dt.datetime.now(dt.timezone.utc)
    # Verify BOTH exact accounts and fetch BOTH queues before any mutation.
    organizations = {a['id']: verify_channel(a) for a in ACCOUNTS}
    contract_check()
    posts = []
    for account in ACCOUNTS:
        posts.extend(fetch_posts(organizations[account['id']], account))
    for account in ACCOUNTS:
        reconcile(state, posts, now, account)
    write_json(STATE, state)
    proposed = plan_all(state, posts, now)
    print('BUFFER PLAN', json.dumps({'eligible_slots': len(proposed), 'target_daily_per_account': '3-5',
          'live_channel_posts': len(posts), 'confirmed_sent': sum(p['status'] == 'sent' for p in posts)}))
    if not args.preflight and not args.reconcile and os.getenv('ENABLE_BUFFER_POSTING') == 'true':
        for clip, when, account in proposed:
            try:
                publish(state, posts, now, account, planned=[(clip, when)])
                clip.pop('media_fetch_error', None)
            except MediaUnavailable:
                clip['media_fetch_error'] = {'at': now.isoformat(), 'reason': 'temporary_public_media_unavailable'}
                write_json(STATE, state)
                print('MEDIA UNAVAILABLE; NO SUBMISSION; CONTINUING', clip['clip_id'])
    report = {'checked_at': now.isoformat(), 'candidate_count': len(state['created']),
              'eligible_next_slots_before_run': len(proposed),
              'accounts': [{**a, 'target_minimum': CONFIG['minimum_target'],
                            'maximum_daily': CONFIG['maximum_daily'],
                            'planned_before_run': sum(target['id'] == a['id'] for _, _, target in proposed),
                            'confirmed_sent': sum(p['status'] == 'sent' for p in posts if p['channelId'] == a['channel_id']),
                            'posts': [{'id': p['id'], 'status': p['status'], 'dueAt': p.get('dueAt'),
                                       'sentAt': p.get('sentAt'), 'externalLink': p.get('externalLink')}
                                      for p in posts if p['channelId'] == a['channel_id']]}
                           for a in ACCOUNTS],
              'note': 'Only sent is provider-confirmed publication. scheduled is not a publication receipt.'}
    write_json(ROOT / 'rendered/buffer-report.json', report)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('## Dream Void and Sunshine\n\n```json\n' + json.dumps(report, ensure_ascii=False, indent=2) + '\n```\n')


if __name__ == '__main__':
    main()
