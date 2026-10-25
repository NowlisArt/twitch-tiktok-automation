"""Evidence gates shared by promotion and publishing. No inferred approvals."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def timestamp(value):
    stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timezone is required')
    return stamp


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rights_for(streamer, when):
    revoked = ROOT / 'config/revoked_channels.txt'
    if revoked.exists():
        denied = {line.strip().lower() for line in revoked.read_text(encoding='utf-8').splitlines()
                  if line.strip() and not line.lstrip().startswith('#')}
        if str(streamer).lower() in denied:
            return None
    document = json.loads((ROOT / 'config/rights.json').read_text(encoding='utf-8'))
    for permission in document['permissions']:
        sources = permission.get('streamers', [permission.get('streamer', '')])
        if str(streamer).lower() not in [str(s).lower() for s in sources]:
            continue
        status = permission.get('status')
        if status not in ('verified_permission', 'user_attested_oral') or permission.get('revoked') is True:
            continue
        actor, date = ('verified_by', 'verified_at') if status == 'verified_permission' else ('attested_by', 'attested_at')
        if not all(permission.get(k) for k in ('id', 'evidence_reference', actor, date)):
            continue
        if not {'edit', 'subtitles', 'tiktok', 'public_hosting'}.issubset(permission.get('scope', [])):
            continue
        try:
            if timestamp(permission[date]) > when:
                continue
            if permission.get('expires_at') and timestamp(permission['expires_at']) <= when:
                continue
        except (ValueError, TypeError):
            continue
        return permission
    return None


def review_for(clip):
    reviews = json.loads((ROOT / 'config/reviews.json').read_text(encoding='utf-8'))['reviews']
    for review in reviews:
        if review.get('clip_id') != clip.get('clip_id'):
            continue
        if any(not clip.get(k) or review.get(k) != clip[k] for k in ('video_sha256', 'subtitle_sha256')):
            continue
        if not review.get('reviewer') or len(str(review.get('notes', ''))) < 20:
            continue
        try:
            if timestamp(review['reviewed_at']) > dt.datetime.now(dt.timezone.utc):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if not all(review.get(k) is True for k in ('subtitle_accuracy', 'readability', 'audio_video', 'context', 'rights_in_clip')):
            continue
        score = review.get('quality_score')
        if type(score) is int and 85 <= score <= 100:
            return review
    return None


def publication_reasons(clip, when):
    reasons = []
    if not clip.get('clip_id') or not clip.get('clip_slug'):
        reasons.append('missing Twitch identity')
    source = urlsplit(str(clip.get('source_url', '')))
    if source.scheme != 'https' or source.hostname not in ('clips.twitch.tv', 'www.twitch.tv', 'twitch.tv'):
        reasons.append('invalid Twitch source URL')
    try:
        if not 0 <= (when - timestamp(clip['original_created_at'])).total_seconds() <= 72 * 3600:
            reasons.append('source older than 72 hours at publication')
    except (KeyError, ValueError, TypeError):
        reasons.append('missing original timestamp')
    if type(clip.get('views_at_selection')) is not int or clip['views_at_selection'] < 800:
        reasons.append('missing verified source views')
    if not rights_for(clip.get('streamer'), when):
        reasons.append('permission evidence missing, expired or revoked')
    if not review_for(clip):
        reasons.append('exact video/subtitle review missing')
    if clip.get('technical_qa_passed') is not True:
        reasons.append('technical QA missing')
    return reasons
