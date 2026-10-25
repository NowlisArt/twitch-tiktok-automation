# Twitch → Dream Void and Sunshine via GitHub Actions

GitHub Actions starts the entire process. ChatGPT is no longer required as a scheduler or publisher.

## Operation

Open [Run workflow](https://github.com/NowlisArt/twitch-tiktok-automation/actions/workflows/tiktok.yml).

- `preflight` (default): read-only live Buffer authentication, exact TikTok channel, connection flags, GraphQL contract and complete queue checks. No new posts.
- `diagnose`: official Twitch metadata only, no downloads or posting.
- `prepare`: render private QA candidates, no Buffer posting.
- `run`: reviewed artifact promotion, discovery/rendering, then eligible Buffer scheduling and receipt reconciliation for both accounts.
- Scheduled at 07:17, 10:17, 13:17, 16:17, 19:17 and 22:17 **UTC**, best effort. Berlin posting slots remain 11:00, 14:00, 17:00, 19:00, 21:00 across DST.

The target is **3–5 different suitable authorized TikToks daily per account**, with at most five reservations/posts per account and Berlin calendar day (ten total). A shared planner balances scarce eligible clips between both accounts and never allocates one source to both. A shortage remains a shortage; it never lowers rights, subtitles or content QA. The planner fills only the next 24 hours and checks original age at the planned posting time. Manual posts in the live target queue consume the daily cap too.

`config/publishing.json` controls the budget: two renders/run, four candidate attempts/run, up to twelve shared daily candidates and 372 shared monthly candidates. ASR runs locally on the runner with a cached medium Whisper model; no paid LLM calls. Model confidence is not evidence of subtitle accuracy. Actual Actions minutes depend on attempts and GitHub billing.

## Discovery and editing

`config/watchlist.json` is the manually checked **German TwitchTracker overall top-50 snapshot, 25 October 2026**, not an automatic live ranking. New ranking members never receive permission automatically. TwitchTracker prohibits recurring scraping; refresh the documented snapshot through permitted access when needed. Discovery uses the intersection with the user-declared `config/approved_channels.txt`, minus `config/revoked_channels.txt` if present.

Original IDs/URLs, title, timestamp, views, duration and available broadcaster/creator/game/VOD metadata come from Twitch Helix. Existing age, view and unsuitable-title filters remain. No fabricated metadata. FFmpeg retains a wide overview plus reaction framing, 1080×1920, audible normalized audio, real speech cuts, and short high-contrast subtitle groups within safe margins. Subtitle timing/readability checks reject unusable renders; new clips can be accepted by the automatic policy described below; exact human word accuracy and editorial quality are not claimed from ASR confidence.

New media starts locally as a QA candidate. New videos passing the configured automatic checks are released and scheduled in the same GitHub run. Failed or manually rejected renders remain unapproved; the `twitch-video-qa` artifact retains QA files for seven days. Retention is a review deadline; expired artifacts require a new render and review. Repository collaborators and artifact access rules still apply.

## Rights and exact-media review

The user explicitly confirmed oral permissions on 25 October 2026 and requested no written evidence. The bounded top-50 snapshot is recorded as `user_attested_oral`, never as independently verified permission. Future ranking additions require a new attestation. Historical clip flags are preserved; no content or subtitle approvals are inferred.

To enable a source for release, use the existing explicit oral attestation or add a documented entry to `config/rights.json`:

```json
{
  "id": "permission-record-id",
  "streamer": "actual_twitch_login",
  "status": "verified_permission",
  "evidence_reference": "reference to actual permission; do not publish private documents here",
  "verified_by": "actual reviewer",
  "verified_at": "2026-10-25T12:00:00Z",
  "scope": ["edit", "subtitles", "tiktok", "public_hosting"],
  "revoked": false,
  "expires_at": null
}
```

For optional human review after watching/listening to the exact candidate and checking the subtitles against audio, add a review entry to `config/reviews.json`. Copy `clip_id`, `video_sha256`, and `subtitle_sha256` from the candidate manifest. Include actual `reviewer`, timezone-aware `reviewed_at`, substantive `notes`, integer `quality_score` ≥85 and explicit true values for `subtitle_accuracy`, `readability`, `audio_video`, `context`, and `rights_in_clip`. Do not mark a review done merely to fill a quota. Pushing rights/reviews to main invokes the workflow. It downloads the exact run/artifact, verifies both hashes and technical media checks, hosts the approved MP4, and schedules only while current evidence remains valid.

## Buffer and credentials

Authorized targets, explicitly requested by the user on 25 October 2026:

- **Dream Void @dreamvoid26**, channel `6ad6c095778b240e2f624d3b`.
- **Sunshine @suhshine28**, channel `6ade2e8c2f1f5ed648cabd2c`.

The same existing Buffer key is used. Both exact channel IDs, handles, TikTok service and connection/queue flags must pass live verification. Both complete queues are fetched before a new post is created. Daily limits and receipts are separate per account; source/URL duplicate protection stays global. Unknown pending submissions retain their original account reservation. Historical untagged Buffer receipts remain assigned to Dream Void; they are not copied to Sunshine. Historical Metricool records stay in duplicate history; no new Metricool posting is performed.

GitHub repository secrets: `BUFFER_API_KEY`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`. Buffer uses `https://api.buffer.com`, bearer authentication, `CreatePostInput`, `customScheduled`, `automatic` and public video asset URLs. The preflight validates the live contract without creating a test post. Keys, passwords and OAuth tokens never belong in chat, files, logs or commits.

The existing Buffer key UI on 25 October showed expiry **16 November 2026**. Its actual correspondence to the GitHub secret must be verified by preflight. The Free plan currently has one key slot and blocks adding another key. No upgrade or credential regeneration is performed automatically. Before expiry, renew through Buffer's offered options and save the replacement directly to GitHub Secrets. A personal key's unlimited lifetime is not promised. If using OAuth instead, follow provider `expires_in`, request `offline_access`, and persist every rotated single-use refresh token; a rotating OAuth refresh token must not be treated as a static Actions secret.

## State, duplicate protection and receipts

All production writers share `twitch-auto20-nowlisart-main`, `cancel-in-progress: false`, and check out current main. IDs/slugs/source URLs, reservations and historical Metricool/Buffer use prevent reuse across accounts. Before every Buffer mutation, a pending intent is atomically written, committed and pushed. A failed push prevents submission. A timeout/cancellation retains the remote reservation; never blindly retry. Reconciliation can recover one exact media URL match, otherwise manual queue inspection is required. State pushes never force or silently rebase over another writer.

`state/auto20.json`, the run summary and `buffer-report.json` (broken down by account) distinguish prepared, reviewed, scheduled, sent, error and uncertain. Only Buffer `sent` is provider-confirmed publication; record `sentAt` and `externalLink` where available. A green run and a GitHub Release are not proof of a TikTok upload. Failed posts retain duplicate protection and are not automatically reposted.

Migration check on 25 October 2026: all four legacy ChatGPT tasks were paused and visibly verified in ChatGPT Tasks: Twitch TikTok Pipeline Watchdog, TikTok-Upload Ersatzprüfung, GitHub Videotest überwachen, and Twitch-Clips automatisch posten. GitHub is now the sole configured starter. A screenshot of the paused tasks was saved with the migration deliverables.

The complete manual GitHub run [40214301943](https://github.com/NowlisArt/twitch-tiktok-automation/actions/runs/40214301943) succeeded: all 50 channels resolved in Helix, one new private QA video rendered, zero new Buffer posts. Live channel/contract/queue checks passed; all four tracked historical posts returned `sent` with destination links. See [verified upload ledger](docs/verified-uploads-2026-10-25.json). Semantic subtitle/content review of the new video is still pending; no new approval is claimed.

## Tests

```sh
python -m unittest discover -s tests -v
python scripts/pipeline.py --self-test
python scripts/distribute.py --selftest
python scripts/status.py
```

CI parses every workflow. Regression tests cover daily caps including pending/manual posts, Berlin DST, source expiry, exact hash reviews, permission scope/revocation/expiry, pagination, wrong/paused channels, cross-field duplicate identities, durable intent before network timeout, failed checkpoint preventing mutation, and publication receipts. Live Buffer/Twitch tests require the existing secrets and are run in Actions.

## Provider references

- [Buffer authentication and OAuth](https://developers.buffer.com/guides/authentication.html)
- [Buffer video post contract](https://developers.buffer.com/examples/create-video-post.html)
- [Buffer GraphQL reference](https://developers.buffer.com/reference.html)
- [TwitchTracker German ranking](https://twitchtracker.com/channels/ranking/german)

The old `buffer.yml` and promotion workflow have been replaced by the single starter; the obsolete manual `promote_approved.py` is retained only as history and is not invoked by Actions.

## Two-account expansion, 25 October 2026

Both existing connected accounts are now publishing targets, per the user's request. This expands routing and render capacity only; no quality approvals are invented. Five Berlin slots apply independently to each account. At low supply, accounts with fewer reservations that day take priority; historical service order breaks ties. Tests additionally cover ten unique allocations, fair shortage distribution, independent daily caps, Sunshine live identity checks, cross-account source/media reuse, and correct durable Sunshine intent and payload.

## Autonomous mode (explicitly requested 25 October 2026)

`config/automatic_qa.json` enables machine acceptance of NEW renders, without a per-clip human approval stop. Existing oral source authorization and cross-account duplicate history remain. No paid LLM/API is used for captions or QA: the cached local Whisper model transcribes source and rendered audio, with at least 80% token agreement and mean log probability at least -0.85. These are automated consistency checks, not proof of perfect word accuracy. Other checks cover source metadata, audible decodable media, caption bounds/overlap/two-line readability, basic unsuitable speech filtering and long static gameplay/menu phases.

New evidence is tied to the exact video and subtitle hashes. Machine accepted clips retain `subtitle_verified=false` and `quality_score_verified=false`; `approval_method=automatic_machine_checks` distinguishes them from actual human review. No arbitrary verified editorial score is fabricated. Existing exact-byte human rejections are honored. Changing policy or disabling `enabled` stops machine acceptance. Clips without a manual review or valid machine evidence stay blocked.

Caption timing is checked before expensive encoding; short cards can merge and long German words wrap. The new rendering uses one source view and a dedicated lower subtitle band, avoiding the previous repeated two-panel picture and text. It does not claim to remove every subtitle already burned into source footage.

A second release step after preparation promotes valid local files immediately; no download of an unfinished current-run artifact is required. A broken/expired release candidate logs its error and does not block other clips or Buffer reconciliation. Interrupted public asset uploads reuse matching bytes rather than failing forever on an existing asset name. Ambiguous Buffer submissions retain their reservation to prevent duplicate posts.

The daily target remains 3–5 eligible distinct videos per account. Missing usable content, provider outages or an expired credential can still cause a shortfall; the run summary reports that honestly. Authentication renewal may still require the account owner. Old ChatGPT posting tasks remain paused; GitHub is the starter.
