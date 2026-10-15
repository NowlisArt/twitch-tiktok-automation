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
EXCLUDE_IDS = {'1885635439', 'PopularAgreeableBobaBatChest-T3Ga_Bm2CiWY5vII'}
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
    """Production buffer: max 60 prepared / month, max 2 / day.

    GitHub production is NOT the separate Metricool 20-post monthly limit.
    More production candidates allow genuine replacement when clips fail review.
    """
    monthly = [rec for rec in state['created']
               if rec.get('created_at', '').startswith(now.strftime('%Y-%m'))]
    if len(monthly) >= 60:
        return False, 'GitHub-Pufferlimit von 60 Produktionen in diesem Monat erreicht'
    if sum(rec.get('created_at', '').startswith(now.strftime('%Y-%m-%d'))
           for rec in monthly) >= 2:
        return False, 'Heute bereits zwei Clip-Kandidaten erstellt'
    if event == 'schedule' and not 9 <= now.hour <= 22:
        return False, 'Ausserhalb des Produktionszeitfensters (UTC)'
    return True, 'OK'


def authorized_channels():
    source = Path('config/approved_channels.txt')
    if not source.exists():
        return []
    approved = {line.strip().lower() for line in source.read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')}
    # A stable 50-channel seed list; it is not a live TwitchTracker ranking.
    return [channel for channel in STREAMERS if channel in approved]


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
        return list(dict.fromkeys(links))[:(8 if range_code == '24hr' else 12)]
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

def used_ids(state):
    used = set(EXCLUDE_IDS) | set(map(str, state['processed_ids']))
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


def selection_rank(clip):
    age = clip['age_hours']
    return (0 if age <= 24 else 1 if age <= 48 else 2, -score(clip))


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
    model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=4)
    segments, _ = model.transcribe(
        str(path), language='de', beam_size=4, word_timestamps=True,
        condition_on_previous_text=False, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=450))
    utterances = list(segments)
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
    events = []
    for group in groups:
        a, b = group[0][0], group[-1][1]
        label = ' '.join(x[2] for x in group).upper()
        label = label.replace('\\', '').replace('{', '(').replace('}', ')').replace('\n', ' ').strip()
        if label:
            events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(min(length, max(a + 0.45, b + 0.12)))},TikTok,,0,0,0,,{label}')
    path.write_text(header + '\n'.join(events) + '\n', encoding='utf-8')
    return len(events) >= 3

def render(clip, source):
    duration = probe(source)
    if not 15 <= duration <= 65:
        raise ValueError('Originalvideo outside supported range')
    words = transcribe(source)
    start, length = pick_window(duration, words)
    if length < 15 or length > 45:
        raise ValueError('Cut must be between 15 and 45 seconds')
    OUT.mkdir(exist_ok=True)
    (OUT / 'headline.txt').write_text(
        '\n'.join(textwrap.wrap(headline(clip), 21, break_long_words=False)[:3]),
        encoding='utf-8')
    if not write_subs(words, start, length, OUT / 'subs.ass'):
        raise ValueError('Subtitles are too sparse; move to next candidate')
    # 2-level layout: larger focal crop plus complete wide view so facecams stay visible.
    # Exact facecam auto-detection is not supported; visual QA still required.
    filters = ('[0:v]split=3[bgsource][zoomsource][wide];'
               '[bgsource]scale=1080:1920:force_original_aspect_ratio=increase,'
               'crop=1080:1920,boxblur=18:8[bg];'
               '[zoomsource]scale=1080:860:force_original_aspect_ratio=increase,'
               'crop=1080:860,setsar=1[focus];'
               '[wide]scale=1080:610:force_original_aspect_ratio=decrease,'
               'pad=1080:610:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[overview];'
               '[bg][focus]overlay=0:285[t1];'
               '[t1][overview]overlay=0:1170,'
               'drawbox=x=0:y=110:width=1080:height=140:color=black@0.7:t=fill,'
               'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:'
               'textfile=rendered/headline.txt:fontsize=55:fontcolor=white:borderw=3:'
               'bordercolor=black:x=(w-text_w)/2:y=142,'
               'ass=rendered/subs.ass,format=yuv420p[v];'
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
    cover = OUT / 'cover.jpg'
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', '1',
         '-i', str(movie), '-frames:v', '1', '-q:v', '3', str(cover)], timeout=30)
    return movie, cover, True

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
    inspected = set()
    for phase in ('24hr', '7d'):
        links = [(channel, url) for channel, url in fetch_candidates(phase, channels)
                 if twitch_slug(url) not in inspected
                 and twitch_slug(url) not in used and url not in used_urls
                 and twitch_slug(url) not in failed]
        inspected.update(twitch_slug(url) for _, url in links)
        verified = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(
                lambda pair: inspect_original(
                    pair[0], pair[1], now, int(os.getenv('MIN_VIEWS', '800'))), links)
            for clip in results:
                if clip and clip['id'] not in used and clip['clip_slug'] not in used:
                    if clip['age_hours'] <= 48 or very_strong(clip):
                        verified.append(clip)
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
    remaining = min(max(0, 2-len(daily)), max(0, 60-len(monthly)))
    prepared, attempted = 0, 0
    for phase, verified in fresh_candidates(now, used, used_urls, failed, channels):
        attempts_this_phase = 0
        for clip in verified:
            if prepared >= remaining or attempts_this_phase >= 12:
                break
            if clip['clip_slug'] in failed or clip['id'] in used:
                continue
            # Original created_at is never inferred from the GitHub queue timestamp.
            if (now_utc() - dt.datetime.fromisoformat(
                    clip['original_created_at'].replace('Z', '+00:00'))).total_seconds() > 72*3600:
                continue
            attempted += 1
            attempts_this_phase += 1
            try:
                source = download(clip)
                movie, cover, has_subs = render(clip, source)
                if not has_subs:
                    raise ValueError('Subtitles missing')
                video_url, cover_url = release(clip, movie, cover, now)
                state['created'].append({
                    'clip_id': clip['id'], 'clip_slug': clip['clip_slug'],
                    'streamer': clip['channel_login'], 'source_url': clip['url'],
                    'original_title': clip['title'], 'hook': headline(clip),
                    'caption': caption(clip), 'views_at_selection': clip['view_count'],
                    'original_duration': clip['duration'],
                    'original_created_at': clip['original_created_at'],
                    'video_url': video_url, 'cover_url': cover_url,
                    'transcript_subtitles': has_subs, 'created_at': iso(now),
                    'status': 'awaiting_review_not_posted',
                    'rights_status': 'user_asserted_not_independently_verified',
                    'video_review_status': 'metadata_only',
                    'editing_status': '9x16_focal_plus_fullscreen_cropped_15_42s',
                    'subtitle_verified': False,
                    'subtitle_review_status': 'auto_generated_needs_manual_review'
                })
                state['processed_ids'].extend([clip['id'], clip['clip_slug']])
                used.update([clip['id'], clip['clip_slug']])
                save_state(state)
                print('VIDEO READY (NOT POSTED TO TIKTOK):', video_url, flush=True)
                summary = os.getenv('GITHUB_STEP_SUMMARY')
                if summary:
                    with open(summary, 'a', encoding='utf-8') as handle:
                        handle.write(
                            f'## New candidate: {clip["channel_login"]}\n'
                            f'- Twitch views: {clip["view_count"]}\n'
                            f'- Original age: {clip["age_hours"]:.1f} hours\n'
                            f'- [Rendered MP4]({video_url})\n'
                            '- **NOT posted to TikTok. Manual QA needed.**\n')
                prepared += 1
            except Exception as exc:
                remember_failure(state, clip, now, exc)
                failed.add(clip['clip_slug'])
        if prepared >= remaining:
            break
    print('PREPARATION SUMMARY', json.dumps({
        'channels_considered': len(channels), 'attempted': attempted,
        'produced': prepared, 'target_this_run': remaining,
        'tiktok_posts': 0}, ensure_ascii=False), flush=True)
    if not prepared:
        print('No suitable new clip could be rendered; do NOT recycle old clips.')


def self_test():
    assert len(STREAMERS) == 50 and len(set(STREAMERS)) == 50
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
    assert not can_prepare({'created': [example_record, example_record], 'processed_ids': []},
                           dt.datetime(2026, 10, 13, 14, tzinfo=UTC))[0]
    assert 'Quelle:' not in caption(dict(example, title='Quelle: https://example.org Mega fail'))
    sample_words = [(i*1.1, i*1.1+0.6, ('word.' if i in (9, 19, 29, 39) else 'word'))
                    for i in range(40)]
    cut_start, cut_length = pick_window(44, sample_words)
    assert 0 <= cut_start and 15 <= cut_length <= 42
    assert authorized_channels() is not None
    assert '1885635439' in EXCLUDE_IDS
    print('SELFTEST OK: age checks, fallback, 15-42s speech cuts, subtitles and limits')


def render_test():
    """Render one QA sample, retry other clips and sources, never publish it."""
    now = now_utc()
    channels = authorized_channels()
    if not channels:
        raise SystemExit('No approved channels for safe render test')
    attempted = 0
    for phase, verified in fresh_candidates(now, set(EXCLUDE_IDS), set(), set(EXCLUDE_IDS), channels):
        for clip in verified:
            if attempted >= 12:
                break
            attempted += 1
            try:
                print('SAFE RENDER ATTEMPT', phase, clip['channel_login'], clip['id'], flush=True)
                source = download(clip)
                movie, cover, has_subs = render(clip, source)
                if not has_subs:
                    raise ValueError('No subtitles')
                manifest = {
                    'sample_only': True, 'posted_to_tiktok': False,
                    'no_public_release': True, 'streamer': clip['channel_login'],
                    'original_clip_url': clip['url'],
                    'original_created_at': clip['original_created_at'],
                    'original_age_hours_at_selection': round(clip['age_hours'], 2),
                    'original_views_at_selection': clip['view_count'],
                    'original_duration': clip['duration'], 'rendered_duration': probe(movie),
                    'video_file': str(movie), 'cover_file': str(cover),
                    'subtitle_status': 'auto_generated_needs_review',
                    'quality_review': 'not_performed',
                    'editing_version': 'v2_small_asr_speech_aware_focal'
                }
                (OUT / 'test_manifest.json').write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
                print('SAFE RENDER READY', json.dumps(manifest, ensure_ascii=False), flush=True)
                return
            except Exception as exc:
                print('SAFE RENDER FAILED - NEXT CLIP', clip['channel_login'],
                      repr(exc), file=sys.stderr, flush=True)
        if attempted >= 12:
            break
    raise SystemExit('No eligible sample could be rendered. No posting; inspect logs.')


def source_diagnostic():
    """Read-only test of public Twitch clip listing and source metadata."""
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
