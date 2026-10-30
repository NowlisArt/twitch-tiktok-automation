# Throughput repair, 30 October 2026

Observed 29 October: three automatic runs, 24 attempted candidates, two completed videos shared by four accounts. Caption rejections mostly report excessive reading speed. Latest 30 October run reached one finished video but failed at a Git publishing checkpoint; the captured exception did not expose the underlying transport/rejection reason.

Changes: borrow adjacent subtitle display time with a maximum 650ms speech delay; retain all words and existing 28 characters/second and two-line checks. Retry transport/server Git push failures at most three times; fail immediately for recognized permission or remote-ahead rejections and retain reservations. Apply the same checkpoint to final state persistence. Increase candidate attempts to 20 and preparation timeout to 25 minutes; hourly schedule provides more recovery opportunities. Retain caps of four finished renders per run, 24 per day, 744 per month, and five posts per account/day. A code/config push also starts a real validation/production run.

No guarantee of GitHub schedule delivery or daily quota. No permissions, subscriptions or credentials changed. Unknown provider mutations remain locked. Actual post receipts must be checked after rollout. The root cause of the existing Git failure remains unconfirmed until the new diagnostic executes.
