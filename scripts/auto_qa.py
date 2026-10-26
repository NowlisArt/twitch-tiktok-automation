"""Local machine QA. Never represents ASR agreement as human-verified accuracy."""
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT/'config/automatic_qa.json').read_text(encoding='utf-8'))
REQUIRED_CHECKS = ('media', 'subtitle_timing', 'speech_confidence', 'transcript_consistency',
                   'motion', 'source_metadata', 'content_filter')


def words(text):
    return re.findall(r'\w+', str(text).casefold(), flags=re.UNICODE)


def transcript_agreement(expected, observed):
    a, b = words(expected), words(observed)
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio() if a and b else 0


def seconds(value):
    h, m, s = value.split(':')
    return int(h)*3600 + int(m)*60 + float(s)


def caption_checks(path, duration):
    cues, previous_end, reasons = [], 0., []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.startswith('Dialogue:'):
            continue
        row = line.split(',', 9)
        try:
            a, b, label = seconds(row[1]), seconds(row[2]), row[9]
        except (IndexError, ValueError):
            reasons.append('malformed caption')
            continue
        lines = label.split('\\N')
        text = ' '.join(lines)
        if not 0 <= a < b <= duration + .02 or a < previous_end - .01:
            reasons.append('caption overlap or out-of-bounds time')
        if len(lines) > 2 or any(len(part) > 28 for part in lines):
            reasons.append('caption exceeds two readable lines')
        if len(text)/max(.01,b-a) > POLICY['maximum_characters_per_second'] + .1:
            reasons.append('caption too fast')
        previous_end = b
        cues.append((a, b, text))
    if len(cues) < 3:
        reasons.append('insufficient caption cues')
    return {'passed': not reasons, 'reasons': sorted(set(reasons)),
            'text': ' '.join(c[2] for c in cues), 'cue_count': len(cues)}


def motion_check(source, start, duration):
    # Inspect the gameplay region; chat and face-camera movement must not hide a static menu.
    result = subprocess.run(['ffmpeg','-hide_banner','-nostats','-ss',str(start),'-t',str(duration),
        '-i',str(source),'-an','-vf','crop=iw*0.60:ih*0.70:0:0,scale=320:-2,freezedetect=n=0.003:d=6',
        '-f','null','-'], capture_output=True, text=True, timeout=100)
    if result.returncode:
        return False
    longest, active = 0., None
    for line in result.stderr.splitlines():
        match = re.search(r'freeze_start:\s*([\d.]+)', line)
        if match: active = float(match.group(1))
        match = re.search(r'freeze_duration:\s*([\d.]+)', line)
        if match:
            longest = max(longest, float(match.group(1)))
            active = None
    if active is not None:
        longest = max(longest, duration-active)
    return longest <= min(POLICY['maximum_still_seconds'], duration*.45)


def verify(video, subtitles, duration, expected_text, source_confidence, transcribe):
    captions = caption_checks(subtitles, duration)
    if not captions['passed']:
        raise ValueError('Automatic caption QA: ' + ', '.join(captions['reasons']))
    observed = transcribe(video)  # Reuses the cached local model, no API/LLM bill.
    observed_text = ' '.join(w[2] for w in observed)
    agreement = min(transcript_agreement(expected_text, observed_text),
                    transcript_agreement(captions['text'], observed_text))
    confidence = min(source_confidence, getattr(transcribe, 'last_confidence', -99))
    if agreement < POLICY['minimum_transcript_agreement']:
        raise ValueError('Rendered audio/caption transcript mismatch')
    if confidence < POLICY['minimum_avg_logprob']:
        raise ValueError('Speech confidence below automatic publishing policy')
    return {'version': POLICY['version'], 'status': 'passed',
            'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'video_sha256': hashlib.sha256(Path(video).read_bytes()).hexdigest(),
            'subtitle_sha256': hashlib.sha256(Path(subtitles).read_bytes()).hexdigest(),
            'transcript_agreement': round(agreement, 4), 'avg_logprob': round(confidence, 4),
            'checks': {k: True for k in REQUIRED_CHECKS},
            'method': 'media decode/audio level, readable non-overlapping captions, gameplay motion, '
                      'source metadata/filter and local ASR consistency on rendered audio',
            'limitations': 'Machine acceptance, not human editorial review, perfect word accuracy or viral quality.'}
