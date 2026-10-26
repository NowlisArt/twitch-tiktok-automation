"""Optional Metricool publisher. Requires the owner's provider API access, never chat credentials."""
import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
import urllib.error
import uuid
from zoneinfo import ZoneInfo
import buffer_publish as buffer
from buffer_publish import verify_media, MediaUnavailable
from quality import timestamp
from storage import ROOT, STATE, write_json, checkpoint

CONFIG=json.loads((ROOT/'config/metricool.json').read_text(encoding='utf-8'))
ZONE=ZoneInfo(CONFIG['timezone'])
BASE='https://app.metricool.com/api'
ACCOUNT={'id':CONFIG['id'],'channel_id':'metricool:'+str(CONFIG['brand_id']),
         'expected_handle':CONFIG['expected_handle'],'posting_hours':CONFIG['posting_hours']}


def request(path,method='GET',params=None,body=None):
    if not path.startswith('/') or path.startswith('//'):
        raise RuntimeError('Invalid Metricool API path')
    key=os.getenv('METRICOOL_API_KEY')
    if not key: raise RuntimeError('METRICOOL_API_KEY secret missing')
    params=dict(params or {},userId=CONFIG['user_id'],blogId=CONFIG['brand_id'])
    req=urllib.request.Request(BASE+path+'?'+urllib.parse.urlencode(params),method=method,
        headers={'X-Mc-Auth':key,'Content-Type':'application/json'},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=45) as response: data=json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Metricool HTTP {exc.code}; verify API plan/credential; no create retry') from None
    if isinstance(data,dict) and (data.get('error') or data.get('errors')):
        raise RuntimeError('Metricool rejected request; no create retry')
    return data


def unwrap(data):
    return data.get('data') if isinstance(data,dict) and 'data' in data else data


def verify_brand():
    rows=unwrap(request('/admin/simpleProfiles'))
    if not isinstance(rows,list): raise RuntimeError('Unexpected brand response')
    for row in rows:
        if row.get('id')!=CONFIG['brand_id']: continue
        if (row.get('userId')!=CONFIG['user_id'] or row.get('deleted')
                or str(row.get('tiktok','')).lstrip('@').lower()!=CONFIG['expected_handle']
                or row.get('timezone')!=CONFIG['timezone']):
            raise RuntimeError('Metricool brand/handle/timezone mismatch')
        print('METRICOOL BRAND VERIFIED',CONFIG['brand_id'],CONFIG['expected_handle'])
        return
    raise RuntimeError('Novel Novel brand not accessible')


def page_path(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme and (parsed.scheme!='https' or parsed.netloc!='app.metricool.com'):
        raise RuntimeError('Untrusted pagination origin')
    path=parsed.path
    if path.startswith('/api/'): path=path[4:]
    if path!='/v2/scheduler/posts': raise RuntimeError('Unexpected pagination path')
    params=dict(urllib.parse.parse_qsl(parsed.query))
    for name,value in [('userId',CONFIG['user_id']),('blogId',CONFIG['brand_id'])]:
        if name in params and params[name]!=str(value): raise RuntimeError('Pagination identity mismatch')
    return path,params


def fetch_posts(now):
    params={'start':(now.astimezone(ZONE)-dt.timedelta(days=3)).strftime('%Y-%m-%dT00:00:00'),
            'end':(now.astimezone(ZONE)+dt.timedelta(days=2)).strftime('%Y-%m-%dT23:59:59'),
            'timezone':CONFIG['timezone']}
    path,rows,seen='/v2/scheduler/posts',[],set()
    for _ in range(50):
        data=request(path,params=params)
        page=unwrap(data)
        if not isinstance(page,list): raise RuntimeError('Unexpected calendar response')
        rows.extend(page)
        next_page=data.get('page',{}).get('next') if isinstance(data,dict) else None
        if not next_page: return rows
        if next_page in seen: raise RuntimeError('Repeated calendar page')
        seen.add(next_page)
        path,params=page_path(next_page)
    raise RuntimeError('Calendar pagination limit')


def post_time(post):
    stamp=post['publicationDate']
    return dt.datetime.fromisoformat(stamp['dateTime']).replace(tzinfo=ZoneInfo(stamp['timezone']))


def tiktok(post):
    return next((p for p in post.get('providers',[]) if p.get('network')=='tiktok'),{})


def reconcile(state,posts,now):
    by_id={str(p['id']):p for p in posts}
    for clip in state['created']:
        if clip.get('metricool_brand_id')!=CONFIG['brand_id']: continue
        post=by_id.get(str(clip.get('metricool_post_id')))
        if not post and clip.get('status')=='metricool_submission_pending':
            matches=[p for p in posts if clip.get('video_url') in p.get('media',[])]
            if len(matches)==1: post=matches[0]
        if not post: continue  # Unknown submissions remain locked.
        provider=tiktok(post)
        if not provider: continue
        status=provider.get('status','UNKNOWN')
        clip.update(metricool_post_id=post['id'],metricool_post_uuid=post.get('uuid'),
            metricool_last_reported_status=status,metricool_last_checked_at=now.isoformat())
        if status=='PUBLISHED':
            clip.update(status='metricool_published',metricool_public_url=provider.get('publicUrl'))
        elif status=='PENDING': clip['status']='metricool_scheduled'
        elif status=='ERROR': clip['status']='metricool_reported_failed'
        else: clip['status']='metricool_'+status.lower()
        print('METRICOOL RECEIPT',post['id'],status,provider.get('publicUrl') or '')


def proposals(state,posts,now):
    normalized=[]
    for post in posts:
        if tiktok(post):
            normalized.append({'id':str(post['id']),'channelId':ACCOUNT['channel_id'],
                'dueAt':post_time(post).isoformat(),'assets':[{'source':url} for url in post.get('media',[])]})
    known={p['id'] for p in normalized}
    for c in state['created']:
        if c.get('metricool_brand_id')==CONFIG['brand_id'] and c.get('metricool_due_at'):
            key=str(c.get('metricool_post_id') or c.get('reservation_id'))
            if key not in known:
                normalized.append({'id':key,'channelId':ACCOUNT['channel_id'],'dueAt':c['metricool_due_at'],'assets':[]})
    result=[]
    for clip,when in buffer.plan(state,normalized,now,ACCOUNT):
        date=when.astimezone(ZONE).date()
        other_counts=[sum(bool(c.get('buffer_due_at')) and timestamp(c['buffer_due_at']).astimezone(ZONE).date()==date
            for c in state['created'] if c.get('reserved_for')==account['id']) for account in buffer.ACCOUNTS]
        limit=min(CONFIG['maximum_daily'],min(other_counts,default=0)+1)
        current=sum(timestamp(p['dueAt']).astimezone(ZONE).date()==date for p in normalized)
        if current>=limit: continue
        result.append((clip,when))
        normalized.append({'id':'plan:'+clip['clip_id'],'channelId':ACCOUNT['channel_id'],'dueAt':when.isoformat()})
    return result


def publish(state,posts,clip,when):
    verify_media(clip)
    clip.update(status='metricool_submission_pending',reserved_for=CONFIG['id'],
        reservation_id=str(uuid.uuid4()),metricool_brand_id=CONFIG['brand_id'],
        metricool_handle=CONFIG['expected_handle'],metricool_due_at=when.isoformat())
    checkpoint(state)  # Must complete remotely BEFORE the create request.
    payload={'publicationDate':{'dateTime':when.astimezone(ZONE).strftime('%Y-%m-%dT%H:%M:%S'),
        'timezone':CONFIG['timezone']},'text':clip['caption'],'providers':[{'network':'tiktok'}],
        'media':[clip['video_url']],'autoPublish':True,'saveExternalMediaFiles':True,'draft':False,
        'tiktokData':{'privacyOption':'PUBLIC_TO_EVERYONE'}}
    post=unwrap(request('/v2/scheduler/posts',method='POST',body=payload))
    if not isinstance(post,dict) or not post.get('id'):
        raise RuntimeError('Unconfirmed Metricool submission; reservation retained')
    clip.update(metricool_post_id=post['id'],metricool_post_uuid=post.get('uuid'),status='metricool_submission_confirmed')
    posts.append(post)
    reconcile(state,posts,dt.datetime.now(dt.timezone.utc))
    checkpoint(state)


def write_report(report):
    write_json(ROOT/'rendered/metricool-report.json',report)
    print('METRICOOL STATUS',json.dumps(report,ensure_ascii=False))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as stream:
            stream.write('\n## Novel Novel / Metricool\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args(argv)
    if not os.getenv('METRICOOL_API_KEY'):
        write_report({'account':CONFIG['expected_handle'],'status':'blocked_missing_api_credential',
            'required':'Provider API access (Advanced/Custom) and GitHub secret METRICOOL_API_KEY',
            'new_submissions':0})
        return
    try:
        verify_brand()
        now=dt.datetime.now(dt.timezone.utc)
        state=json.loads(STATE.read_text(encoding='utf-8'))
        posts=fetch_posts(now)
        # Exact receipts outside the calendar window are fetched individually.
        known={str(p['id']) for p in posts}
        for c in state['created']:
            if c.get('metricool_brand_id')==CONFIG['brand_id'] and c.get('metricool_post_id') and str(c['metricool_post_id']) not in known:
                posts.append(unwrap(request('/v2/scheduler/posts/'+str(int(c['metricool_post_id'])))))
        reconcile(state,posts,now)
        write_json(STATE,state)
        planned=proposals(state,posts,now)
        submitted=0
        if not args.preflight and os.getenv('ENABLE_METRICOOL_POSTING')=='true':
            for clip,when in planned:
                try: publish(state,posts,clip,when)
                except MediaUnavailable:
                    print('METRICOOL MEDIA NOT READY; NEXT RUN',clip['clip_id'])
                    continue
                submitted+=1
        write_report({'account':CONFIG['expected_handle'],'status':'preflight_ok' if args.preflight else 'checked',
            'eligible_slots':len(planned),'new_submissions':submitted,
            'posts':[{'id':p['id'],'publicationDate':p.get('publicationDate'),'provider':tiktok(p)} for p in posts if tiktok(p)],
            'note':'Only provider status PUBLISHED is a publication receipt.'})
    except Exception as exc:
        write_report({'account':CONFIG['expected_handle'],'status':'error','error_type':type(exc).__name__,
            'note':'Inspect API access/connection; ambiguous submissions remain locked. No create retry.'})
        raise


if __name__=='__main__': main()
