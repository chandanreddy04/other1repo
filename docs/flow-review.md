# User-Flow Effectiveness Review — Consolidated Report

**Date:** 2026-07-02
**Method & confidence:** Four parallel code-mapping passes over every user flow (auth/onboarding,
sessions/SOS, circle/alerts, gating/payments), followed by a manual line-by-line verification of
every load-bearing claim (all held), a fifth pass over previously unmapped flows (recipient side,
settings, group plan, photos, push routing, history), and an external research round
(~260 searches over competitor docs, FCC/CTIA primary documents, Apple/Google policy pages,
academic literature; 8/8 spot-checked claims confirmed against primary sources). Code claims below
carry `file:line` refs and were verified in this repo. External claims carry source URLs.
Nothing here is legal advice.

---

## Part 1 — Findings, organized by the situation the user is in

The organizing question: *does the alert reach someone who can help, at the moment it matters?*
The most serious findings share one shape — **the app reassures while silently doing nothing.**

### Situation A: "I feel unsafe right now" (SOS)

**A1. A trial-exhausted user's SOS shows a fake alarm and alerts no one.** `POST /sessions`
(both types) depends on `get_current_user_with_subscription` → 402 (`sessions.py:85`,
`deps/auth.py:77-79`). Mobile: `sendSOS` enqueues on *any* error including 402
(`useSessionStore.ts:232-241`); `flushSOSQueue` swallows all failures and retries forever
(`sosQueue.ts:38-39`); the alarm UI is deliberately kept (`(tabs)/index.tsx:74-83`) and the toast
says *"Connection's spotty"* even when the real cause is the paywall. The user sees an
active-looking alarm; nothing ever dispatches; they are never shown the paywall.

**A2. SOS requires a 5-second hold with no fallback and no 911 affordance.** The hold is the
confirmation (`CustomTabBar.tsx:69,101`); early release aborts silently. "Call 911" exists only
inside the failure-toast text.

**A3. Queued offline SOS only retries when the app is foregrounded** (`sosQueue.ts` flush is
called on Home mount). A locked, offline phone delivers nothing until reopened.

### Situation B: "Someone I love might be in trouble" (the contact)

**B1. Contacts who don't install the app are silently never alerted.** New members are created
`PENDING` (`crud/circle_of_trust.py:117,178`); dispatch queries `status=ACTIVE` only
(`session_tasks.py:216,278`); activation paths are in-app accept (`crud:126`), STOP-undo
(`sms_opt_out.py:209`) — **and, correction from follow-up verification: a web accept flow DOES
exist** (`POST /invitation/{code}/accept` behind web cookie-auth, `routes_htmx_profile.py:68`,
plus a `/invitations` page at `routes_web.py:181`). The real defect is that it's **orphaned from
the invite journey**: the invite SMS link lands on `circle_join.html`, which only says "Install
the app, then enter this invite code" (`circle_join.html:80`) and never mentions the web path.
The invite text promises "if I miss one, it'll contact you" — for a contact who reads it and
does nothing, that promise is false, and the owner sees them listed in their circle believing
they're covered. Fix is wiring (lander → web OTP login → accept), not new construction.

**B2. The alert text is unattributed and near-useless to a panicking recipient.** One template
for both alert types: `"{name} may need help. Please check on them immediately."`
(`notification_constants.py:20`, used at `session_tasks.py:59,64`). No service name, no location,
no address, no link, no callback number, no guidance. **SOS and a routine missed timer are
word-for-word identical to the recipient.**

**B3. A recipient with the app can look but not act.** Alert details show the person's phone as
plain non-tappable text (`alert-details.tsx:192-203`); no call/text buttons, no navigate, no 911,
no acknowledge. The acknowledge endpoint exists (`alerts.py:40-57`) and `api.acknowledgeAlert()`
is defined (`api.ts:611`) but no mobile screen calls it. **Correction from follow-up
verification: the web dashboard DOES have an acknowledge button**
(`routes_htmx_profile.py:253`) — mobile is the only side missing it, so this is
activate-existing-plumbing, not new construction. Nothing broadcasts *who* acknowledged, so no
circle member (or the owner) knows whether anyone else is responding (duplicated response, or
none).

**B4. All-clear works** (`sessions.py:195-213`) — the one recipient-side piece that matches
industry practice.

### Situation C: "I'm running late / I forgot" (the owner mid-session)

**C1. The app claims "your trusted contacts have been notified" before it's true.** The copy is
driven by the client clock (`active-session.tsx:67,225,363`) while the backend waits
`GRACE_PERIOD_MINUTES=2` (`config.py:166`) + worker cadence, and dispatch can fail/retry. The
owner relaxes; the circle may know nothing for minutes — or at all.

**C2. Owner pre-deadline reminders are push-only** (`notification_helpers.py:89-114`); a phone
with notifications denied (see D2) or in a pocket misses them all. The `minutes=0` reminder
renders "Your session expires in 0 minutes."

**C3. Extending is more friction than it should be**: no presets on the live create screen
(±30-min stepper only, `create-session.tsx:100-135`; an 8-hour outing = 12 taps; silent no-op at
bounds), a confirm dialog on every extend (`active-session.tsx:175-205`), and no extend action in
the reminder push itself. Once the session tips MISSED, extend is blocked (`sessions.py:218-244`)
— correct, but it makes the pre-deadline reminder the critical moment, and it's the weakest link.

### Situation D: "I just downloaded this" (first run)

**D1. Interrupted onboarding is never resumed.** `index.tsx` gates only on `isAuthenticated`;
`ONBOARDING_COMPLETED` is written (`onboarding.tsx:45`) and read nowhere. Quit mid-onboarding →
land in the app forever with no location and no notification permission, silently.

**D2. Permission denial is invisible.** Denying notifications or location in onboarding advances
silently; a session then runs with location tracking silently disabled
(`useSessionStore.ts:175`), and nothing tells the owner or offers a Settings deep link. Contacts
permanent-denial dead-ends in a toast with no Settings link (`contacts.ts:97`).

**D3. The free trial is invisible and the paywall lands at the worst moment.** No trial
surfacing anywhere pre-session (only `profile.tsx:149` after the fact); the 402 lands *after*
the user has filled the whole form to arrange safety for an outing; after paying in the external
browser they land on `/` (`subscribed.tsx:35,61`) and the session they were building is lost.

**D4. A returning signed-out user replays the full 3-page intro carousel** before reaching login.

### Situation E: Reliability plumbing that undermines everything above

**E1. Push tap-routing is dead — twice over.** `handleNotificationResponse` bodies are comment
stubs (`notifications.ts:155-169`), *and* the `type` keys checked (`session_reminder`,
`emergency_alert`, `missed_session`) match **zero** of the types the backend actually emits
(`session_expired`, `session_expiring`, `all_clear`, `alert_triggered`, …, verified in
`notification_helpers.py` / `session_tasks.py`). Consequences: tapping any push just opens the
app wherever it was, and the escalate-tracking-on-alert branch has never fired from a real push.

**E2. Data-retention copy contradicts behavior.** `create-session.tsx:229` promises deletion
"24 hours after your session ends"; `cleanup_expired_data` purges photos + location immediately
on the next tick after completion (`session_tasks.py:478`). (The welcome carousel is correct.)
Immediate deletion is also a product decision: nothing is recoverable if someone marked safe
under duress.

**E3. Orphaned/dead surfaces:** legacy create screen `(tabs)/session.tsx` (reachable via
`active-session.tsx:107`) dead-ends on 402 with a toast instead of the paywall; session history
is dead plumbing (store loads `sessions`, no screen renders them); group-plan lapse gives
members a silent 7-day grace with zero member-facing UX (`webhooks.py:300-325`); no notification
/ privacy preferences exist anywhere in settings; `alert-details` falls back to "Alert not found"
on cold-start deep links (in-memory store lookup, `alert-details.tsx:44,81-92`); profile version
hardcoded "1.0.0".

**E4. Config gap now fixable:** `APP_INFO.SMS_NUMBER` is empty (`config.ts:222`), which degrades
the opted-out-contact recovery dialog to a dead-end Cancel (`useContactsScreen.ts:170-189`) —
set it to the new toll-free number (+18774146630), along with backend `SMS_DISPLAY_NUMBER`.

---

## Part 2 — What the outside world says (evidence per decision point)

### 2.1 Should SOS be behind the paywall?

Industry: **the line is drawn at professional response, not at alerting.** Noonlight's panic
button *including 24/7 professional dispatch* is free (noonlight.com/noonlight-app); Life360
free-tier SOS pushes the Circle and texts emergency contacts, with paid tiers adding human
dispatch (support.life360.com article 23053474049687); Snug's missed-check-in SMS to contacts is
free with a paid human-dispatcher tier (snugsafe.com/for-emergency-contacts); iOS Check In and
Pixel Safety Check do the whole loop for $0. Counterexamples exist (bSafe, invisaWear are fully
paywalled and pass review) — so a paywalled SOS is *store-legal*, but it sits against category
norms and against free OS features, and Google Play's Misleading Claims policy (answer 9888077)
plus Apple 1.4.1 mean marketing/screenshots must never imply a free or 911-connected panic
button. Apple 5.1.5: don't frame location features as "emergency services."

### 2.2 Contacts without the app

**SMS-only emergency contacts are the industry norm, and a one-tap web accept is not.** Snug,
Pixel Safety Check, Iamfine, My SOS Family, Life360 (and historically Kitestring, which had no
app at all) alert contacts by plain SMS with no install. The common consent floor is: (1) an
immediate "you've been added by [name] — all is well" text with context + STOP language,
(2) alerts only on real events, (3) an all-clear follow-up, (4) STOP honored absolutely.
Verified example (Snug): *"You are Annie's emergency contact on Snug (don't worry – all is
well)"*.

Compliance shape (US): TCPA has an emergency-purposes exception (47 CFR §64.1200(f)(4); FCC
16-88 fn.76 — messages limited to the emergency, no marketing, relevant to the called party) but
it is narrow, untested for consumer apps, and **carriers don't honor it** — CTIA's 2023
Messaging Principles contain no emergency exception and Twilio states there are no A2P
exceptions. The FCC-blessed design that fits Circle of Trust is **intermediary consent**
(GroupMe ruling, FCC 14-33: intermediaries may convey consent provided by others, platform
liable if false) — i.e., the owner attests, and the platform immediately sends the contact a
confirmation SMS with STOP/HELP *before* any alert, logged as the consent record. For *invites*,
the app's current pattern (owner's native SMS app) is exactly the *Cour v. Life360* safe harbor
— keep it. STOP must override even "emergency" sends (*Farhat*, 2022) — the existing
`sms_opt_out.py` cascade is correct. Register the alert campaign as a standard use case
(Account Notification / Security Alert), not TCR "Emergency" (that's for public emergencies).

### 2.3 What the alert text should contain

Verified real-world copy converges on a structure: **service name first** ("IAMFINE ALERT:",
"on Snug", "via Kitestring") → first name → plain-language reason → **street address before the
map link** (Red Panic Button's guide: recipients read the address and call before tapping) →
maps link + battery → an instruction verb. Verified examples: Iamfine: *"IAMFINE ALERT: [Name]
did not respond to today's check-in call. Please check on their welfare."*; Google Emergency
Sharing: *"You're receiving this message because you're an emergency contact for [Name]… Please
call or text [Name] directly for updates."* Notably **none of the verified copy says "call
911"** — the instruction ladder is call/text the person → check on them → (implicitly)
authorities with the last-known address. Two mechanics worth stealing: Iamfine lets a contact
resolve on the user's behalf and posts it to the circle; My SOS Family lets the first responder
"claim" the SOS so others know who's on it. Kitestring let users pre-write the alert body
(home address, habits) — context the app shouldn't guess.

### 2.4 Timer UX

Consumer apps converge on **coarse presets + one-tap extension from the reminder itself**
(iOS Check In: +15/30/60 from the Check In details; travel mode proactively offers more time
when you're "not making progress"). **Grace periods are universal** (Kitestring 5 min, Snug
10 min, iOS 15-min respond window) and are the industry's main false-alarm control; the
escalation canon is: nag the owner hard across channels → grace → alert circle with context →
(paid) human monitoring. Notify the circle of extensions rather than going dark. False-alarm
social cost is a documented abandonment driver, as is unreliability (46 of 67 safety apps failed
when tested — Maxwell et al. 2020; "you could do the same things without the app" — Doria et
al. 2021). Life360's retention comes from passive ambient value; a session-based app has none —
**reliability and the positive "made it home" moment are the retention features.**

### 2.5 Permissions

Hard rules: Apple **5.1.2(i)** — an app may not *require* users to enable push/location to
access functionality (permission walls are a written violation; Citizen's wall is documented in
a CHI 2023 paper as an anti-pattern); Apple 4.5.4 (push must not be required to function);
iOS "Always" location arrives via a system-timed deferred prompt and the upgrade prompt fires
exactly once; Android 11+ background location is a separate Settings flow requiring a prior
educational screen, plus a Play Console declaration + video. The best observed denial pattern is
Life360's: never block — degraded-status chips ("Location Permissions Off") with fix-it deep
links. Sequencing: contextual soft-ask before every native prompt (notifications at first
session creation; When-In-Use location at first session start). **Shipping v1
foreground-location-only skips the entire background-location compliance surface** and loses
little, since alert dispatch is server-side. Time Sensitive notifications are self-service;
**Critical Alerts** (bypass mute — Life360 has it for SOS) needs an Apple entitlement request —
apply early. Live Activities fit the running-countdown perfectly.

### 2.6 Monetization structure

Price bands: software-only alerting $3–10/mo (the app's $5 is mid-band); humans/dispatch
$10–25/mo; $10 group undercuts Life360 Gold ($14.99) but Life360's free tier is far richer.
**"1 free session ever" has no living precedent** — the only session-limited free tier was
Kitestring's *3 free trips per month, recurring* (+1 free contact). Everything else is a
time-boxed full trial (bSafe 7-day) or permanent-free-core + paid dispatch. One notable outlier:
bSafe's **$0.99 24-hour pass** (episodic micropayment for a night out — no current US
competitor offers this). The contact-facing experience is free everywhere — contacts are the
acquisition channel.

**iOS payments risk:** base 3.1.1 still mandates IAP for unlocking features; the US carve-out
(3.1.1(a), May 2025) permits external purchase links at currently-0% commission (post-Epic;
SCOTUS granted cert June 30 2026 — commission likely returns). But **zero-IAP with an in-app
"Subscribe" CTA going only to Stripe has no verified approval precedent for a non-reader app**
(safety apps don't qualify for the 3.1.3(a) reader category). Risk-ordered options: (a) IAP +
equally-prominent Stripe link; (b) web checkout + login unlock, no in-app CTA (the tolerated
Netflix pattern); (c) Stripe-link-only — literal-text permitted, reviewer-discretion exposed.
Google Play US is affirmatively solved (alternative billing allowed since Oct 2025; a 9–20% fee
is proposed but unapproved). Model the P&L at ~10–15% platform take. Also: Apple 5.1.1(ix) —
submit from a legal entity, not an individual account.

---

## Part 3 — Recommendations (tiered, evidence-linked)

### Tier 0 — the promise must not silently break

| # | Change | Grounding |
|---|--------|-----------|
| 1 | **Ungate SOS from subscription** (and let alerts for an already-running session dispatch regardless of billing state). At minimum: treat 402 on SOS as terminal — never the fake alarm; show an honest "we could not send this — call 911" state. Fix the misleading "Connection's spotty" toast for non-network errors. | A1; §2.1 (Noonlight/Life360/Snug norms; misleading-claims policies) |
| 2 | **Make SMS-only contacts first-class and alertable.** On add: platform sends a "you've been added by {name} — all is well" confirmation SMS (Twilio) with STOP/HELP, logged as the consent record (GroupMe intermediary-consent shape); membership becomes ACTIVE unless STOP. Keep P2P native-SMS invites (Life360 safe harbor). Surface PENDING-vs-ACTIVE honestly to the owner ("Mom won't be alerted yet"). | B1; §2.2 |
| 3 | **Rewrite the alert messages**: service name first; differentiate SOS from missed check-in; include expected-return time, street address + maps link, battery, callback number, and an instruction ("Please call or text them"). Add an optional user-authored note (Kitestring). Keep all-clear. | B2; §2.3 |
| 4 | **Make "notified" true**: show "notifying your circle…" until server-confirmed dispatch, then confirm. Widen the post-deadline owner-nag: aggressive multi-channel owner reminders during a 5–10 min grace before the circle alert (industry norm), incl. an SMS fallback for the final reminder. Fix the "0 minutes" string. | C1, C2; §2.4 |
| 5 | **Fix push plumbing**: align mobile `type` keys with backend payloads, implement tap-routing (reminder → active session; alert → alert details), and put **extend actions (+30/+1h) in the reminder push itself**. | E1, C3; §2.4 |

### Tier 1 — first-run and recipient effectiveness

| # | Change | Grounding |
|---|--------|-----------|
| 6 | Resume interrupted onboarding; on any permission denial show a Life360-style status chip + Settings deep link instead of silent advance; never wall (Apple 5.1.2(i)). Consider shipping v1 foreground-location-only. | D1, D2; §2.5 |
| 7 | Give recipients actions: tappable call/text on alert details, an "I'm on it" acknowledge (endpoint already exists) broadcast to owner + other members (My SOS Family claiming). | B3; §2.3 |
| 8 | Kill the legacy create screen; add duration presets + reminder-push extend; drop the extend confirm dialog. | C3, E3 |
| 9 | Restructure the free tier: recurring N sessions/month (Kitestring model) or a 7-day full trial; surface it ("2 free sessions left this month"); resume the pending session after payment; consider a $0.99 night pass. Decide the iOS payment posture (IAP+link vs web-unlock). | D3; §2.6 |

### Tier 2 — trust and polish

10. Fix the 24h-vs-immediate retention copy (and decide if immediate is the intent — duress
    recoverability); member-facing group-plan lapse UX; session history screen (plumbing
    exists); returning-user fast path past the carousel; notification preferences; alert-details
    cold-start fetch; set `SMS_NUMBER`/`SMS_DISPLAY_NUMBER` to +18774146630; apply for the
    Critical Alerts entitlement; add a Live Activity countdown; version string from config.

### Open product decisions

> Superseded — resolved in Part 4 below (2026-07-02 decision round). Only the four items in
> §4.4 remain open.

---

## Part 4 — Decision round (2026-07-02): owner responses, recommendations, remaining opens

### 4.1 Corrections from follow-up verification

Two Part-1 findings were amended after the owner challenged them (amendments applied inline
above):

- **B1**: a web accept flow *does* exist (`routes_htmx_profile.py:68` + `/invitations` page) but
  is unreachable from the invite journey — the lander only says "install the app." Fix = wiring.
- **B3**: the web dashboard *does* have an Acknowledge button (`routes_htmx_profile.py:253`);
  only mobile lacks it. Fix = activate existing plumbing + broadcast who claimed.

### 4.2 Decision register (locked by owner)

| Item | Decision |
|---|---|
| A1 / 2.1 / 3.1 | **SOS is free, always.** Dispatch regardless of subscription; never a fake alarm; honest failure state. |
| A2 | 5-second hold is intentional — **keep as is**. |
| A3 | **Fix**: SOS retry must not require the app to be foregrounded. |
| B1 / 2.2 / 3.2 | **Support contacts without the app**, with **explicit acceptance required** (web form or app — no auto-activation): wire the invite lander to the existing web accept; SMS-based alert delivery; SMS confirmation on acceptance. Also instruct circle members to add our number as a **"favorite"** so alerts bypass Do Not Disturb. |
| B2 / 3.3 | **Rewrite alert copy** per §4.3; **differentiate SOS from missed check-in**. No street address available (no reverse geocoding exists — verified); include the rest; alternatives in §4.3. |
| B3 / 3.7 | **Implement**: recipients can call the person, navigate, and call 911 from alert details; add acknowledge/claiming. |
| C1 / 3.4 | **Align client and server** — the "notified" state must reflect actual dispatch (concrete design in §4.3). |
| C2, C3 | Owner asked for recommendations — given in §4.3. Extend-friction fixes (presets, one-tap extend, push actions) **approved** via 3.6. |
| D1 | **Resume interrupted onboarding, always.** |
| D2 / 2.5 | **Make permission gaps visible** with corrective controls (status + fix-it/Settings deep links). |
| D3 | **Resume the drafted session after payment** (persist draft → prefill create-session on return). |
| D4 | **Welcome carousel only if the app has never been logged in before.** |
| E1 / 3.5 | **Fix push plumbing** (type alignment + tap routing + foreground escalation) — concrete design in §4.3. |
| E2 / 3.10 | **Retention: 7 days after session end, across the board**, and the user can extend **7 days at a time** (repeatable). Update all copy to match. |
| E3 / 3.8 | Verify each dead surface, then **delete if unnecessary, activate if needed** — dispositions in §4.3. |
| E4 | **Set the number** (+18774146630) in app config / `SMS_DISPLAY_NUMBER`. |
| 3.6 | **Implement**: kill legacy create screen; duration presets; reminder-push extend; drop extend confirm dialog. |
| 3.9 | **$0.99 24-hour pass: yes. No additional free sessions** (keep 1-ever trial). |

### 4.3 Recommendations and concrete designs (answers to the owner's asks)

**B2 — why SOS should read differently from a missed timer.** They are different events with
different confidence levels. A missed check-in is a *passive inference*; most are benign
(forgot, phone died, running late) — false-alarm cost is the category's documented #1
abandonment driver. An SOS is a *deliberate act*: the user physically held a button for 5
seconds, so false positives are ~zero by design. Identical wording forces the recipient to
either treat every forgotten timer as a panic (alarm fatigue → ignored alerts) or every panic
as a "maybe" (dangerous delay). **Final copy (owner-approved, 2026-07-02):**

- Missed: `Made It Home: {name} hasn't checked in, and expected to be back by {time}. Please
  check on them: [number]. Details: [link]`
- SOS: `Made It Home EMERGENCY: {name} activated SOS and needs help now. Please check on them:
  [number]. Details: [link].`

Message content beyond the template (per owner, 3.3 + follow-up): intended destination **when
available**; battery level **only when critically low** (<5%, `LOW_BATTERY_ALERT_THRESHOLD`) —
a dying phone is a safety signal, a half-full one is noise (owner reverted the brief
"battery whenever available" reading on 2026-07-02). Location and battery are
permission-dependent and may be absent; the SMS must degrade gracefully. Location information
lives on the details webpage (the tokenized alert page), not in the SMS body. *(Session photos:
removed 2026-09-05.)*

**C2 — owner pre-deadline reminder ladder.** (1) Replace `[30, 15, 0]` with `[30, 10]` plus a
distinct at-deadline message: *"Time's up — check in now, or your circle will be alerted in ~N
minutes"* (kills the "0 minutes" string, creates urgency). (2) Extend actions (+30m / +1h)
directly in the reminder push (notification action buttons). (3) One **SMS fallback to the
owner** during the grace window — SMS lands even with notifications denied or DND; costs one
message per genuinely-late session. (4) Widen grace 2 → 5 min to make room for the ladder
(industry norm is 5–10; tradeoff: circle alert lands ~3 min later). (5) Later: Apple Critical
Alerts entitlement + Live Activity countdown.

**C3 — create/extend friction.** Owner's call: *"30m is enough — don't overcomplicate."*
Resolved as: **no preset chips** on the create screen (the ±30m stepper stays, with disabled
buttons at bounds instead of silent no-ops); **extend is a single +30m action everywhere** —
one-tap on the active-session screen (undo-toast, no confirm dialog) and a single "Extend 30
min" action button on the reminder push (supersedes the +30m/+1h pair floated in C2).

**D3 — resume-after-payment design.** Persist a session draft (destination, toggles, photo)
when routing to the paywall; after `/subscribed` confirms, land on create-session prefilled
(recompute the return time — minutes have passed) with one tap to start.

**3.3 — location content without street addresses.** Verified: no reverse geocoding exists
anywhere in the codebase; available data = lat/long + user-typed destination. **v1**: maps link
(`maps.google.com/?q=lat,lng`) + destination text ("was headed to Central Park") +
expected-return time + battery, plus a **tokenized web alert page** (required anyway so SMS-only
contacts can see map/details/claim) linked from every alert SMS. **v2**: server-side reverse
geocoding at alert time (AWS Location Service, ~$0.50/1k, one call per alert) to add the
human-readable address recipients read before tapping links.

**3.4 — aligning "notified" (C1).** Server session status becomes the only source of truth on
the active-session screen. Poll the session once inside the final ~5 minutes, then render:
`ACTIVE past deadline` → *"Time's up — check in now. Your circle will be alerted in ~N min"*
(grace countdown); `MISSED` → *"Notifying your circle…"*; `ALERTED` → *"Your circle has been
notified."* Add an owner push when the backend promotes MISSED→ALERTED (transition already
exists) so a backgrounded phone updates too. The client clock never claims "notified."

**3.5 — push plumbing (E1).** Root cause: mobile handlers were written against guessed type
names; backend later shipped real ones; nothing enforced agreement. Fix: (1) a checked-in
`shared/notification-types.json` as single source of truth — backend test asserts every emitted
type is listed; mobile test asserts every listed type is handled; drift becomes a test failure.
(2) Implement tap-routing per type (reminder → active session; `alert_triggered` → alert
details; `all_clear` → alerts tab; circle events → contacts; account events → profile), reusing
the existing pending-route pattern for cold starts (`getLastNotificationResponseAsync` on
launch). (3) Fix foreground escalation to match real types (`alert_triggered`,
`session_expired`). (4) Notification action buttons for extend (per C2).

**E3 — dead-surface dispositions (verified).** Legacy `(tabs)/session.tsx` → **delete**
(redundant duplicate; approved via 3.6). Session-history plumbing → **activate** — it is now
load-bearing: the 7-day-retention-with-extension decision (E2) needs a surface where the owner
sees past sessions and taps "keep 7 more days." Acknowledge → **activate on mobile** (web
already has it; add claim broadcast). Group-plan lapse → **add the missing member-facing
copy** (small). Notification preferences → **defer**. The app functions without them today, but
three of five are now required by other decisions in this round.

**2.4 — viability, honest read.** The *job* is validated by the strongest available signals:
Apple and Google both built check-in timers into their OSes; Kitestring went viral on this exact
loop; Snug survives on it. The *business* is where the category kills apps: (1) **free OS
competition** — but iOS Check In is iMessage-only, iOS-17-on-both-ends, single-recipient; the
wedge is mixed Android/iPhone households, SMS reach to any phone, multi-contact circle with
escalation and claiming. That wedge is real. (2) **Retention** — episodic products churn;
Life360 survives on passive ambient value this app doesn't have. The hedges chosen here are the
right ones: the group plan (the payer is the worrier, not the user — Life360's actual model)
and the $0.99 pass (matches episodic reality instead of fighting it). (3) **Reliability** — 46
of 67 tested safety apps simply didn't work, and users leave on the first misfire or false
alarm; this review found exactly those defect classes in the current build, so the unglamorous
fixes queued here *are* the product strategy. Net: sound concept, narrow-but-real wedge;
existential risk is execution quality, not demand.

**2.6 — clarifications.** *Contact-facing experience* = everything a circle member touches
without paying: invite, alert SMS/push, alert-details view, acknowledge/claim, all-clear. Keep
it free forever — every alert and invite is the acquisition channel; degrading it breaks the
growth loop. *The iOS risk* = yes, **App Review rejection**: rule 3.1.1 still requires IAP for
unlocking digital features; the 2025 US carve-out allows external payment *links*, but an app
with zero IAP whose subscribe button goes straight to Stripe has no known approval precedent
outside "reader" apps (a safety app is not one). A reviewer can reject at first submission or
any later update. Options, safest first: **(a)** subscribe on the website only — no purchase
CTA in the app, the app just unlocks on login (tolerated Netflix pattern); **(b)** add StoreKit
IAP (15% small-business rate) alongside Stripe web checkout; **(c)** ship Stripe-link-only and
accept reviewer-discretion risk. Recommendation: (a) first, add (b) if conversion suffers. Also:
Apple 5.1.1(ix) expects safety apps from a **legal entity** developer account, not an
individual.

### 4.4 Final decisions (resolved 2026-07-02 — all items closed)

1. **Grace window 2 → 5 minutes:** YES.
2. **Owner SMS fallback at the deadline:** YES (one Twilio message per genuinely-late session).
3. **iOS payment posture:** **web-only subscribe** — no purchase CTA in the iOS app; the app
   unlocks on login (Netflix pattern).
4. **SOS sessions excluded from the free-trial count:** YES — `get_sessions_used_count` must
   skip SOS sessions.

> **Addendum (2026-08) — subscription management surface.** Refines decision 3
> above. Purchase and sponsorship stay native (plan selection in `subscribe.tsx`
> → external Stripe checkout under the US carve-out; sponsorship needs the device
> address book + native SMS, which a browser can't do). **Management** is now
> native too for the common actions: the Profile "Subscription" section is two
> rows — a constant-height **Manage Subscription** row and the referral row. Cancel
> and reactivate are native (`PATCH /subscriptions {cancel_at_period_end}` →
> `subscription_service.get_cancelable_subscription`, self-paid recurring only);
> only **change-plan** and **payment-method** open the Stripe Customer Portal in
> the external browser. Routing (`mobile/utils/subscriptionDisplay.ts`
> `getManageRoute`): not-subscribed/trial/promo/referral/day-pass → native
> `/paywall`; individual self-paid → `/manage-subscription`; gift/comp →
> `/manage-subscription` (status-only); group owner/member → `/group-plan` (owner
> gets the same native cancel/reactivate + portal link there). A web "manage
> everything" page was considered and rejected: group member-management is
> inherently native and Stripe has no single hosted page for purchase + change +
> cancel.

### 4.4b "Favorite our number" — DND-bypass guidance for circle members

Owner requirement (from 2.2): circle members should be instructed to save the Made It Home
number so alerts break through Do Not Disturb. Platform mechanics differ from the folk
understanding of "favorites":

- **iOS**: Favorites only whitelist *calls*. For **texts** to break through Focus/DND/silent,
  the contact card needs **Emergency Bypass** enabled on the *Text Tone* (Contacts → Edit →
  Text Tone → Emergency Bypass). Guidance must say that, not just "favorite us."
- **Android**: save the contact, **star** it, and allow starred contacts in DND settings
  (Settings → Do Not Disturb → People → Messages → Starred contacts).

Placement plan: (1) a **downloadable vCard** (`.vcf` with the Made It Home contact) + the
per-platform steps on the **web accept success page**; (2) the same instruction on the in-app
accept success screen ("You're in!"); (3) one line in the post-acceptance welcome SMS ("Save
this number so alerts reach you"); (4) a tip card on the Circles tab. The vCard makes step one
one-tap; Emergency Bypass/starring remains a manual toggle we can only instruct, not automate.

### 4.5 Implementation phases

> **STATUS: ALL THREE PHASES SHIPPED 2026-07-02** (commits `6505eaf..96e1513`).
> Additional latent defects found and fixed during implementation: mobile
> session creation 422'd on every attempt (legacy payload fields), extend
> 405'd (wrong method + field), the at-deadline reminder was never scheduled
> (`minutes <= 0` skip), and push type keys matched nothing the backend
> emitted. Contract/regression tests now pin all of these.

- **Phase 1 — safety-critical:** SOS ungate (+ honest failure state + background retry);
  push-type alignment + tap routing; server-truth "notified" state; alert copy rewrite with SOS
  differentiation; set +18774146630 (E4).
- **Phase 2 — contacts:** invite lander → web accept wiring; SMS-only contact activation with
  acceptance + confirmation SMS; DND "favorite our number" guidance; call/navigate/911 +
  acknowledge/claim on alert details; tokenized web alert page.
- **Phase 3 — first-run & monetization:** onboarding resume; visible permission gaps with
  fix-it controls; session-draft resume after payment; carousel only pre-first-login; create
  presets + one-tap extend + push extend actions; delete legacy screen; $0.99 day pass; 7-day
  extensible retention + history screen; group-lapse copy; retention copy fixes.
