#!/usr/bin/env python3
"""Merge Auto20 queue snapshots without discarding remote publication states."""
import json
import sys
from pathlib import Path

remote = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
local = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
remote.setdefault("created", [])
remote.setdefault("processed_ids", [])
remote.setdefault("failed_attempts", {})

def identifiers(item):
    return [str(item[k]) for k in ("clip_id", "clip_slug") if item.get(k)]

existing = {k: item for item in remote["created"] for k in identifiers(item)}
for item in local.get("created", []):
    match = next((existing[k] for k in identifiers(item) if k in existing), None)
    if match is None:
        match = dict(item)
        remote["created"].append(match)
    else:
        for key, value in item.items():
            if key not in match or match[key] is None:
                match[key] = value
    for key in identifiers(match):
        existing[key] = match

seen = set()
ids = []
for value in remote["processed_ids"] + local.get("processed_ids", []):
    if value not in seen:
        seen.add(value)
        ids.append(value)
for item in remote["created"]:
    for value in identifiers(item):
        if value not in seen:
            seen.add(value)
            ids.append(value)
remote["processed_ids"] = ids

for key, value in local.get("failed_attempts", {}).items():
    if key in existing:
        continue
    previous = remote["failed_attempts"].get(key)
    if previous is None or value.get("at", "") > previous.get("at", ""):
        remote["failed_attempts"][key] = value
for key in list(remote["failed_attempts"]):
    if key in existing:
        del remote["failed_attempts"][key]

print(json.dumps(remote, ensure_ascii=False, indent=2))
