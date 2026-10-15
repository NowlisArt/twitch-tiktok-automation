#!/usr/bin/env python3
"""Promote a visually reviewed GitHub Actions QA artifact into a public MP4 release.

This script does not post to TikTok. ChatGPT/Metricool publication is a separate,
confirmed action once public reachability and scheduling constraints pass.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from pipeline import now_utc, read_state, save_state, twitch_slug, used_ids, iso, slug

APPROVAL = Path('config/approved_for_release.json')
ROOT = Path('prepared')
REPO = os.getenv('GITHUB_REPOSITORY', '')
UTC = dt.timezone.utc


def call(args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)


def main():
    if not APPROVAL.exists():
        print('No approved clip manifest; do not upload.')
        return
    request = json.loads(APPROVAL.read_text(encoding='utf-8'))
    decision = request.get('decision')
    if decision not in ('approved_after_audio_visual_review', 'approved_for_end_to_end_test'):
        raise ValueError('Explicit review or end-to-end test approval is required')
    notes = str(request.get('review_notes') or '').strip()
    if len(notes) < 35:
        raise ValueError('A substantive review note is required')
    if decision == 'approved_for_end_to_end_test' and not request.get('user_authorized_live_test'):
        raise ValueError('Public end-to-end test was not authorized by user')
    run_id = request.get('qa_run_id')
    channel_slug = request.get('qa_sample_folder')
    if type(run_id) is not int or not (1 <= run_id):
        raise ValueError('GitHub run id missing')
    if not isinstance(channel_slug, str) or not re.fullmatch(r'[a-z0-9-]{8,90}', channel_slug):
        raise ValueError('Invalid QA folder name')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', REPO):
        raise ValueError('Repository context missing')
    # Download EXACTLY the QA run's stored video. No re-rendering after approval.
    ROOT.mkdir(parents=True, exist_ok=True)
    call(['gh', 'run', 'download', str(run_id), '--repo', REPO,
          '--name', 'twitch-video-qa', '--dir', str(ROOT)], timeout=180)
    clip_dir = ROOT / 'qa_samples' / channel_slug
    movie = clip_dir / 'tiktok.mp4'
    cover = clip_dir / 'cover.jpg'
    manifest_path = clip_dir / 'test_manifest.json'
    if not all(p.is_file() for p in (movie, cover, manifest_path)):
        raise ValueError('Approved QA artifact folder missing video, cover or manifest')
    info = json.loads(manifest_path.read_text(encoding='utf-8'))
    url = info.get('original_clip_url')
    clip_slug = twitch_slug(url or '')
    if not clip_slug or clip_slug != request.get('original_clip_slug'):
        raise ValueError('Twitch source URL and approved clip slug do not match')
    ts = dt.datetime.fromisoformat(info['original_created_at'].replace('Z', '+00:00'))
    age = (now_utc() - ts).total_seconds() / 3600
    if not 0 <= age <= 72:
        raise ValueError('Source is older than 72 hours at promotion')
    if not isinstance(info.get('original_views_at_selection'), int) or info['original_views_at_selection'] < 800:
        raise ValueError('No verified Twitch view threshold')
    state = read_state()
    used, _ = used_ids(state)
    if clip_slug in used:
        raise ValueError('Previously processed, rejected or published clip')
    probe = call(['ffprobe','-v','error','-select_streams','v:0',
                  '-show_entries','stream=width,height','-of','csv=s=x:p=0',
                  str(movie)],capture_output=True,timeout=25).stdout.strip()
    duration = float(call(['ffprobe','-v','error','-show_entries','format=duration',
                           '-of','csv=p=0',str(movie)],capture_output=True,timeout=25).stdout)
    if probe != '1080x1920' or not 15 <= duration <= 60:
        raise ValueError('Wrong 9:16 video geometry or length')
    call(['ffmpeg','-v','error','-i',str(movie),'-f','null','-'],
         capture_output=True,timeout=180)
    stamp = now_utc()
    tag = f'tiktok-{stamp:%Y-%m}'
    basename = slug(info['streamer']+'-'+clip_slug,88)
    vid_name, cov_name = basename+'.mp4', basename+'-cover.jpg'
    out = ROOT / 'publish'
    out.mkdir(exist_ok=True)
    shutil.copyfile(movie,out/vid_name)
    shutil.copyfile(cover,out/cov_name)
    exists = subprocess.run(['gh','release','view',tag,'--repo',REPO],
                            capture_output=True,text=True).returncode == 0
    if not exists:
        call(['gh','release','create',tag,'--repo',REPO,
              '--title',f'QA-geprüfte Clips {stamp:%Y-%m}',
              '--notes','Nur nach dokumentierter Audio-/Video-Prüfung freigegebene MP4-Dateien.'])
    call(['gh','release','upload',tag,str(out/vid_name),str(out/cov_name),
          '--repo',REPO], timeout=180)
    video_url=f'https://github.com/{REPO}/releases/download/{tag}/{vid_name}'
    call(['curl','-f','-L','-I','--retry','3','--retry-delay','2',
          '--max-time','60',video_url],capture_output=True,timeout=85)
    state['created'].append({
        'clip_slug':clip_slug,'clip_id':clip_slug,'source_url':url,
        'original_created_at':info['original_created_at'],
        'views_at_selection':info['original_views_at_selection'],
        'streamer':info['streamer'],'created_at':iso(stamp),
        'video_url':video_url,'status':'qa_approved_metricool_pending',
        'quality_review_status':decision,
        'review_notes':notes,'subtitle_verified': decision == 'approved_after_audio_visual_review',
        'posted_to_tiktok':False, 'test_only': decision == 'approved_for_end_to_end_test',
        'rights_status':'user_asserted_not_independently_verified'
    })
    state['processed_ids'].append(clip_slug)
    save_state(state)
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as f:
            f.write(f'## QA-approved video hosted\n[Public MP4]({video_url})\n'
                    'Not yet posted to TikTok; schedule separately in Metricool.\n')
    print('PUBLIC QA-APPROVED MP4, NOT TIKTOK:',video_url,flush=True)


if __name__ == '__main__':
    main()
