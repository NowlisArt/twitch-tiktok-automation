"""Multi-account allocation planner. Read-only; never posts or changes queue state.

Only independently approved clips are eligible. Every source ID is allocated
at most once across accounts. Add accounts to config/distribution.json.
"""
import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "distribution.json"
DEFAULT_STATE = ROOT / "state" / "auto20.json"


def eligible(clip, threshold):
    required = (
        clip.get("technical_qa_passed") is True
        and clip.get("subtitle_verified") is True
        and clip.get("editorial_review_status") == "approved"
        and clip.get("rights_status") == "verified_permission"
        and clip.get("quality_score_verified") is True
        and type(clip.get("quality_score")) is int
        and threshold <= clip["quality_score"] <= 100
        and clip.get("status") == "approved_for_distribution"
    )
    return bool(required)


def clip_keys(clip):
    """Normalize source identities across re-encoded media and TikTok accounts."""
    from urllib.parse import urlsplit
    keys = set()
    for field in ("clip_id", "clip_slug"):
        value = str(clip.get(field) or "").strip()
        if value:
            keys.add(field + ":" + value)
    url = str(clip.get("source_url") or "").strip()
    if url:
        parts = urlsplit(url)
        keys.add("source_url:" + parts.netloc.lower() + parts.path.rstrip("/").lower())
    return keys


def unavailable(clip):
    """A pending, reserved or posted clip is never an unallocated candidate."""
    return bool(
        clip.get("posted_to_tiktok")
        or clip.get("buffer_post_id")
        or clip.get("metricool_post_id")
        or clip.get("reserved_for")
        or clip.get("reservation_id")
        or str(clip.get("status", "")).startswith(("metricool_", "buffer_"))
    )


def allocate(clips, accounts, used_ids=None):
    used = set(str(value) for value in (used_ids or ()))
    # Reserve all historical identities BEFORE considering approved candidates.
    for clip in clips:
        if unavailable(clip):
            used.update(clip_keys(clip))
            if clip.get("clip_id"):
                used.add(str(clip["clip_id"]))
    result = {account["id"]: [] for account in accounts}
    for account in sorted(accounts, key=lambda x: x["priority"]):
        for clip in clips:
            cid = str(clip.get("clip_id") or "")
            keys = clip_keys(clip)
            if not cid or unavailable(clip) or cid in used or keys.intersection(used):
                continue
            if not eligible(clip, account["minimum_quality"]):
                continue
            result[account["id"]].append(cid)
            used.add(cid)
            used.update(keys)
            if len(result[account["id"]]) >= account["videos_per_day"]:
                break
    return result

def validate(accounts):
    assert isinstance(accounts, list) and accounts
    ids = [a["id"] for a in accounts]
    assert len(ids) == len(set(ids)), "Duplicate account IDs"
    for a in accounts:
        assert a["platform"] == "tiktok"
        assert a["provider"] in ("metricool", "buffer")
        assert type(a["videos_per_day"]) is int and 1 <= a["videos_per_day"] <= 12
        assert type(a["priority"]) is int
        assert type(a["minimum_quality"]) is int and 85 <= a["minimum_quality"] <= 100
        assert a["timezone"] == "Europe/Berlin"
        assert len(a["posting_hours"]) == a["videos_per_day"]
        assert all(type(h) is int and 0 <= h <= 23 for h in a["posting_hours"])


def selftest():
    approved = {
        "status": "approved_for_distribution",
        "technical_qa_passed": True,
        "subtitle_verified": True,
        "editorial_review_status": "approved",
        "rights_status": "verified_permission",
        "quality_score_verified": True,
        "quality_score": 90,
    }
    accounts = [
        {"id": "novel", "priority": 1, "videos_per_day": 1, "minimum_quality": 85},
        {"id": "dream", "priority": 2, "videos_per_day": 2, "minimum_quality": 85},
    ]
    clips = [dict(approved, clip_id=str(i)) for i in range(4)]
    result = allocate(clips, accounts)
    assert result == {"novel": ["0"], "dream": ["1", "2"]}, result
    assert len(set(sum(result.values(), []))) == 3
    assert allocate(clips, accounts, used_ids={"0"}) == {"novel": ["1"], "dream": ["2", "3"]}
    assert allocate([dict(approved, clip_id="a", quality_score=84)], accounts) == {"novel": [], "dream": []}
    assert allocate([dict(approved, clip_id="a", metricool_post_id="used")], accounts) == {"novel": [], "dream": []}
    assert allocate([dict(approved, clip_id="a", subtitle_verified=False)], accounts) == {"novel": [], "dream": []}
    duplicate = [
        dict(approved, clip_id="a", clip_slug="same", source_url="https://clips.twitch.tv/xyz?a=1"),
        dict(approved, clip_id="b", clip_slug="same", source_url="https://clips.twitch.tv/xyz?a=2"),
        dict(approved, clip_id="c", clip_slug="unique", source_url="https://clips.twitch.tv/other"),
    ]
    assert allocate(duplicate, accounts) == {"novel": ["a"], "dream": ["c"]}
    blocked = [
        dict(approved, clip_id="a", clip_slug="same", status="buffer_pending"),
        dict(approved, clip_id="b", clip_slug="same"),
    ]
    assert allocate(blocked, accounts) == {"novel": [], "dream": []}
    assert allocate([dict(approved, clip_id="a", reserved_for="dreamvoid")], accounts) == {"novel": [], "dream": []}
    print("PASS: multi-account priority, exclusivity, historical reuse, QA fail-closed")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    config = json.loads(args.config.read_text(encoding="utf-8"))
    accounts = config["accounts"]
    validate(accounts)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    clips = state["created"]
    result = allocate(clips, accounts)
    print(json.dumps({
        "mode": "preview_only_no_publication",
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "allocation": result,
        "shortfalls": {a["id"]: a["videos_per_day"] - len(result[a["id"]]) for a in accounts},
        "total_candidates": len(clips),
        "total_quality_approved": sum(eligible(c, 85) for c in clips),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
