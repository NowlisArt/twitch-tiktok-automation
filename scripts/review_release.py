"""Publish exact reviewed artifacts only after current rights/QA evidence gates."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from pipeline import read_state, save_state, now_utc, release, verify_render_media
from quality import digest, publication_reasons, review_for, rights_for, automatic_review_for
from distribute import unavailable


def artifact_sample(destination, folder):
    """Accept actual multi-path Actions archives and older flattened archives."""
    if not re.fullmatch(r'[a-z0-9-]{8,90}', str(folder)):
        raise ValueError('Invalid QA sample folder')
    matches = [p for p in (destination / 'rendered/qa_samples' / folder,
                            destination / 'qa_samples' / folder) if p.is_dir()]
    if len(matches) != 1:
        raise ValueError('Reviewed artifact folder missing or ambiguous')
    return matches[0]


def promote_one(clip):
    now = now_utc()
    if publication_reasons(clip, now):
        return False
    folder, run_id = str(clip.get('qa_sample_folder', '')), str(clip['qa_run_id'])
    if not re.fullmatch(r'[a-z0-9-]{8,90}', folder) or not run_id.isdigit():
        raise ValueError('Invalid artifact identity')
    sample = Path('rendered/qa_samples') / folder
    if not sample.is_dir():
        destination = Path('prepared') / run_id
        if not destination.exists():
            subprocess.run(['gh', 'run', 'download', run_id, '--name', 'twitch-video-qa',
                            '--dir', str(destination)], check=True, timeout=180)
        sample = artifact_sample(destination, folder)
    video, cover, subs = sample/'tiktok.mp4', sample/'cover.jpg', sample/'subs.ass'
    if digest(video) != clip['video_sha256'] or digest(subs) != clip['subtitle_sha256']:
        raise ValueError('Artifact differs from accepted bytes')
    verify_render_media(video)
    Path('rendered').mkdir(exist_ok=True)
    manual, machine = review_for(clip), automatic_review_for(clip)
    permission = rights_for(clip['streamer'], now)
    source = {'channel_login': clip['streamer'], 'id': clip['clip_id']}
    video_url, cover_url = release(source, video, cover, now)
    clip.update(video_url=video_url, cover_url=cover_url, status='approved_for_distribution',
                rights_status=permission['status'], rights_evidence_id=permission['id'],
                subtitle_verified=bool(manual),
                editorial_review_status='approved' if manual else 'automatic_checks_passed',
                quality_score_verified=bool(manual), quality_score=manual['quality_score'] if manual else None,
                approval_method='documented_review' if manual else 'automatic_machine_checks')
    clip.pop('release_error', None)
    print('RELEASE READY', clip['clip_id'], clip['approval_method'])
    return True


def main():
    state = read_state()
    for clip in state['created']:
        if unavailable(clip) or clip.get('video_url') or not clip.get('qa_run_id'):
            continue
        try:
            if promote_one(clip):
                save_state(state)
        except Exception as exc:
            # One broken/expired artifact must not block other usable clips or Buffer receipts.
            clip['release_error'] = type(exc).__name__
            save_state(state)
            print('RELEASE FAILED; CONTINUING WITH OTHER CLIPS', clip['clip_id'], type(exc).__name__)


if __name__ == '__main__':
    main()
