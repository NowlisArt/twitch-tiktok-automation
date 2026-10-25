# GitHub pipeline implementation plan

**Goal:** GitHub owns discovery, rendering, review promotion, Buffer scheduling and receipts for Dream Void.

**Architecture:** Existing Python/Helix/FFmpeg/Whisper stack, one serialized main-branch writer, Git state journal before Buffer mutations. Unreviewed media stays in Actions artifacts; verified rights and exact media/subtitle review are required for public hosting and posting.

**User decisions:** autonomous replacement; no invented approvals; target 3â€“5 distinct suitable clips daily; existing resources; secrets stay in GitHub. No design approval round requested.

- [x] Add regression coverage for daily caps, DST, pagination, ambiguous submissions, cross-field duplicates and evidence gates.
- [x] Consolidate schedules and state writer lock; add read-only preflight and independent CI.
- [x] Retain original metadata; refresh the manually checked German TwitchTracker snapshot; intersect with declared channels and revocations.
- [x] Store hashed private QA artifacts; promote exact bytes only after recorded rights/content review.
- [x] Use verified Buffer GraphQL contract, exact channel checks and durable mutation intent; record sent receipts separately.
- [x] Run local tests, GitHub CI and live connection preflight; report actual blockers and upload evidence.

Validation result: 20 local/GitHub regression tests and the existing self-tests pass. Complete production-mode smoke run 40214301943 succeeded; 50 Helix channels, one private QA render, zero new posts. All four legacy ChatGPT tasks visibly paused. Content review remains deliberately unapproved. Oral rights attestation added on the user's explicit clarification; never labeled independent verification.
