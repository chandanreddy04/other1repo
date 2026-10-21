# UX Review — Post-Session-Creation Experience (2026-07-16)

Adversarially-reviewed audit of what the **session creator (owner)** and the
**circle member (contact)** experience from the moment a session is created.
Method: two independent reviewers (one per perspective) each produced a
current-state description + proposal; each proposal then went through two
rounds of adversarial review (fact-checking every claim against the code)
until the reviews stopped finding substantive defects. This doc records the
converged result and tracks what has shipped vs. what remains.

Related: `docs/flow-review.md` (the 2026-07-02 flow review this builds on),
`.claude/rules/domain-sessions-alerts.md` (invariants updated 2026-07-16),
`docs/manual-test-plan.md` §4 (device-QA items for the shipped fixes).

---

## 1. Shipped 2026-07-16 (commits `a546563`…`8857ee3`)

The "first slice": owner Tier 0 + Tier 1, circle items 1–2 — the confirmed
safety-correctness bugs.

| # | Fix | Where |
|---|-----|-------|
| T0 | `GET /sessions/active` returns non-terminal sessions (ACTIVE/MISSED/ALERTED, ACTIVE-first, newest, `limit(1)`) + computes `alert_acknowledged`; mobile seeds server-truth state from it. Was: any remount mid-incident (incl. tapping the `circle_alerted` push) nulled the store, showed "No active session", and killed the Live Activity. | `crud/session.py`, `endpoints/sessions.py`, `active-session.tsx` |
| T1.1 | Alarm-card "I'm Safe" keeps the emergency UI up on a **rejected** mark-safe (was: silent teardown while circle alerts stayed live). | `(tabs)/index.tsx` |
| T1.2 | Mark-safe with an offline-queued SOS clears the pending queue (was: the "cancelled" SOS fired later — zombie SOS). | `(tabs)/index.tsx`, `sosQueue.clearPendingSOS` |
| T1.3 | New `circle_unreachable` flag + `LIVE_STATUS_COPY.unreachable` ("We couldn't reach your circle / Call or text them directly, or call 911"). Was: "Notifying your circle…" **forever** when every delivery was terminally dead. | `notification_outbox.is_circle_unreachable`, `liveStatus.ts` |
| T1.4 | Home "I'm Safe" gets success/error toasts (was: unhandled rejection, zero feedback on the primary safety action). | `(tabs)/index.tsx` |
| T1.5 | `checkinQueue` classifies terminal-vs-retryable like `sosQueue` (was: 4xx retried forever with the UI already optimistically cleared). | `checkinQueue.ts` |
| C1 | Circle-viewer snapshot (`services/circle_view.py`) shared by the public alert page **and** `GET /alerts` — restores owner name, Call/Text, map pin, outing details, battery to the in-app alert screen. Was: schema never sent these ("Unknown User", no actions — worse than the public page). Backend-only fix; live for all installed app versions. | `circle_view.py`, `schemas/alert.py`, `endpoints/alerts.py` |
| C2 | Terminal claim guard in `claim_alert()` (no-op once alert RESOLVED / session over — no post-all-clear "on it" broadcast, from any of the 3 claim surfaces); public page shows other recipients "{claimer} is already on it"; mobile renders resolved truth (safe badge replaces claim button, "Resolved — they're safe" pill, smart-tab fix, `isAlertResolved`). | `alert_claim.py`, `routes_web.py`, `alert_view.html`, `useAlertsStore.ts`, `alert-details.tsx`, `AlertLogCard.tsx` |

Decisions taken with the T0 fix (deliberate, easy to revert): a lingering
MISSED session **blocks starting a new check-in** (mark safe first), and
**circle edits are blocked during an incident**, not just while ACTIVE.

Verification: `make verify` green — 1723 backend tests (23 new; ratchet
1694→1723; coverage 91.46%), 153 mobile tests (8 new).

---

## 2. Resolution record (walkthrough with the owner, 2026-07-18/19)

Every remaining item was walked through one-by-one and either shipped,
redesigned per owner decisions, or explicitly skipped. Shipped (commits
`1748edb`…`6c9875c`, each item its own commit):

- **O1** retention toast says 7 days (mirrored constant).
- **O2** circle_alerted push wired to its title/body constants.
- **O3 (+owner decision)** honest SOS card ("Sending…" → server-truth badge,
  queued banner, gated shared-info rows) AND **SOS sessions now share
  photos** (reverses flow-review: anything captured mid-emergency
  auto-discovers to the alert page). *Superseded 2026-09-05: background photo
  discovery was removed entirely; SOS shares location + battery only.*
- **O4** foreground pushes refresh the live status (session-id-guarded).
- **O5** Home pill relabels from server truth via two one-shot fetches.
- **O6** warning card renders LIVE_STATUS_COPY subtitles (no inline copy).
- **O7 (redesigned by owner)** the ENTIRE reminder ladder (T-30/10/5/0) is
  client-scheduled local notifications — dead-zone/outage-proof — with
  mirrored backend copy; the server keeps only the T-0 SMS. Ladder tests
  moved to jest; legacy server rows consumed as no-ops.
- **O8 (owner copy)** circle-emptied honesty: "Last Circle member opted
  out…" (tense follows the alert window; ALERTED excluded).
- **O9 (+two owner directives)** SOS cancels the prior ladder; local
  reminders self-check liveness at fire time (provable-stale only,
  fail-open); **SOS during a live check-in CONVERTS the session in place**
  (same row → PANIC, deadline now, location on — the circle gets everything
  gathered; MISSED/ALERTED get a fresh PANIC session instead).
- **O11 (owner redesign)** paywall draft restore is all-or-nothing: restore
  EVERYTHING (exact time + photo) unless the deadline passed or 30 min
  elapsed; a dead photo file prompts re-add instead of silently starting.
- **O12** stale "5s hold" comments corrected to 3s.
- **C3 (owner redesign — acknowledgement)**: the word is **Acknowledge**
  ("claim"/"on it" is gone, including the DB enum via migration
  `e5f6a7b8c9d0` and the renamed `alert_acknowledgement` service). Broadcast
  is **SMS-only** (no pushes): owner gets the NAMED SMS, every other active
  member the ANONYMOUS one; the acknowledger's identity is never revealed to
  the circle; the checked/grayed button is the entire acknowledgement UI
  (no badges/toasts/notices anywhere). Copy never claims "on their way".
- **C4** emergency push deep-links to /alert-details (fetch-on-miss fixed).
- **C5 (owner: baseline only)** PRG 303 on acknowledge + live-only 75s
  meta-refresh (no Ajax — zero-JS page by design).
- **C6** time-sensitive interruption level on CIRCLE_ALERT/RENUDGE +
  entitlement staged in app.config.js (**activates with the 1.1.0 native
  build**).
- **C8** alert-page label contrast fixed to WCAG AA.

## 3. Owner decisions (2026-07-19)

1. **Single-contact acknowledgement — un-gated**: the button shows for every
   recipient (reverses the flow-review >1 coordination gate); the
   acknowledgement is primarily the owner's "a human saw this" signal.
2. **Never-resolved incidents**: public page goes neutral after
   `ALERT_PAGE_MAX_AGE_DAYS` (7) — "no longer current / contact law
   enforcement"; the data is deliberately **never auto-purged** (potential
   evidence; pinned by test); disposal/closure are human decisions via the
   admin stuck-session actions ("close as false alarm" → CANCELLED, no
   all-clear claimed or broadcast; "purge data now").
3. **Link previews**: the page title is the name-free "Safety Alert Details".

## 4. Explicitly skipped (owner decisions — do not re-propose without cause)

- **O10 accessibility** (SOS control labels/alternate activation, status
  announcements) — skipped permanently, 2026-07-19.
- **C7 localization** (per-contact language for SMS + page) — skipped.

## 5. Explicitly rejected (unchanged from the review)

- Shortening the alert link (UUID is the access token; entropy matters).
- Notifying circle members at session creation (silence is correct).
- Dropping the T-5 local reminder (now part of the client-owned ladder).
- Mapping CANCELLED to the all-clear card (CANCELLED now has its own honest
  "no longer current" treatment instead).
