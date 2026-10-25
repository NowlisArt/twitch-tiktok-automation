"""Publish exact reviewed artifacts only after current rights/QA evidence gates."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from pipeline import read_state, save_state, now_utc, release, verify_render_media
from quality import digest, publication_reasons, review_for, rights_for
from distribute import unavailable


def main():
    state = read_state()
    for clip in state['created']:
        if unavailable(clip) or clip.get('video_url') or not clip.get('qa_run_id'):
            continue
        now = now_utc()
        if publication_reasons(clip, now):
            continue
        folder = str(clip.get('qa_sample_folder', ''))
        run_id = str(clip['qa_run_id'])
        if not re.fullmatch(r'[a-z0-9-]{8,90}', folder) or not run_id.isdigit():
            raise ValueError('Invalid artifact identity')
        destination = Path('prepared') / run_id
        if not destination.exists():
            subprocess.run(['gh', 'run', 'download', run_id, '--name', 'twitch-video-qa',
                            '--dir', str(destination)], check=True, timeout=180)
        sample = destination / 'qa_samples' / folder
        video, cover, subs = sample / 'tiktok.mp4', sample / 'cover.jpg', sample / 'subs.ass'
        if digest(video) != clip['video_sha256'] or digest(subs) != clip['subtitle_sha256']:
            raise ValueError('Artifact differs from reviewed bytes')
        verify_render_media(video)
        Path('rendered').mkdir(exist_ok=True)
        # release() creates files in rendered; preserve original review hashes.
        review = review_for(clip)
        permission = rights_for(clip['streamer'], now)
        source = {'channel_login': clip['streamer'], 'id': clip['clip_id']}
        video_url, cover_url = release(source, video, cover, now)
        clip.update(video_url=video_url, cover_url=cover_url, status='approved_for_distribution',
                    rights_status=permission['status'], rights_evidence_id=permission['id'],
                    subtitle_verified=True, editorial_review_status='approved',
                    quality_score_verified=True, quality_score=review['quality_score'])
        save_state(state)
        print('REVIEWED RELEASE READY', clip['clip_id'])


if __name__ == '__main__':
    main()
