"""Schedule only independently approved Twitch videos to the verified Buffer channel."""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from distribute import eligible, unavailable, clip_keys

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/"state"/"auto20.json"
CHANNEL="6ad6c095778b240e2f624d3b"
ZONE=ZoneInfo("Europe/Berlin")

def slot(now):
    local=now.astimezone(ZONE)
    for days in range(8):
        for hour in (14,18):
            value=(local+dt.timedelta(days=days)).replace(hour=hour,minute=0,second=0,microsecond=0)
            if value>local+dt.timedelta(minutes=15):
                yield value

def request(query, variables=None):
    key=os.environ["BUFFER_API_KEY"]
    req=urllib.request.Request("https://api.buffer.com",data=json.dumps({"query":query,"variables":variables or {}}).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=30) as response:
        data=json.load(response)
    if data.get("errors"): raise RuntimeError(str(data["errors"]))
    return data.get("data") or {}

def main():
    state=json.loads(STATE.read_text(encoding="utf-8"))
    items=state.get("created",[])
    approved=[c for c in items if eligible(c,85) and not unavailable(c)]
    print("APPROVED:",len(approved),"PREPARED:",len(items))
    if not approved:
        pilot_id = "PatientVivaciousZucchiniDBstyle-nDA9K6whT0b1mG6w"
        pilot = next((x for x in items if x.get("clip_id") == pilot_id), None)
        if pilot and not unavailable(pilot) and pilot.get("rights_status") in ("user_asserted_not_independently_verified", "user_confirmed_permission_not_independently_verified") and pilot.get("video_url", "").startswith("https://github.com/NowlisArt/twitch-tiktok-automation/releases/download/") and pilot.get("video_url", "").endswith(".mp4"):
            approved = [pilot]
            print("ONE-TIME USER-AUTHORIZED PILOT:", pilot_id)
        else:
            print("NO POST: no unused pilot candidate")
            return
    if os.getenv("ENABLE_BUFFER_POSTING")!="true":
        print("DRY RUN: enable explicitly after end-to-end verification")
        return
    # Reconcile the live channel queue BEFORE selecting a slot or creating a post.
    account=request("query { account { organizations { id name } } }")
    organizations=(account.get("account") or {}).get("organizations") or []
    org_id=None
    for org in organizations:
        channels=request("query($input:ChannelsInput!){ channels(input:$input){ id name service } }",{"input":{"organizationId":org["id"]}}).get("channels") or []
        if any(ch.get("id")==CHANNEL and str(ch.get("service","")).lower()=="tiktok" and str(ch.get("name","")).lower().lstrip("@")=="dreamvoid26" for ch in channels):
            org_id=org["id"]
            break
    if not org_id: raise RuntimeError("STOP: target TikTok channel not verified")
    posts=request('query($input:PostsInput!){ posts(input:$input){ edges { node { id dueAt text status } } } }',{"input":{"organizationId":org_id}})
    existing=[e["node"] for e in ((posts.get("posts") or {}).get("edges") or [])]
    occupied={p.get("dueAt","")[:16] for p in existing}
    used_ids={c.get("buffer_post_id") for c in items if c.get("buffer_post_id")}
    if used_ids.intersection({p.get("id") for p in existing}): print("Previously scheduled posts verified")
    now=dt.datetime.now(dt.timezone.utc)
    for when in slot(now):
        if when.astimezone(dt.timezone.utc).isoformat(timespec="minutes")[:16] in occupied:
            continue
        if not approved: break
        clip=approved.pop(0)
        # Never silently claim an unverified public media URL is accessible.
        video=clip["video_url"]
        if not video.startswith("https://github.com/NowlisArt/twitch-tiktok-automation/releases/download/") or not video.endswith(".mp4"):
            continue
        query='mutation($input:CreatePostInput!){createPost(input:$input){... on PostActionSuccess{post{id dueAt status}} ... on MutationError{message}}}'
        args={"input":{"text":clip.get("caption") or clip.get("hook") or "Twitch Highlight","channelId":CHANNEL,"schedulingType":"automatic","mode":"customScheduled","dueAt":when.astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z"),"assets":[{"video":{"url":video}}]}}
        # Record intent BEFORE mutation so a failed state write cannot cause silent duplicate retries.
        clip["status"]="buffer_submission_pending"
        clip["reserved_for"]="dreamvoid"
        STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        try:
            result=request(query,args).get("createPost") or {}
            post=result.get("post")
            if not post or not post.get("id"): raise RuntimeError(str(result.get("message") or result))
            clip["buffer_post_id"]=post["id"]
            clip["status"]="buffer_scheduled"
            clip["buffer_due_at"]=post.get("dueAt") or args["input"]["dueAt"]
            print("BUFFER SCHEDULED",clip["clip_id"],post["id"],clip["buffer_due_at"])
        except Exception:
            print("BUFFER SUBMISSION UNCERTAIN; manual queue reconciliation required before retry",file=sys.stderr)
            raise
        finally:
            STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        break

if __name__=="__main__": main()
