# Novel Novel via Metricool

Goal: GitHub starts the existing clip pipeline and schedules eligible distinct TikToks for Novel Novel using Metricool, targeting 3–5/day when supply permits.

Architecture: reuse current media production, rights/QA gates, global source history, Berlin slots and durable Git checkpoints. Add a standard-library Metricool API adapter and optional workflow steps before Buffer allocation. A missing API secret reports blocked and leaves the two Buffer targets running. No use of chat OAuth credentials in GitHub and no plan purchase.

Confirmed target: brand 7451945, user 5794027, TikTok novel.novel601, Europe/Berlin. Live account is Free and API access requires Advanced/Custom. Existing post 406605403 is PUBLISHED; it is not a new upload from this implementation.

Implementation:
- [ ] Add exact-brand configuration and API publisher with read-only preflight.
- [ ] Reuse shared eligible-clip planner; cap at five/day and limit priority to one above the less-served Buffer account to share scarce supply.
- [ ] Persist pending intent before POST, reconcile receipts, retain ambiguous locks, and never retry uncertain creates.
- [ ] Add optional serialized workflow stages, reporting and activation guide; keep render budget unchanged.
- [ ] Test identity, caps, duplicate protection, payload/timezone, durable intent and truthful receipt handling.
- [ ] Deploy and run read-only/missing-secret smoke test; report API activation blocker explicitly.

API reference: https://app.metricool.com/resources/apidocs/index.html and linked official Swagger. Authentication: X-Mc-Auth plus userId/blogId. POST /api/v2/scheduler/posts; GET list and exact post. GitHub secret METRICOOL_API_KEY must be provided directly by the account owner after eligible API access is available.
