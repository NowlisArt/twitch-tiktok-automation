#!/usr/bin/env python3
"""Prepare recent Twitch clips in GitHub Releases (never post to TikTok directly)."""
import calendar
import concurrent.futures
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import textwrap
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

UTC = dt.timezone.utc
STATE = Path('state/auto20.json')
OUT = Path('rendered')
STREAMERS = '''eliasn97 zarbex papaplatte trymacs canerkrd krokoboss xrohat montanablack88 gamerbrother kubafps bonjwa xthesolutiontv handofblood noway4u_sir metashi12 gronkhtv gronkh tolkin gtasty orangemorange schradin dhalucard shlorox mertabimula rumathra elotrix bastighg maxim dracon staiy spontent marli onlyjson naguura phunkroyal niklaswilson pietsmiet scurrows h0llylp rezo letshugotv edopeh amar sterzik repaz gtimetv mckytv rezonfn fregepaul coachlim'''.split()
RANK = {name: idx + 1 for idx, name in enumerate(STREAMERS)}
# Permanent bans: BastiGHG and Trymacs already used on TikTok.
# Previous QA sample rejected for weak narrative. Never recycle it.
EXCLUDE_IDS = {
    # Already rejected QA samples:
    '1885635439', 'PopularAgreeableBobaBatChest-T3Ga_Bm2CiWY5vII',
    '1971178535', 'JazzyRoughDadMcaT-0BGiWmmWGrinz4ZP',
    '1586086735', 'DiligentSarcasticArugulaKevinTurtle-gbC316ajn04-BalO',
    # Clips used/scheduled in the friend's original example: avoid cross-account copying.
    '1497602893', 'PeppyBloodyTeaRlyTho-BUSJgy71xak5-60U',
    '2169900339', 'CreativeSpeedyMetalPipeHype-WuzCUT11-Pk1F9WY',
    '3570577492', 'AltruisticVenomousVelociraptorSpicyBoy-ECiYgUQC2M1vchxM',
    'GrossTubularAntelopeWow-1KWH2cn3DcuhqWSe'
}
KEYWORDS = ('witz', 'lach', 'rage', 'fail', 'wtf', 'omg', 'unfassbar', 'ausrast', 'schrei', 'haha', 'reaction', 'peinlich', 'lustig', 'unerwart')


def run(command, check=True, **kwargs):
    return subprocess.run(command, check=check, text=True, **kwargs)


def iso(value):
    return value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def now_utc():
    return dt.datetime.now(UTC)


def slug(value, limit=92):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', value)).strip('-')[:limit] or 'clip'


def twitch_slug(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        return None
    if parsed.hostname == 'clips.twitch.tv':
        match = re.fullmatch(r'/([^/]+)/?', parsed.path)
    elif parsed.hostname in ('twitch.tv', 'www.twitch.tv'):
        match = re.fullmatch(r'/[^/]+/clip/([^/]+)/?', parsed.path)
    else:
        return None
    return match.group(1) if match else None


def read_state():
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))
    else:
        state = {'version': 2, 'created': [], 'processed_ids': []}
    state.setdefault('created', [])
    state.setdefault('processed_ids', [])
    state.setdefault('failed_attempts', {})
    return state


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def scheduled_slot(now):
    days = calendar.monthrange(now.year, now.month)[1]
    return math.floor(20 * now.day / days) > math.floor(20 * (now.day - 1) / days)


def can_prepare(state, now, event='schedule'):
    """Production buffer: max 60 prepared / month, max 3 / day.

    GitHub production is NOT the separate Metricool 20-post monthly limit.
    More production candidates allow genuine replacement when clips fail review.
    """
    monthly = [rec for rec in state['created']
               if rec.get('created_at', '').startswith(now.strftime('%Y-%m'))]
    if len(monthly) >= 60:
        return False, 'GitHub-Pufferlimit von 60 Produktionen in diesem Monat erreicht'
    if sum(rec.get('created_at', '').startswith(now.strftime('%Y-%m-%d'))
           for rec in monthly) >= 3:
        return False, 'Heute bereits drei Clip-Kandidaten erstellt'
    # Continuous hourly discovery/production. Keep the per-day and per-month caps.
    return True, 'OK'


def authorized_channels():
    source = Path('config/approved_channels.txt')
    if not source.exists():
        return []
    approved = {line.strip().lower() for line in source.read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')}
    # A stable 50-channel seed list; it is not a live TwitchTracker ranking.
    return [channel for channel in STREAMERS if channel in approved]


def twitch_api_candidates(range_code='24hr', channels=None):
    """Official Helix discovery; metadata must come from Twitch, not guessed."""
    import urllib.request
    import urllib.parse
    import urllib.error
    channels = channels if channels is not None else authorized_channels()
    client_id = os.getenv('TWITCH_CLIENT_ID', '').strip()
    client_secret = os.getenv('TWITCH_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret:
        raise RuntimeError('TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET missing')
    form = urllib.parse.urlencode({
        'client_id': client_id, 'client_secret': client_secret,
        'grant_type': 'client_credentials'}).encode()
    request = urllib.request.Request(
        'https://id.twitch.tv/oauth2/token', data=form, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            token = json.load(response)['access_token']
    except urllib.error.HTTPError as exc:
        # Report only Twitch's documented error classification, never raw
        # response bodies or request parameters containing credentials.
        safe_reason = 'unknown'
        try:
            body = json.loads(exc.read(4096))
            reason = str(body.get('message', '')).lower()
            if 'invalid client' in reason or 'client id' in reason:
                safe_reason = 'invalid_client_id'
            elif 'secret' in reason:
                safe_reason = 'invalid_client_secret'
            elif 'grant' in reason:
                safe_reason = 'invalid_grant'
            elif 'missing' in reason:
                safe_reason = 'missing_parameter'
        except (ValueError, UnicodeDecodeError):
            pass
        raise RuntimeError(
            f'Twitch OAuth rejected app credentials (HTTP {exc.code}; reason={safe_reason}). '
            'Verify GitHub secret values match the same Twitch developer app.'
        ) from None
    headers = {'Client-Id': client_id, 'Authorization': 'Bearer ' + token}
    def get(path, params):
        url = 'https://api.twitch.tv/helix/' + path + '?' + urllib.parse.urlencode(params, doseq=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as response:
            return json.load(response)
    users = get('users', [('login', ch) for ch in channels]).get('data', [])
    logins = {u['id']: u['login'].lower() for u in users
              if u.get('login', '').lower() in channels}
    now = now_utc()
    # '7d' is a fallback discovery source, but eligibility is always <=72 hours.
    hours = 24 if range_code == '24hr' else 72
    start = iso(now - dt.timedelta(hours=hours))
    end = iso(now)
    found = []
    def clips_for_user(item):
        broadcaster_id, login = item
        result = []
        cursor = None
        for _ in range(3):
            params = {'broadcaster_id': broadcaster_id, 'started_at': start,
                      'ended_at': end, 'first': 100}
            if cursor:
                params['after'] = cursor
            response = get('clips', params)
            result.extend((login, clip) for clip in response.get('data', []))
            cursor = response.get('pagination', {}).get('cursor')
            if not cursor:
                break
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for batch in pool.map(clips_for_user, logins.items()):
            found.extend(batch)
    print('TWITCH HELIX DISCOVERY', range_code, 'approved', len(channels),
          'resolved', len(logins), 'clips', len(found), flush=True)
    return found


def helix_verified(phase, now, used, used_urls, failed, channels):
    """Helix is authoritative for source views, timestamps, duration and broadcaster."""
    results = []
    reject_counts = {}
    def rejected(reason):
        reject_counts[reason] = reject_counts.get(reason, 0) + 1
    for channel, info in twitch_api_candidates(phase, channels):
        try:
            clip_id = str(info['id'])
            url = str(info['url'])
            clip_slug = twitch_slug(url)
            if not clip_slug or clip_id in used or clip_slug in used or url in used_urls or clip_slug in failed:
                rejected('invalid_url_or_duplicate')
                continue
            created = dt.datetime.fromisoformat(info['created_at'].replace('Z', '+00:00'))
            age = (now - created).total_seconds() / 3600
            views = info['view_count']
            duration = info['duration']
            title = str(info.get('title') or '').strip()
            if not isinstance(views, int) or isinstance(views, bool):
                rejected('missing_views')
                continue
            if not isinstance(duration, (int, float)) or isinstance(duration, bool):
                rejected('missing_duration')
                continue
            if not 0 <= age <= 72:
                rejected('age_outside_72h')
                continue
            if not 15 <= duration <= 60:
                rejected('duration_outside_15_60s')
                continue
            if views < int(os.getenv('MIN_VIEWS', '800')):
                rejected('views_below_minimum')
                continue
            if len(title) < 5 or channel not in RANK:
                rejected('title_or_channel')
                continue
            clip = {'id': clip_id, 'clip_slug': clip_slug, 'url': url,
                    'channel_login': channel, 'rank': RANK[channel],
                    'title': title, 'view_count': views, 'duration': float(duration),
                    'original_created_at': iso(created), 'age_hours': age}
            if not (age <= 48 or very_strong(clip)):
                rejected('older_without_strong_metrics')
            elif not worth_testing(clip):
                rejected('velocity_or_sponsor_filter')
            else:
                results.append(clip)
        except (KeyError, ValueError, TypeError) as exc:
            rejected('invalid_metadata')
            print('WARN invalid Helix clip metadata', repr(exc)[:100], file=sys.stderr)
    results.sort(key=selection_rank)
    print('HELIX FILTER COUNTS', json.dumps(reject_counts, sort_keys=True), flush=True)
    print('HELIX VERIFIED', phase, len(results), flush=True)
    return results


def channel_urls(channel, range_code='24hr'):
    """Discover fresh URLs first; failed listings do not abort other channels."""
    source = f'https://www.twitch.tv/{channel}/clips?filter=clips&range={range_code}'
    try:
        proc = run(['yt-dlp', '--no-warnings', '--flat-playlist',
                    '--playlist-end', '30', '--dump-single-json', source],
                   capture_output=True, timeout=65)
        data = json.loads(proc.stdout)
        links = []
        for item in data.get('entries') or []:
            if not isinstance(item, dict):
                continue
            url = item.get('webpage_url') or item.get('url') or ''
            if isinstance(url, str) and twitch_slug(url):
                links.append((channel, url))
        return list(dict.fromkeys(links))[:(20 if range_code == '24hr' else 35)]
    except Exception as exc:
        print('WARN listing', channel, range_code, repr(exc)[:150], file=sys.stderr, flush=True)
        return []


def fetch_candidates(range_code='24hr', channels=None):
    channels = channels if channels is not None else authorized_channels()
    if not channels:
        print('SKIP: no authorized channels configured', flush=True)
        return []
    all_links = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for links in pool.map(lambda ch: channel_urls(ch, range_code), channels):
            all_links.extend(links)
    unique = {twitch_slug(url): (channel, url) for channel, url in all_links}
    print('DISCOVERY', range_code, 'channels', len(channels), 'links', len(unique), flush=True)
    return list(unique.values())

def rejected_clips():
    """Human QA rejections: block IDs and slugs before future searches/renders."""
    path = Path('config/rejected_clips.txt')
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')}


def used_ids(state):
    used = set(EXCLUDE_IDS) | rejected_clips() | set(map(str, state['processed_ids']))
    used_urls = set()
    for rec in state['created']:
        used.add(str(rec.get('clip_id', '')))
        used.add(str(rec.get('clip_slug', '')))
        url = rec.get('source_url', '')
        used_urls.add(url)
        if twitch_slug(url):
            used.add(twitch_slug(url))
    return used, used_urls


def inspect_original(channel, link, now, min_views=800):
    """Full original Twitch extraction; queue created_at is NEVER evidence of age."""
    try:
        result = run(['yt-dlp', '--no-warnings', '--no-playlist', '--skip-download', '--dump-single-json', link], capture_output=True, timeout=45)
        info = json.loads(result.stdout)
        if os.getenv('DIAG_SOURCE_METADATA') == 'true':
            print('DIAGNOSTIC ORIGINAL META', json.dumps({
                'url': link, 'id': info.get('id'),
                'extractor_key': info.get('extractor_key'),
                'view_count': info.get('view_count'),
                'duration': info.get('duration'),
                'timestamp': info.get('timestamp'),
                'upload_date': info.get('upload_date'),
                'release_timestamp': info.get('release_timestamp'),
                'webpage_url': info.get('webpage_url'),
                'title': info.get('title')
            }, ensure_ascii=False), flush=True)
        clip_url = info.get('webpage_url') or link
        current_slug = twitch_slug(clip_url) or twitch_slug(link)
        source_id = str(info.get('id') or current_slug or '')
        views = info.get('view_count')
        duration = info.get('duration')
        timestamp = info.get('timestamp')
        extractor = str(info.get('extractor_key') or info.get('extractor') or '').lower()
        # Only Twitch clip metadata can validate this original creation timestamp.
        if 'twitch' not in extractor or not current_slug:
            return None
        if isinstance(timestamp, bool) or not isinstance(timestamp, (float, int)):
            return None
        if isinstance(views, bool) or not isinstance(views, int):
            return None
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return None
        age_hours = (now - dt.datetime.fromtimestamp(timestamp, UTC)).total_seconds() / 3600
        if not 0 <= age_hours <= 72 or not 15 <= duration <= 60 or views < min_views:
            return None
        title = str(info.get('title') or '').strip()
        if len(title) < 5:
            return None
        return {'id': source_id, 'clip_slug': current_slug, 'url': link,
                'channel_login': channel, 'rank': RANK[channel], 'title': title,
                'view_count': views, 'duration': float(duration),
                'original_created_at': iso(dt.datetime.fromtimestamp(timestamp, UTC)),
                'age_hours': age_hours}
    except Exception as exc:
        print('WARN clip metadata', link, repr(exc)[:130], file=sys.stderr)
        return None


def score(clip):
    speed = clip['view_count'] / max(2, clip['age_hours'])
    matches = sum(key in clip['title'].lower() for key in KEYWORDS)
    return 2.3 * math.log1p(clip['view_count']) + 2.4 * math.log1p(speed) + min(matches, 3) * .8 + .02 * (51 - clip['rank']) - abs(clip['duration'] - 28) / 50


def very_strong(clip):
    """Allow 48-72-hour clips only with convincing metrics."""
    return clip['view_count'] >= 8000 and clip['view_count'] / max(1, clip['age_hours']) >= 150


def worth_testing(clip):
    """Cheap discovery gate, not an assessment of whether the moment is funny.

    Keyword and high velocity requirements used to eliminate clips whose
    metadata was valid (800+ views), even before inspecting actual content.
    Quality must be checked from the video, not guessed from its title.
    """
    title = clip['title'].lower()
    risky_context = any(keyword in title for keyword in (
        'partner +', 'sponsor', 'vertrags', 'werbung',
        'sponsored', 'advert'))
    velocity = clip['view_count'] / max(1.0, clip['age_hours'])
    return (
        not risky_context and clip['view_count'] >= 800
        and ((clip['age_hours'] <= 48 and velocity >= 15)
             or (48 < clip['age_hours'] <= 72 and very_strong(clip)))
    )


def selection_rank(clip):
    """Prefer clips with verified high views across the allowed time window."""
    age, views = clip['age_hours'], clip['view_count']
    if views >= 5000 and age <= 48:
        tier = 0
    elif views >= 3000 and age <= 48:
        tier = 1
    elif views >= 1500 and age <= 24:
        tier = 2
    elif age <= 24:
        tier = 3
    elif age <= 48:
        tier = 4
    else:
        tier = 5
    return (tier, -score(clip), -views, age)


def headline(clip):
    title = re.sub(r'[\r\n\x00-\x1f]+', ' ', clip['title'])
    title = re.sub(r'[#@][\w]+', '', title)
    title = re.sub(r'\s+', ' ', title).strip(' -.,?!')
    # Never insert automatic creator-attribution or source-link text.
    title = re.sub(r'(?i)\bclip\s+von\s+\S+|\bquelle\s*:\s*\S+', '', title).strip()
    if len(title) < 8:
        title = 'DIESER MOMENT'
    return (title[:40].rstrip(' -.,:') + '…' if len(title) > 41 else title).upper()


def caption(clip):
    name = slug(clip['channel_login'], 24).replace('-', '')
    title = re.sub(r'(?i)\bclip\s+von\s+\S+|\bquelle\s*:\s*\S+', '',
                   clip['title']).strip(' -:')[:85]
    if len(title) < 5:
        title = 'Dieser Moment war unerwartet'
    return f'{title} 😂\n#{name} #twitchde #streamclips'


def probe(path, size=False):
    args = (['-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0'] if size else ['-show_entries', 'format=duration', '-of', 'csv=p=0'])
    proc = run(['ffprobe', '-v', 'error', *args, str(path)], capture_output=True)
    return proc.stdout.strip() if size else float(proc.stdout.strip())


def verify_render_media(path):
    """Fail closed on missing audio, silent renders, and nearly all-black output.

    These checks do not establish subtitle accuracy or editorial quality.
    """
    streams = json.loads(run([
        'ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_type,width,height', '-of', 'json', str(path)],
        capture_output=True, timeout=30).stdout).get('streams', [])
    video = [s for s in streams if s.get('codec_type') == 'video']
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if len(video) != 1 or not audio:
        raise ValueError('Render must contain one video stream and an audio track')
    if (video[0].get('width'), video[0].get('height')) != (1080, 1920):
        raise ValueError('Render must be 1080x1920')
    analysis = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
                    '-vn', '-af', 'volumedetect', '-f', 'null', '-'],
                   capture_output=True, timeout=90, check=False)
    if analysis.returncode != 0:
        raise ValueError('Audio decode/volume analysis failed')
    match = re.search(r'mean_volume:\s*(-?[\d.]+) dB', analysis.stderr)
    if not match or float(match.group(1)) < -48:
        raise ValueError('Audio missing or effectively silent')
    return True


def download(clip):
    OUT.mkdir(exist_ok=True)
    for path in OUT.glob('source.*'):
        path.unlink()
    run(['yt-dlp', '--no-playlist', '--retries', '3', '--merge-output-format', 'mp4', '-o', str(OUT / 'source.%(ext)s'), clip['url']], timeout=120)
    files = [p for p in OUT.glob('source.*') if p.suffix.lower() in ('.mp4', '.mkv', '.webm')]
    if not files:
        raise ValueError('Kein Clip heruntergeladen')
    return files[0]



def transcribe(path):
    """Transcribe real German audio; reject low-confidence / nonsensical outputs."""
    from faster_whisper import WhisperModel
    model_name = os.getenv('ASR_MODEL', 'medium')
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=4)
    print('ASR MODEL', model_name, flush=True)
    segments, _ = model.transcribe(
        str(path), language='de', beam_size=5, word_timestamps=True,
        condition_on_previous_text=False, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=450))
    utterances = list(segments)
    full_text = ' '.join(seg.text for seg in utterances).lower()
    if re.search(r'scheidensaft|muttersaft|inzest|kinderporn|vergewaltig|nekr[oó]phil', full_text):
        raise ValueError('Potentially unsuitable sexual/graphic clip; try another')
    reliable = [seg for seg in utterances
                if seg.avg_logprob is not None and seg.avg_logprob > -0.95
                and (seg.no_speech_prob is None or seg.no_speech_prob < 0.75)]
    if not reliable:
        raise ValueError('No reliable spoken content for subtitles; try another clip')
    words = [(float(word.start), float(word.end), word.word.strip())
             for segment in reliable for word in (segment.words or [])
             if word.word and word.word.strip()]
    if len(words) < 8 or len(' '.join(w[2] for w in words)) < 45:
        raise ValueError('Insufficient reliable speech; try another clip')
    quality = sum(seg.avg_logprob for seg in reliable)/len(reliable)
    print('ASR CONFIDENCE', round(quality,3), 'words', len(words), flush=True)
    return words

def pick_window(duration, words):
    """Trim at speech/pause boundaries and prefer complete endings, not random seconds."""
    if not words:
        raise ValueError('Cannot cut without speech timing')
    if duration <= 20:
        return 0.0, round(duration, 2)
    start_candidates = {0.0}
    end_candidates = {round(duration, 2)}
    for i, (a, b, word) in enumerate(words):
        if i == 0 or a - words[i-1][1] >= 0.60 or re.search(r'[.!?…]$', words[i-1][2]):
            start_candidates.add(round(max(0.0, a - 0.35), 2))
        if i == len(words)-1 or words[i+1][0] - b >= 0.65 or re.search(r'[.!?…]$', word):
            end_candidates.add(round(min(duration, b + 0.35), 2))
    best = None
    target = min(32.0, duration - 0.4)
    for start in sorted(start_candidates):
        for end in sorted(end_candidates):
            length = end - start
            if not (15 <= length <= min(42, duration)):
                continue
            selected = [w for w in words if w[0] >= start - 0.1 and w[1] <= end + 0.1]
            if len(selected) < 7:
                continue
            first, last = selected[0], selected[-1]
            ending_complete = bool(re.search(r'[.!?…]$', last[2])) or (
                end < duration - 0.7 and not any(
                    0 < w[0] - last[1] < 0.5 for w in words if w[0] > last[1]))
            ending_incomplete = last[1] >= end - 0.13 and not re.search(r'[.!?…]$', last[2])
            title_terms = ('haha', 'lach', 'wtf', 'krass', 'nein', 'what', 'nicht', 'wow', 'lol')
            moment = sum(any(k in w[2].lower() for k in title_terms) for w in selected)
            density = len(selected) / max(length, 1)
            score_value = density * 6 + min(moment, 3) * 0.8 + 5 * ending_complete
            score_value -= 6 * ending_incomplete
            score_value -= abs(length - target) * 0.13
            if start == 0:
                score_value += 0.2
            if best is None or score_value > best[0]:
                best = (score_value, start, length)
    if best is None:
        raise ValueError('No coherent 15-42s speech window; try next clip')
    return round(best[1], 2), round(best[2], 2)

def ass_time(seconds):
    ticks = int(max(0, seconds) * 100)
    return f'{ticks // 360000}:{(ticks // 6000) % 60:02}:{(ticks // 100) % 60:02}.{ticks % 100:02}'


def write_subs(words, start, length, path):
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,DejaVu Sans,61,&H00FFFFFF,&H00FFFFFF,&H00000000,&H75000000,-1,0,0,0,100,100,0,0,1,4,1,2,65,65,310,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    selected = [(max(0, a-start), min(length, b-start), w) for a, b, w in words
                if a >= start and b <= start+length and b > a and w.strip()]
    groups, group = [], []
    for item in selected:
        tentative = ' '.join(x[2] for x in group + [item])
        if group and (len(tentative) > 31 or len(group) >= 4 or item[0] - group[-1][1] > .5):
            groups.append(group)
            group = []
        group.append(item)
        if re.search(r'[.!?…]$', item[2]):
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    cues = []
    for group in groups:
        a, b = group[0][0], group[-1][1]
        label = ' '.join(x[2] for x in group).upper()
        label = label.replace('\\', '').replace('{', '(').replace('}', ')').replace('\n', ' ').strip()
        if label:
            cues.append((a, b, label))
    events = []
    for index, (a, b, label) in enumerate(cues):
        # Never render two text cards at once: cap each card before the next begins.
        next_start = cues[index+1][0] if index+1 < len(cues) else length
        end = min(length, max(a+0.25, b+0.08), next_start-0.02)
        if end <= a+0.05:
            continue
        events.append(
            f'Dialogue: 0,{ass_time(a)},{ass_time(end)},TikTok,,0,0,0,,{label}')
    path.write_text(header + '\n'.join(events) + '\n', encoding='utf-8')
    return len(events) >= 3

def find_face_focus(source, duration):
    """Best-effort reaction camera framing; leave original overview visible below."""
    try:
        import cv2
        video = cv2.VideoCapture(str(source))
        if not video.isOpened():
            return None
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = []
        for fraction in (0.2, 0.45, 0.7):
            video.set(cv2.CAP_PROP_POS_MSEC, max(0, duration*fraction*1000))
            ok, frame = video.read()
            if not ok:
                continue
            small_width = min(width, 960)
            factor = small_width/width
            small = cv2.resize(frame, (small_width, int(height*factor)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            found = cascade.detectMultiScale(gray, scaleFactor=1.08,
                                             minNeighbors=5, minSize=(30, 30))
            for x,y,w,h in found:
                faces.append((int(x/factor),int(y/factor),
                              int(w/factor),int(h/factor)))
        video.release()
        if not faces:
            return None
        # Pick prominent face; do not crop too tightly around head.
        fx, fy, fw, fh = max(faces, key=lambda box: box[2]*box[3])
        cw = min(width, max(480, int(fw*5)))
        ch = min(height, max(380, int(fh*5)))
        ratio = 1080/860
        if cw/ch < ratio:
            cw = min(width, int(ch*ratio))
        else:
            ch = min(height, int(cw/ratio))
        left = min(max(0, int(fx+fw/2-cw/2)), max(0,width-cw))
        top = min(max(0, int(fy+fh/2-ch/2)), max(0,height-ch))
        if cw < 100 or ch < 100:
            return None
        print('FOCUS REGION', left, top, cw, ch, 'source', width,height, flush=True)
        return left, top, cw, ch
    except Exception as exc:
        print('WARN face detector fallback to central gameplay:', repr(exc)[:150], flush=True)
        return None


def render(clip, source):
    duration = probe(source)
    if not 15 <= duration <= 65:
        raise ValueError('Originalvideo outside supported range')
    # Gameplay highlights can be compelling without continuous dialogue.
    # QA rerun uses the verified no-fabricated-subtitles fallback.
    # Recheck the corrected FFmpeg volume parser with real Twitch samples.
    # Only speech-specific failures use the no-subtitle fallback; unsafe content
    # and genuinely broken media still fail closed.
    try:
        words = transcribe(source)
        start, length = pick_window(duration, words)
    except ValueError as exc:
        if not any(marker in str(exc) for marker in (
                'No reliable spoken content', 'Insufficient reliable speech',
                'No coherent 15-42s speech window')):
            raise
        print('QA GAMEPLAY FALLBACK: no trustworthy subtitles', repr(exc), flush=True)
        words = []
        start, length = 0.0, min(35.0, duration)

    if length < 15 or length > 45:
        raise ValueError('Cut must be between 15 and 45 seconds')
    OUT.mkdir(exist_ok=True)
    (OUT / 'headline.txt').write_text(
        '\n'.join(textwrap.wrap(headline(clip), 21, break_long_words=False)[:3]),
        encoding='utf-8')
    has_subs = write_subs(words, start, length, OUT / 'subs.ass') if words else False
    if words and not has_subs:
        print('QA GAMEPLAY FALLBACK: sparse captions omitted', flush=True)
    # No speech: use the real gameplay and headline, never fabricate captions.
    # Focus on a reaction face if detected, otherwise central gameplay; keep wide view below.
    focus_roi = find_face_focus(source, duration)
    if focus_roi:
        left, top, cw, ch = focus_roi
        focus_transform = (
            f'crop={cw}:{ch}:{left}:{top},scale=1080:860:'
            'force_original_aspect_ratio=increase,crop=1080:860,setsar=1')
    else:
        focus_transform = (
            'scale=1080:860:force_original_aspect_ratio=increase,'
            'crop=1080:860,setsar=1')
    filters = ('[0:v]split=3[bgsource][zoomsource][wide];'
               '[bgsource]scale=1080:1920:force_original_aspect_ratio=increase,'
               'crop=1080:1920,boxblur=18:8[bg];'
               '[zoomsource]' + focus_transform + '[focus];'
               '[wide]scale=1080:610:force_original_aspect_ratio=decrease,'
               'pad=1080:610:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[overview];'
               '[bg][focus]overlay=0:285[t1];'
               '[t1][overview]overlay=0:1170,'
               'drawbox=x=0:y=110:width=1080:height=140:color=black@0.7:t=fill,'
               'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:'
               'textfile=rendered/headline.txt:fontsize=55:fontcolor=white:borderw=3:'
               'bordercolor=black:x=(w-text_w)/2:y=142,'
               + ('ass=rendered/subs.ass,' if has_subs else '') + 'format=yuv420p[v];'
               '[0:a:0]loudnorm=I=-16:LRA=9:TP=-1.5[a]')
    movie = OUT / 'tiktok.mp4'
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', str(start),
         '-t', str(length), '-i', str(source), '-filter_complex', filters,
         '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast',
         '-crf', '23', '-r', '30', '-c:a', 'aac', '-b:a', '160k',
         '-movflags', '+faststart', str(movie)], timeout=360)
    if not 15 <= probe(movie) <= 45.5 or probe(movie, size=True) != '1080x1920':
        raise ValueError('Rendered MP4 failed duration or size check')
    run(['ffmpeg', '-v', 'error', '-i', str(movie), '-f', 'null', '-'],
        capture_output=True, timeout=120)
    verify_render_media(movie)
    cover = OUT / 'cover.jpg'
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', '1',
         '-i', str(movie), '-frames:v', '1', '-q:v', '3', str(cover)], timeout=30)
    return movie, cover, has_subs

def release(clip, video, cover, now):
    repo = os.getenv('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        raise ValueError('GitHub repository missing')
    tag = f'tiktok-{now:%Y-%m}'
    asset = slug(clip['channel_login'] + '-' + clip['id'])
    video_name, cover_name = asset + '.mp4', asset + '-cover.jpg'
    video_file, cover_file = OUT / video_name, OUT / cover_name
    video_file.write_bytes(video.read_bytes())
    cover_file.write_bytes(cover.read_bytes())
    if run(['gh', 'release', 'view', tag, '-R', repo], check=False, capture_output=True).returncode != 0:
        run(['gh', 'release', 'create', tag, '-R', repo, '--title', f'Video-Kandidaten {now:%Y-%m}', '--notes', 'Automatisch produzierte Kandidaten; Rechte und Duplikate vor Veroeffentlichung pruefen.'], timeout=60)
    # Never clobber an existing public asset: it might already have been shared.
    run(['gh', 'release', 'upload', tag, str(video_file), str(cover_file), '-R', repo], timeout=120)
    prefix = f'https://github.com/{repo}/releases/download/{tag}/'
    video_url = prefix + video_name
    # This checks PUBLIC reachability, not only asset existence in GitHub's API.
    # A newly created release URL can propagate briefly; curl retries.
    run(['curl', '--fail', '--silent', '--show-error', '--location', '--head',
         '--retry', '3', '--retry-all-errors', '--retry-delay', '3',
         '--max-time', '90', video_url], capture_output=True, timeout=100)
    return video_url, prefix + cover_name


def fresh_candidates(now, used, used_urls, failed, channels):
    """Two-stage discovery; the seven-day page is only a fallback source."""
    # When credentials exist, use authoritative Helix data exclusively.
    # Fail closed on API errors: do not silently downgrade to unverified listings.
    if os.getenv('TWITCH_CLIENT_ID') or os.getenv('TWITCH_CLIENT_SECRET'):
        for phase in ('24hr', '7d'):
            yield phase, helix_verified(phase, now, used, used_urls, failed, channels)
        return
    inspected = set()
    for phase in ('24hr', '7d'):
        links = [(channel, url) for channel, url in fetch_candidates(phase, channels)
                 if twitch_slug(url) not in inspected
                 and twitch_slug(url) not in used and url not in used_urls
                 and twitch_slug(url) not in failed]
        inspected.update(twitch_slug(url) for _, url in links)
        verified = []
        metadata_passed, selection_rejected = 0, 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(
                lambda pair: inspect_original(
                    pair[0], pair[1], now, int(os.getenv('MIN_VIEWS', '800'))), links)
            for clip in results:
                if clip and clip['id'] not in used and clip['clip_slug'] not in used:
                    metadata_passed += 1
                    if (clip['age_hours'] <= 48 or very_strong(clip)) and worth_testing(clip):
                        verified.append(clip)
                    else:
                        selection_rejected += 1
        print('DISCOVERY_DIAGNOSTIC', phase, json.dumps({
            'urls': len(links), 'valid_original_metadata': metadata_passed,
            'rejected_by_candidate_gate': selection_rejected,
            'eligible_for_quality_test': len(verified)}), flush=True)
        # Prefer a real number of views, strong view velocity, a fresh age and a usable length.
        verified.sort(key=selection_rank)
        print('VERIFIED', phase, len(verified), 'candidate(s)', flush=True)
        for clip in verified[:20]:
            print('QUALIFIED', phase, clip['channel_login'], clip['id'],
                  round(clip['age_hours'], 1), clip['view_count'], flush=True)
        yield phase, verified


def current_failed_ids(state, now):
    recent = {}
    for key, rec in state.get('failed_attempts', {}).items():
        try:
            stamp = dt.datetime.fromisoformat(rec['at'].replace('Z', '+00:00'))
            if (now - stamp).total_seconds() < 6 * 3600:
                recent[key] = rec
        except (KeyError, ValueError, TypeError):
            continue
    state['failed_attempts'] = recent
    return set(recent)


def remember_failure(state, clip, now, exc):
    state['failed_attempts'][clip['clip_slug']] = {
        'at': iso(now), 'streamer': clip['channel_login'], 'reason': repr(exc)[:200]}
    save_state(state)
    print('FAILED CANDIDATE - NEXT CLIP', clip['channel_login'],
          clip['clip_slug'], repr(exc)[:170], file=sys.stderr, flush=True)


def main():
    """Produce a small buffer of reviewed-later MP4s; never directly post to TikTok."""
    if os.getenv('ENABLE_PREPARATION') != 'true':
        print('SKIP: ENABLE_PREPARATION != true')
        return
    now, state = now_utc(), read_state()
    allowed, reason = can_prepare(state, now, os.getenv('GITHUB_EVENT_NAME', 'schedule'))
    if not allowed:
        print('SKIP:', reason)
        return
    channels = authorized_channels()
    if not channels:
        print('SKIP: no approved channels. No videos prepared.')
        return
    used, used_urls = used_ids(state)
    failed = current_failed_ids(state, now)
    monthly = [r for r in state['created'] if r.get('created_at', '').startswith(now.strftime('%Y-%m'))]
    daily = [r for r in monthly if r.get('created_at', '').startswith(now.strftime('%Y-%m-%d'))]
    daily_limit = 3
    remaining = min(max(0, daily_limit-len(daily)), max(0, 60-len(monthly)))
    if remaining <= 0:
        print('SKIP: production buffer already filled')
        return
    all_candidates = []
    for phase, verified in fresh_candidates(now, used, used_urls, failed, channels):
        all_candidates.extend((phase, clip) for clip in verified)
    all_candidates.sort(key=lambda x: selection_rank(x[1]))
    print('PRODUCTION CANDIDATE RANKING', json.dumps([
        {'source': p, 'channel': c['channel_login'], 'views': c['view_count'],
         'age_hours': round(c['age_hours'], 1)} for p, c in all_candidates[:15]],
        ensure_ascii=False), flush=True)
    prepared, attempted = 0, 0
    for phase, clip in all_candidates:
        if prepared >= remaining or attempted >= 16:
            break
        if clip['clip_slug'] in failed or clip['id'] in used:
            continue
        if (now_utc() - dt.datetime.fromisoformat(
                clip['original_created_at'].replace('Z', '+00:00'))).total_seconds() > 72*3600:
            continue
        attempted += 1
        try:
            print('PRODUCTION ATTEMPT', attempted, phase, clip['channel_login'],
                  clip['clip_slug'], clip['view_count'], flush=True)
            source = download(clip)
            movie, cover, has_subs = render(clip, source)
            # Silent gameplay commentary is not a failure if real audio passes QA.
            # Never invent subtitles for clips without reliable speech.
            # Trigger the release preparation smoke test on this commit.
            video_url, cover_url = release(clip, movie, cover, now)
            state['created'].append({
                'clip_id': clip['id'], 'clip_slug': clip['clip_slug'],
                'streamer': clip['channel_login'], 'source_url': clip['url'],
                'original_title': clip['title'], 'hook': headline(clip),
                'caption': caption(clip), 'views_at_selection': clip['view_count'],
                'original_duration': clip['duration'], 'rendered_duration': probe(movie),
                'original_created_at': clip['original_created_at'],
                'video_url': video_url, 'cover_url': cover_url,
                'transcript_subtitles': has_subs, 'created_at': iso(now),
                'status': 'awaiting_review_not_posted',
                'rights_status': 'user_asserted_not_independently_verified',
                'video_review_status': 'technical_checks_only',
                'editing_status': '9x16_face_focus_fullscreen_overview_15_42s',
                'subtitle_verified': False,
                'subtitle_review_status': ('auto_generated_needs_review' if has_subs else 'no_reliable_speech_no_subtitles')
            })
            state['processed_ids'].extend([clip['id'], clip['clip_slug']])
            used.update([clip['id'], clip['clip_slug']])
            save_state(state)
            print('VIDEO READY FOR QA, NOT POSTED:', video_url, flush=True)
            prepared += 1
        except Exception as exc:
            remember_failure(state, clip, now, exc)
            failed.add(clip['clip_slug'])
    print('PREPARATION SUMMARY', json.dumps({
        'channels_considered': len(channels),
        'new_candidates_considered': len(all_candidates),
        'attempted': attempted, 'produced': prepared,
        'target_this_run': remaining, 'tiktok_posts': 0}, ensure_ascii=False), flush=True)
    if not prepared:
        print('No suitable clip this run. Retry all eligible 50 sources next scheduled hour.')


def self_test():
    assert len(STREAMERS) == 50 and len(set(STREAMERS)) == 50
    assert callable(twitch_api_candidates) and callable(helix_verified)
    assert twitch_slug('https://www.twitch.tv/trymacs/clip/Example-123') == 'Example-123'
    assert twitch_slug('https://evil.com/a/clip/nope') is None
    example = {'channel_login': 'papaplatte', 'title': 'Das war verrückt!', 'duration': 27,
               'view_count': 13000, 'rank': 3, 'age_hours': 12}
    assert '#papaplatte' in caption(example)
    assert 'Clip von' not in caption(example) and 'Quelle:' not in caption(example)
    assert very_strong(dict(example, age_hours=55))
    assert not very_strong(dict(example, age_hours=55, view_count=900))
    assert sum(scheduled_slot(dt.datetime(2026, 10, i, tzinfo=UTC)) for i in range(1, 32)) == 20
    example_record = {'created_at': iso(dt.datetime(2026, 10, 13, 13, tzinfo=UTC))}
    assert can_prepare({'created': [example_record], 'processed_ids': []},
                       dt.datetime(2026, 10, 13, 14, tzinfo=UTC))[0]
    assert can_prepare({'created': [example_record, example_record], 'processed_ids': []},
                       dt.datetime(2026, 10, 13, 14, tzinfo=UTC))[0]
    assert not can_prepare({'created': [example_record]*3, 'processed_ids': []},
                           dt.datetime(2026, 10, 13, 14, tzinfo=UTC))[0]
    assert 'Quelle:' not in caption(dict(example, title='Quelle: https://example.org Mega fail'))
    sample_words = [(i*1.1, i*1.1+0.6, ('word.' if i in (9, 19, 29, 39) else 'word'))
                    for i in range(40)]
    cut_start, cut_length = pick_window(44, sample_words)
    assert 0 <= cut_start and 15 <= cut_length <= 42
    assert authorized_channels() is not None
    assert isinstance(rejected_clips(), set)
    # Verified clips should not be rejected only because their titles are mundane.
    assert worth_testing(dict(example, title='Normale Situation', age_hours=22, view_count=909))
    assert not worth_testing(dict(example, title='Sponsored advertisement', age_hours=5, view_count=8000))
    assert not worth_testing(dict(example, title='Normale Situation', age_hours=52, view_count=909))
    assert selection_rank(dict(example, age_hours=36, view_count=9000)) < selection_rank(
        dict(example, age_hours=8, view_count=800))
    assert '1885635439' in EXCLUDE_IDS
    assert '1586086735' in EXCLUDE_IDS
    assert worth_testing(dict(example, title='Was ein WTF Moment', view_count=13000))
    assert not worth_testing(dict(example, title='1 PARTNER + 1 STRIKE', view_count=1129, age_hours=8))
    assert worth_testing(dict(example, title='Unerwartete Szene', view_count=1129, age_hours=8))
    print('SELFTEST OK: age checks, fallback, 15-42s speech cuts, subtitles and limits')


def render_test():
    """Find and prepare several ranked QA samples. Never post to TikTok."""
    now = now_utc()
    channels = authorized_channels()
    if not channels:
        raise SystemExit('No approved channels for safe render test')
    known, used_urls = used_ids(read_state())
    attempts, produced = 0, 0
    target = min(4, max(1, int(os.getenv('QA_SAMPLE_COUNT', '3'))))
    discovered = []
    for phase, verified in fresh_candidates(
            now, known, used_urls, set(EXCLUDE_IDS) | rejected_clips(), channels):
        discovered.extend((phase, clip) for clip in verified)
    discovered.sort(key=lambda item: selection_rank(item[1]))
    print('QA GLOBAL RANKING', json.dumps([
        {'channel': clip['channel_login'], 'views': clip['view_count'],
         'age': round(clip['age_hours'], 1), 'phase': phase}
        for phase, clip in discovered[:20]], ensure_ascii=False), flush=True)
    for phase, clip in discovered:
        if attempts >= 16 or produced >= target:
            break
        attempts += 1
        try:
            if (now_utc() - dt.datetime.fromisoformat(
                    clip['original_created_at'].replace('Z', '+00:00'))).total_seconds() > 72*3600:
                print('SAFE RENDER SKIP: clip too old', clip['id'], flush=True)
                continue
            print('SAFE RENDER ATTEMPT', phase, clip['channel_login'], clip['id'], flush=True)
            source = download(clip)
            movie, cover, has_subs = render(clip, source)
            # No reliable speech is acceptable for a gameplay-only QA sample.
            sample_dir = OUT / 'qa_samples' / slug(
                clip['channel_login'] + '-' + clip['clip_slug'], 90)
            sample_dir.mkdir(parents=True, exist_ok=True)
            video_file = sample_dir / 'tiktok.mp4'
            cover_file = sample_dir / 'cover.jpg'
            subtitle_file = sample_dir / 'subs.ass'
            video_file.write_bytes(movie.read_bytes())
            cover_file.write_bytes(cover.read_bytes())
            if has_subs and (OUT / 'subs.ass').exists():
                subtitle_file.write_bytes((OUT / 'subs.ass').read_bytes())
            elif subtitle_file.exists():
                subtitle_file.unlink()
            manifest = {
                'sample_only': True, 'posted_to_tiktok': False,
                'no_public_release': True,
                'streamer': clip['channel_login'],
                'original_clip_url': clip['url'],
                'original_title': clip['title'],
                'original_created_at': clip['original_created_at'],
                'original_age_hours_at_selection': round(clip['age_hours'], 2),
                'original_views_at_selection': clip['view_count'],
                'original_duration': clip['duration'],
                'rendered_duration': probe(video_file),
                'video_file': str(video_file), 'cover_file': str(cover_file),
                'subtitle_status': ('auto_generated_needs_review' if has_subs else 'no_subtitles_no_reliable_speech'),
                'quality_review': 'not_performed',
                'editing_version': 'v3_popularity_ranked'
            }
            (sample_dir / 'test_manifest.json').write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',
                encoding='utf-8')
            (OUT / 'test_manifest.json').write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',
                encoding='utf-8')
            print('SAFE RENDER READY', json.dumps(manifest, ensure_ascii=False), flush=True)
            known.update([clip['id'], clip['clip_slug']])
            produced += 1
        except Exception as exc:
            print('SAFE RENDER FAILED - NEXT CLIP', clip['channel_login'],
                  repr(exc), file=sys.stderr, flush=True)
    print('QA RENDER SUMMARY', json.dumps({
        'attempted': attempts, 'produced': produced, 'target': target,
        'found_originals': len(discovered), 'tiktok_posts': 0}), flush=True)
    if produced < 1:
        raise SystemExit('No eligible sample rendered. Nothing posted; inspect logs.')


def source_diagnostic():
    """Read-only test of public Twitch clip listing and source metadata."""
    if os.getenv('TWITCH_CLIENT_ID') and os.getenv('TWITCH_CLIENT_SECRET'):
        channels = authorized_channels()
        if len(channels) != 50:
            raise SystemExit('FAILED: expected 50 approved channels')
        now = now_utc()
        results = {}
        for window in ('24hr', '7d'):
            candidates = helix_verified(window, now, set(), set(), set(), channels)
            results[window] = {
                'eligible': len(candidates),
                'sample': [{'channel': c['channel_login'], 'views': c['view_count'],
                            'age_hours': round(c['age_hours'], 1)}
                           for c in candidates[:5]]
            }
        print('HELIX DIAGNOSTIC SUMMARY', json.dumps({
            'approved_channels': len(channels),
            'eligible_clips_last_24h': results['24hr']['eligible'],
            'eligible_clips_last_72h': results['7d']['eligible'],
            'sample': results['7d']['sample'],
            'no_download_or_upload': True}), flush=True)
        return
    channels = ('papaplatte', 'eliasn97', 'trymacs', 'krokoboss')
    found = 0
    confirmed = 0
    now = now_utc()
    os.environ['DIAG_SOURCE_METADATA'] = 'true'
    for channel in channels:
        links = channel_urls(channel)
        print('DIAGNOSTIC CHANNEL', channel, 'clip_links:', len(links), flush=True)
        found += len(links)
        for _, link in links[:2]:
            clip = inspect_original(channel, link, now, min_views=0)
            if clip:
                confirmed += 1
                print('DIAGNOSTIC VERIFIED', json.dumps({
                    'streamer': channel, 'source_url': link,
                    'original_created_at': clip['original_created_at'],
                    'age_hours': round(clip['age_hours'], 2),
                    'views': clip['view_count'], 'duration': clip['duration']
                }, ensure_ascii=False), flush=True)
            else:
                print('DIAGNOSTIC UNVERIFIED', channel, link, flush=True)
    print('DIAGNOSTIC SUMMARY', json.dumps({
        'tested_channels': len(channels), 'clip_links': found,
        'verified_fresh_clips': confirmed, 'no_download_or_upload': True
    }), flush=True)
    if found == 0:
        raise SystemExit('FAILED: no Twitch clip listings; check yt-dlp and Twitch access')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    elif '--diagnose' in sys.argv:
        source_diagnostic()
    elif '--render-test' in sys.argv:
        render_test()
    else:
        main()
