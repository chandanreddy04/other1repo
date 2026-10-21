# Made It Home — Manual Test Plan (Production / Real-World)

This is the checklist to run against a **fully deployed** environment (staging
first, then production smoke). It deliberately concentrates on what automated
tests **cannot** cover: real SMS/push delivery, live Stripe, time-based worker
behavior, native device permissions, universal-link interception, and
cross-device flows. The unit/integration suites (backend pytest, the mobile
jest tests, tsc/eslint) already cover business logic and pure functions — don't
re-test those here; test the seams with the real world.

This is a **personal-safety app**: the overdue-check-in → alert path
(§4) and SOS (§3) are P0. If nothing else gets tested, test those, on two real
devices, end to end.

> **Maintenance.** This is a **living checklist, updated every release.** Whenever
> a change lands that automated tests can't fully verify — anything visual,
> native, on-device, cross-device, time-based, or dependent on a real external
> service (SMS/push/Stripe/links) — add its device-verification items here in the
> same PR. The goal is that running this list before a release build catches
> exactly the things the jest/pytest/tsc gates cannot.

---

## 0. Prerequisites & test rig

- **Two real phones**, one iOS and one Android, each able to **send and receive
  real SMS** and push. Label them **OWNER** and **CONTACT**. A third number
  (CONTACT-2) helps for multi-contact and family cases.
- App installed as a **real signed build** for each environment:
  - Universal links, push, background location, biometrics, Live Activities,
    and Apple/Google Pay **do not work in Expo Go** — use a dev client / EAS
    build (`development`/`staging`/`production` profile, `eas.json`).
  - Confirm the build targets the intended backend: `EXPO_PUBLIC_APP_ENV`
    drives `WEB_ORIGINS` (`mobile/constants/config.ts`). The **EnvBanner**
    must show on staging/dev and be **absent on production**.
- **Carrier/Twilio**: the OWNER/CONTACT numbers must not have previously texted
  STOP to the Made It Home number (or START them first). US numbers (E.164).
- **Stripe**: know whether the env is in **test mode** (use test cards) or
  **live mode** (real charges — use a real card and refund, or a low-value
  plan). Have Apple Pay / Google Pay set up on the devices.
- **Backend access** for verification: the **admin panel** (`/admin`, requires
  `is_admin=true` on your user), plus log/Bugsnag access. Stripe Dashboard
  (events + webhook delivery log). Twilio console (message + delivery logs).
- Know the configured timings before testing time-based flows (don't assume —
  read them): overdue grace, `ALERT_REMINDER_TIMES`,
  `ALERT_REMINDER_DELAY_MINUTES`, `GROUP_PLAN_GRACE_DAYS`,
  `SMS_UNSUBSCRIBE_GRACE_DAYS`, deletion grace days, referral credit days.
  The worker (`worker_tick.py`) runs ~once/minute — time-based effects appear
  within a tick or two, not instantly.

> Throughout: ☐ = check it works; record device/OS, build, env, and result.

---

## 1. Authentication & OTP (live SMS)

- ☐ Request OTP on a fresh number → **SMS arrives** within seconds; code works.
- ☐ Resend OTP → respects the cooldown timer shown in the UI; second code works.
- ☐ Wrong code → inline error; too many attempts → lockout/limit behaves.
- ☐ Rate limiting: rapid repeated OTP requests from one IP get throttled
  (auth limit is tighter than the global 60/min).
- ☐ **iOS auto-fill** of the SMS code from the keyboard suggestion works.
- ☐ Login on an **existing** user → lands on home; **new** user → the required name
  step (`/account/profile`, no back) → onboarding.
- ☐ OTP delivery while roaming / weak signal (best-effort) — note latency.
- ☐ Token persistence: kill & relaunch → still logged in (tokens in SecureStore).
  Reinstall → tokens gone, must re-auth.

### Opt-out (STOP/START) — carrier-level, test carefully
- ☐ From CONTACT's phone, text **STOP** to the Made It Home number → carrier
  confirmation arrives; that contact is **removed from all circles** they're in
  (verify in admin: status `OPTED_OUT`), and any OWNER they back up gets a
  "contact unavailable" push.
- ☐ OWNER tries to **add** a contact who has opted out → blocked with a clear
  message (not a silent failure).
- ☐ The opted-out number tries to **request an OTP** → gets the "text START to
  …" message, not a silent dead end.
- ☐ Text **START** → re-subscribed; memberships restored to ACTIVE in-place;
  OTP works again.
- ☐ "Soft-stop" phrase (e.g. "please stop") → gets the one-time explainer SMS,
  and not again within the cooldown window.

---

## 2. Circle of Trust

- ☐ Add an existing app user as a contact → they receive an **invite SMS**
  (no in-app invitation — Circle members use mobile web only, owner decision
  2026-09-22).
- ☐ Add a non-app contact from the phone book (contacts permission prompt
  appears the first time) → invite SMS sent.
- ☐ CONTACT accepts via the web lander (`/circles/{code}`, from the invite SMS
  link) → becomes ACTIVE; OWNER sees them in the circle; CONTACT gets a
  welcome SMS.
- ☐ Hit the **contact limit** (the configured max) → adding beyond it is blocked.
- ☐ Try to remove a contact **while a session is active** → blocked.
- ☐ Nudge a pending contact → reminder SMS sent.

---

## 3. Sessions — Check-in & SOS

### Check-in
- ☐ Create a check-in with a destination + return time; quick-presets and the
  +/- time picker behave.
- ☐ **Access gating**: a user with no subscription and no free trial left is
  blocked at creation with the `/plans` sheet (402 path). On a small phone (or
  with large accessibility text) the `/plans` options step SCROLLS — all four plan options
  and the footnote are reachable (2026-07-19 fix). A user on free trial /
  paid / gift / referral credit / group plan can create. Verify each access
  source lets you in (see §7 priority order).
- ☐ Toggle location sharing on; capture an **outfit photo**
  (camera + library both work, permission prompts appear).
- ☐ Session screen (live mode) shows a live countdown; Live Activity / Dynamic
  Island appears on iOS; Android shows the foreground/persistent notification.
- ☐ **Live session clock card layout** (2026-07-19): clock, then `ETA hh:mm`,
  then the −30m/+30m pills BELOW (same layout as the Home card); pills hidden
  once escalated; −30m disabled inside the 30-min minimum lead.
- ☐ **Session Details map** (MapLibre + OpenFreeMap — NATIVE, needs the
  1.2.0+ build): tiles load on BOTH iOS and Android (no key configured
  anywhere — a blank gray map is a regression); the teal trail grows as you
  move; the latest position is a **pulsing blue dot**.
- ☐ **Stale dot**: force-stop location updates (kill the app + revoke
  location, or airplane-mode the phone) and keep the screen open on another
  device/admin — after >15 min the dot turns **static gray** and the caption
  flips to "No location update since …" WITHOUT reloading the screen; a fresh
  fix flips it back to pulsing blue.
- ☐ **Tile failure degrades**: with no connectivity the map area shows the
  placeholder / stale tiles — the screen itself must never block or crash.
- ☐ **Pictures in Session Details**: the outfit photo renders under "Outfit"
  (no other session pictures exist — background photo discovery was removed
  2026-09-05).
- ☐ **Subheading tense**: "Shared with your Circle if you miss check-in"
  pre-deadline → "Sharing with your Circle" once overdue or SOS.
- ☐ Battery row shows "No reading yet" at session start, then a real % after
  the first gather tick.
- ☐ **Extend** the session → deadline moves; reminders reschedule (old reminders
  don't fire late — see §5).
- ☐ **Check in (complete)** before the deadline → session COMPLETED; no alerts;
  circle is NOT alerted.
- ☐ **Session History list** (2026-07-19): Account tab → Session History. Each row
  has **no status indicator**. A completed session reads
  **"Ended {date} · {time}"** and the time matches the summary's "Marked safe
  at {time}". A cancelled session also reads "Ended …". A still-active session
  reads **"Started …"** (never "Ended") and shows **no** data-state line. The
  data line is a single word — **"Data deletion pending"** while data is held,
  **"Data deleted"** once purged — with **no dates** and **no "Keep 7 more
  days" button** (extend lives on the summary, below). An unresolved
  missed/alerted row must NOT read "Data deleted".
- ☐ **Tap → summary link** (2026-07-19): tapping a completed/cancelled row
  actually opens the Session Summary (this navigation was previously dead —
  the route was unregistered). Every row — live or ended — opens the same
  `/sessions/{id}` screen, which renders live mode for an active row.
- ☐ **Session Summary** (2026-07-19): tap the completed session in History →
  summary shows "✓ Marked safe at {time}", a "Xd Yh" countdown to data
  deletion with the deletion date under it, and ±7d pills. `-7d` is
  **disabled** until you extend (floor = original deletion date); after a
  `+7d`, `-7d` works and walks it back. Subheading reads "Nothing was shared
  with your Circle" for an on-time completion, "Was shared with your Circle"
  for one that escalated. Map shows the static gray dot (no pulse, no amber
  staleness warning); the outfit photo shows read-only — post-session data
  can't be edited.
- ☐ **Purged session**: after purge (or admin "purge data now"), the summary
  shows "Data deleted {date}" with no countdown/pills/map/pictures; the
  member's old alert link and admin detail degrade the same way — nothing
  looks broken.
- ☐ Background the app / lock the phone during an active session → **background
  location** keeps updating (verify the location trail later); interval escalates
  appropriately.

### SOS (P0)
- ☐ Trigger SOS → session is **immediately overdue**; alerts fire to the circle
  right away (SMS only — Circle members get no push) — see §4 for what the
  contact should receive.
- ☐ SOS with an **empty circle** → OWNER is warned (can't silently do nothing).

---

## 4. Overdue → Alert dispatch (P0, cross-device, time-based)

This is the core promise. Use OWNER + CONTACT on **separate physical phones**.

- ☐ OWNER starts a short check-in (e.g. shortest allowed duration) with ≥1
  active contact and lets it **lapse** (do not check in).
- ☐ Shortly after deadline + grace (within ~1–2 worker ticks), CONTACT receives
  an **SMS** only — no push ("Made It Home: {name} hasn't checked in, and
  expected to be back by {time}…", plus the destination, a battery line only
  when critically low, and a `Details:` link). Exact copy: `docs/notifications.md`.
- ☐ OWNER receives the "⚠️ Session Expired" push **and** its SMS backup (both
  are always sent).
- ☐ Session status goes ACTIVE → MISSED → ALERTED (verify in admin).
- ☐ CONTACT opens the SMS `Details:` link → the public alert page
  (`/alerts/{id}`) shows the location trail map + the outfit photo + battery.
- ☐ Alert page map: the trail map renders when the owner shares location, and
  the page auto-refreshes (~75s) while the incident is live.
- ☐ **Resolved alert** (owner marked safe): reopen the alert link later → the
  page shows the **All clear** card instead of Acknowledge, and stops
  refreshing.
- ☐ CONTACT **acknowledges** the alert → OWNER gets the named SMS, OWNER's
  app shows "Your alert was acknowledged" on its next poll, and admin shows
  the alert ACKNOWLEDGED.
- ☐ **Follow-up re-nudge**: if **no** contact acknowledges within
  `ALERT_REMINDER_DELAY_MINUTES` of the circle being alerted, every active
  contact gets the re-nudge SMS ("Made It Home: still no word from {name}…").
- ☐ OWNER **marks safe** on the missed session → circle gets an **all-clear**
  (SMS only); outstanding SENT/DELIVERED alerts resolve; already-ACKNOWLEDGED
  ones are left as-is.
- ☐ **Multi-contact**: with 2+ active contacts, all get alerted; one
  acknowledging is enough to stop the follow-up.
- ☐ **Opt-out mid-session**: a contact texts STOP during an active session →
  OWNER gets the appropriate push (last-contact "circle emptied" vs
  "contact opted out" when others remain); opted-out contact is excluded.
- ☐ **Delivery failure retry**: if an SMS fails (check Twilio logs / admin alert
  status FAILED), the worker retries via the same provider on a later tick.
- ☐ **Mid-incident remount (2026-07-16 fix)**: while the session is
  MISSED/ALERTED, kill + relaunch the OWNER app, and tap the "circle has been
  notified" push → Home and the session screen (live mode) must still show the incident
  (escalation heading, no extend buttons) and the lock-screen Live Activity /
  ongoing notification must stay up — NOT "No active session — Start Session".
- ☐ **Resolved state for CONTACT (2026-07-16 fix)**: after OWNER marks safe,
  CONTACT reloads the public alert page (SMS `Details:` link) → it shows the
  All-clear card instead of the Acknowledge button. Submitting a stale
  Acknowledge after mark-safe also renders the All-clear card and OWNER gets
  **no** late acknowledgement SMS.
- ☐ **Acknowledgement privacy (2026-07-18 redesign)**: with 2 contacts, after
  contact A acknowledges, B's page/app show NOTHING about it (no name, no
  notice — B's Acknowledge button still active); A sees only their own
  checked/grayed "✓ Acknowledged" button (no badge/toast). OWNER gets the
  NAMED SMS ("{A} acknowledged your alert"); B gets the anonymous SMS
  ("{owner}'s alert was acknowledged"); A gets no SMS; NO pushes are sent
  for acknowledgements. Owner's screens show "Your alert was
  acknowledged" via the poll.
- ☐ **Alert page payload (2026-07-16 fix)**: CONTACT's public alert page (SMS
  `Details:` link) shows the owner's real name + Call/Text buttons +
  destination/expected return + battery.
- ☐ **Unreachable circle (2026-07-16 fix)**: force every delivery terminal
  (staging: opt every contact's number out so their alert SMS is refused) →
  OWNER's screens + lock screen flip from "Notifying your Circle" to "We
  couldn't reach your Circle / Call or text them directly, or call 911" on a
  later poll.
- ☐ **Zombie SOS cancelled (2026-07-16 fix)**: airplane mode → hold SOS (it
  queues) → tap "I'm Safe" on the alarm card ("Cancelled — nothing was sent")
  → restore connectivity, wait past the retry interval → the SOS must NOT
  fire; CONTACT gets nothing.

- ☐ **SOS during a live check-in (2026-07-18)**: start a check-in with a
  destination + outfit photo, then hold SOS → SAME session escalates (circle
  gets a PANIC alert; the alert page shows the destination/outfit/trail from
  the outing); no duplicate session; the check-in's local reminders are gone.
- ☐ **Public alert page (2026-07-18/19)**: acknowledge → browser lands back
  on the normal URL (reload does NOT re-submit); page left open auto-refreshes
  ~75s and flips to All clear by itself when OWNER marks safe; link previews
  in iMessage/WhatsApp show "Safety Alert Details" (no name); a page for a
  session stuck >7 days shows the neutral "no longer current" card with no
  location/phone.
- ☐ **Circle alerts are SMS-only (2026-09-22)**: with a circle member who HAS
  the app installed and signed in, trigger SOS / a missed check-in / mark
  safe → the member gets the SMS each time and NO push; the owner still gets
  the "circle alerted" push.
- ☐ **Admin stuck-session actions (2026-07-19)**: on a MISSED session's admin
  detail page, "Close as false alarm" → CANCELLED, public page goes neutral,
  NO all-clear SMS to the circle; "Purge data now" deletes trail/photos
  immediately; both actions appear in the admin audit log.

---

## 5. Pre-deadline reminders (owner push)

- ☐ Create a check-in long enough to span the ladder (`REMINDER_LADDER_MINUTES`
  in `mobile/utils/sessionTiming.ts`, T-30/10/5/0).
- ☐ OWNER receives a reminder at each ladder rung (T-30/10/5/0) — these are
  now LOCAL notifications (2026-07-18: client-owned, fire in airplane mode /
  with the backend down; verify one rung offline). The T-0 SMS still comes
  from the server. Extending from the notification's "Extend 30 min" action
  reschedules the whole ladder; completing cancels it.
- ☐ **Extend** the session, then confirm the **old** reminders do **not** fire
  (staleness check) and new ones fire for the new deadline.

---

## 6. Notifications & SMS plumbing (both providers, both OS)

- ☐ Push works on **iOS (APNs)** and **Android (FCM)**, in **foreground,
  background, and killed** states.
- ☐ Tapping an owner push deep-links per `mobile/services/notificationRouting.ts`
  (e.g. "Your Circle has been notified" → `/sessions/active`).
- ☐ Dead/uninstalled push token: after reinstall, old token stops being used
  (no errors); new token registers.
- ☐ **SMS failover**: with the primary (Twilio) forced to fail (or per ops
  runbook), an alert still goes out via the failover provider
  (`SMS_FAILOVER_PROVIDER` = SNS on AWS). Verify via delivery logs.
- ☐ **Delivery webhooks** update status: send an alert, confirm the
  delivered/failed status flips on the Alert row (admin) from the provider
  callback (Twilio / SNS-via-Lambda).
- ☐ OTP, invite, welcome, all-clear, lapse, and "you unsubscribed" messages all
  arrive with correct copy and the right short-links.

---

## 7. Payments — Stripe (live), all access paths

> Verify the access **priority order**: active subscription > group plan >
> promotion > referral credit > free trial (1 session). Set up a user with
> overlapping sources and confirm the resolved `reason` and expiry.

### Self-subscribe — in-app selection, web checkout (BOTH platforms, incl. iOS)
> As of the in-app-selection change, iOS behaves like Android: plans are picked
> in the app; only the Stripe **checkout page** is on the web. Test the full
> round-trip on a **real iOS device** (this is the App Review risk surface).
- ☐ `/plans` → "I'll subscribe" → the picker step (same sheet) → Individual/Group ×
  Monthly/Annual toggles show correct prices. Present on **iOS and Android**.
- ☐ "Subscribe Now" opens the **Stripe checkout page in the external browser**
  (not an in-app webview); host is `checkout.stripe.com`. The app itself never
  shows a card/payment sheet.
- ☐ **Seamless return (happy path)**: after paying, return to the app → `/plans`
  is on its confirming step ("Confirming your subscription…"), auto-detects access (polls +
  re-checks on foreground), toasts **"Subscription activated!"**, and **resumes
  the interrupted session** (draft) or goes home. No manual reload.
- ☐ **Canceled checkout is not a dead-end**: open checkout, cancel/close the
  browser, return → the "Almost there" step shows a **"Back to plans"** button
  that returns to the `/plans` options step (not a stuck spinner). A Stripe
  cancel landing on `/plans?checkout=canceled` shows the options with a
  "Checkout canceled — no charge made." note.
- ☐ **Day pass** (`$0.99 "Just tonight"`): same round-trip — external Stripe
  checkout → return → access unlocks. Present on iOS and Android.
- ☐ **Apple Pay** (iOS, in Safari) and **Google Pay** (Android) are offered in
  the Stripe checkout and complete. (host validation: `checkout.stripe.com`.)
- ☐ Stripe Dashboard: `checkout.session.completed` received, webhook delivered
  (signature valid), Subscription row created.
- ☐ **Manage Subscription** (Account tab) → `/subscription`: plan card with
  "Renews …"/"Cancels …"; **Cancel subscription** / **Reactivate plan** work
  natively; **Change plan or payment method** opens the Stripe Customer Portal in
  the external browser (update card works). A trial / promo / referral-credit /
  day-pass user sees a **See plans** button (→ `/plans`); gift / comp shows the
  "provided for you" note with no billing controls.

### Group plan
- ☐ Buy a Group plan → a GroupPlan + invite code is created (admin /
  `/subscription` group-owner state). The owner's Cancel / Reactivate / portal
  controls show only for a self-paid (`stripe_web`) group sub.
- ☐ Share the invite (`/g/{code}`); a member joins (see §10); member gets access
  via the owner's subscription (no own sub).
- ☐ Owner removes a member → member loses access. Owner regenerates the invite →
  old link no longer works.
- ☐ Enforce **max members**.

### Family → Group rename verification (one-time, this release)
Prerequisites that MUST be done before these pass (no code can do them):
- ☐ **Stripe dashboard**: rename the "Family Monthly/Annual" product display names to
  "Group Monthly/Annual" (shown on hosted checkout + receipts). The `price_…` IDs are
  unchanged.
- ☐ **Secrets**: rename `STRIPE_PRICE_ID_FAMILY_MONTHLY` / `_ANNUAL` →
  `STRIPE_PRICE_ID_GROUP_MONTHLY` / `_ANNUAL` in `infra/secrets/manifest.json` and the
  `*.secrets.env` files, then run `populate-secrets.sh <env>` **before** deploying the
  new backend (the task def reads the new key names). `test_secret_manifest.py` stays red
  until the manifest rename lands.
- ☐ Deploy runs migration `f7a3d9e1c8b2` (renames tables + migrates `plan_type`
  `family_*` → `group_*`). Verify existing subscribers keep access post-deploy.

Then verify end-to-end:
- ☐ The `/plans` picker shows the **Group** tab ($10/mo, $8/mo annual, "Up to 5 people —
  family, roommates, or friends"); checkout for `group_monthly` / `group_annual` completes
  and unlocks access with `reason: "group_plan"`.
- ☐ Account tab shows **Group Plan (via <owner>)**, **Manage Group**, and **Leave Group Plan**.
- ☐ `/g/{code}` deep link (slug reassigned from `/f/` in a later commit —
  owner decision 2026-09-23) opens the app → "Joining
  group plan…" → **View Subscription** (→ `/subscription`). Browser fallback lands on **`/groups/{code}`**
  (the old `/family/{code}` URL is gone — confirm any pre-shared links regenerate).
- ☐ Admin **/admin/group-plans** loads; a plan's detail page shows **Group members**.
- ☐ Force-update the founders' TestFlight/internal builds — old builds call the removed
  `/family-plans` routes and send `family_*` plan types, so they break until updated.

### Sponsorship
- ☐ From a sponsorship link (`/s/{code}`) in a **browser** (not app-claimed): sponsor
  enters phone, gets OTP, picks a plan, pays via Stripe.
- ☐ Recipient already has an account → access appears for them. Recipient has no
  account yet → access is applied when they sign up (gift keyed by phone).
- ☐ Two gifts to the same phone **stack** (periods queue, don't overwrite).

### Sponsorship request
- ☐ "Ask someone I trust" → pick a contact → they get an ask (SMS). Fulfilling
  it via sponsorship checkout resolves the request.

### Referral credit
- ☐ Redeem a referral code (`/r/{code}` → `/referrals/new` auto-applies) → user gets
  the configured free-credit days; can create sessions; credit expires on time.
- ☐ Referrer's redemption count increments; referrer can't exceed their max.

### Negative / edge
- ☐ Already-subscribed user hitting checkout → blocked (402), not a double-sub.
- ☐ Payment **failure / dunning**: simulate a failed renewal; confirm the
  dependent lapse notifications fire **only after Stripe exhausts retries** (not
  on the first failure).

---

## 8. Subscription-lapse notification sequence (time-based, dependents)

For a **group owner** and a **sponsored beneficiary**:
- ☐ Owner/sponsor cancels (or sub fails terminally) → **T=0** SMS+push to each
  dependent ("…ends {date}. Subscribe: madeitho.me/sub").
- ☐ **T-7d** and **T-1d** reminders fire once each (no duplicates across ticks).
- ☐ **T=end** (period actually ends) → final SMS; group members get the
  `GROUP_PLAN_GRACE_DAYS` grace, then access cuts off.
- ☐ The `/sub` short-link lands on the marketing site (`www.madeithomeapp.com`)
  via a temporary 302 — interim until the app claims `/sub` and opens the
  paywall directly.

---

## 9. Account lifecycle (delete / grace / restore / purge)

- ☐ **In-app delete** (Account tab → Delete Account, `/account/delete`): type-to-confirm gate + native
  confirm; account soft-deletes; own Stripe sub cancels at period-end; for
  sponsored subs the "stop vs keep" choice is honored.
- ☐ Re-authenticate during grace → **Welcome Back** screen with the
  scheduled-deletion date; "Restore" reactivates the account (and resolves any
  gifts that arrived during grace); "Sign out" leaves it deleted.
- ☐ **Web delete flow** (`/account/delete`, the store-compliance path): phone →
  OTP → type "delete" → success; works without the app.
- ☐ **Hard purge** (after the grace days, hourly worker): PII anonymized,
  outfit photos/location deleted (verify storage), Stripe customer link
  severed (`purged:` sentinel); attempting restore now fails (Gone).
- ☐ **Re-signup after purge**: a previously-purged phone signs up fresh → new
  account; if the matched Stripe customer had prior billing history, free trial
  is **denied**.

---

## 10. Deep links & universal links (the part that needs devices)

> This is the area I could not verify without a device. Exercise it explicitly.

Custom scheme first (works without AASA), to isolate routing from OS link
verification — e.g. `npx uri-scheme open madeithome://g/TESTCODE --ios|--android`:
- ☐ **Cold start, logged out**, open `madeithome://g/{code}`: app launches →
  lands on **login** (not welcome) → after OTP → returns to the **group join**
  screen (destination preserved), not the home tab.
- ☐ **Cold start, logged in**: opens straight to the join screen and joins.
- ☐ **Kill during OTP**: open the link, get to login, fully kill the app, relaunch,
  enter OTP → still returns to the join screen (AsyncStorage-persisted
  destination, 15-min TTL).
- ☐ **New user**: link → signup → required name step → onboarding → lands on the
  join screen (not dumped on home).
- ☐ Stale destination: open a link, abandon login for >15 min, later sign in for
  something else → it does **not** yank you to the old destination.
- ☐ Repeat the four cold-start cases for `/r/{code}` (referral → `/referrals/new`
  auto-apply).
- ☐ `/c/{code}` (Circle invite) is **browser-only** (owner decision
  2026-09-23 — Circle members use mobile web only, no in-app accept screen):
  `https://madeitho.me/c/{code}` opens the web lander (`/circles/{code}`)
  whether or not the app is installed — there's no app-open case to verify.
  (The custom scheme `madeithome://c/{code}` always opens the app, which has
  no `/c` route any more; nothing we send uses it.)
- ☐ `madeithome://sub` (the app's own scheme, no device needed for the SMS
  itself): opens straight to the **paywall** (`/plans`), not a browser bounce
  — this is what the frozen lapse-SMS link now does on a device with the app
  installed (owner decision 2026-09-23, replacing the old marketing-site
  redirect).

Then real universal links (requires AASA/assetlinks served from `madeitho.me`
over HTTPS and the build's team/bundle + SHA-256 fingerprints registered):
- ☐ `https://madeitho.me/.well-known/apple-app-site-association` and
  `/assetlinks.json` return valid JSON with the right appID/package and the
  paths `/r/*, /g/*, /sub, /plans, /subscription` (and **not** `/c`, `/s`,
  `/f`, `/sponsorships`).
- ☐ Tapping a real `https://madeitho.me/g/{code}` or `/r/{code}` link from
  **Messages/Notes** (not typed in the browser) **opens the app** when
  installed.
- ☐ Same links with the app **not installed** → open their browser landers
  showing the invite/referral details + store buttons.
- ☐ `https://madeitho.me/sub` with the app **installed** opens the app's
  **paywall** (`/plans`) directly — not a browser page. With the app **not
  installed**, it hits the browser fallback: `/sub` → 302 `/plans` → the
  UA-based store bounce (iOS → App Store, Android → Play Store, desktop →
  marketing site).
- ☐ **Verify** what a real Stripe return does. Stripe's `success_url` /
  portal `return_url` are `https://madeitho.me/plans?checkout=success…` /
  `…/subscription` (on `SHORT_DOMAIN`, the claimed host). Complete a test
  checkout and a portal visit on iOS and Android and record which happens:
  the OS **may** hand the return to the app (then `/plans` must land on the
  confirming step — the `?checkout=success` query survives into
  `plansStep()` — and `/subscription` shows current status), or it may stay
  in the browser, because a script-driven redirect is often not intercepted
  (then the UA-based store fallback shows the store listing with **Open**).
  Either way, switching back to the app must unlock access: the confirming
  step's foreground re-check is the reliable path, not the universal link.
  Tapping the same URLs from **Messages/Notes** must open the app. Not
  installed → same UA-based store/marketing fallback as `/sub` above.
- ☐ **Verify** the second-modal case: open checkout from `/plans` (the modal
  moves to confirming), then return via the Stripe URL while that modal is
  still open. Record whether expo-router stacks a **second** `/plans` modal
  on top. If it does, closing the top one must reveal a working screen,
  not a dead end.
- ☐ **Signed out, cold open**: log out, kill the app, then tap
  `https://madeitho.me/sub` (and `/plans?checkout=success`, `/subscription`).
  The app goes to **login**, not the paywall. After OTP it **returns to the
  same screen**, including `?checkout=success` → confirming
  (`useRequireAuth` + `setPendingRoute`, replayed by login). It must never
  show the paywall signed out, and a plan tap must never produce a 401 toast.
- ☐ `/c/` (Circle invite) and `/s/` (sponsorship) **always open the
  browser**, even with the app installed — `/c/` because Circle members use
  mobile web only (no in-app surface to route into), `/s/` for the IAP
  guard.
- ☐ Settle the **`index.tsx` anchor race** explicitly: on cold start the entry
  screen must be deterministic (login, not welcome) and the destination must
  survive. If it ever lands on welcome or drops the code, that's the known gap
  flagged in commit `150e9a6` — needs the index guard.

---

## 11. Native device capabilities (iOS + Android, real hardware)

- ☐ **Notifications permission** prompt (onboarding) → grant/deny both honored.
- ☐ **Location**: when-in-use vs **always/background** distinction; iOS
  "Allow Once"/"While Using"; Android background-location grant; background
  task keeps reporting during an active session; stops when session ends.
- ☐ **Camera** + **photo library** capture/pick, with permission prompts;
  captured photo can be saved to the library.
- ☐ **Biometric** (Face ID / Touch ID / fingerprint): enable in the Account tab →
  re-auth prompts biometric; disabling clears stored credentials.
- ☐ **Contacts** permission + import list loads.
- ☐ **SMS compose** (circle invite, sponsor fallback) opens the native SMS app
  prefilled.
- ☐ **Live Activities** (iOS): Dynamic Island/lock-screen countdown during an
  active session; tapping it deep-links to the session screen
  (`madeithome://sessions/active` → `/sessions/{id}`). Android persistent
  notification equivalent.
  - ☐ **Brand mark shows, not stretched**: the house-check logo
    (`MadeItHomeMark`) appears at a fixed square size on the lock-screen card
    AND in the Dynamic Island (compact pill + expanded) — never stretched or
    clipped off the card. (asset: `mobile/assets/liveActivity/MadeItHomeMark.png`)
  - ☐ **Brand voice / state-aware copy** mirrors the in-app session screen's
    live mode, not "Session" jargon (`LIVE_STATUS_COPY` in `mobile/services/liveStatus.ts`):
    active → **Made It Home · Check-in by {time}**;
    grace → **Check-in overdue**; MISSED → **Notifying your Circle**;
    ALERTED → **Your Circle has been notified**; a Circle member acknowledged →
    **Your alert was acknowledged**.
  - ☐ **Hero countdown**: a large digital countdown ticks every second on the
    lock-screen card (and in the expanded Dynamic Island); the thin progress
    bar **fills left → right** from session start toward the deadline (it must
    not drain right → left, and must not reset when the app foregrounds).
  - ☐ **Danger flips AT the deadline, app dead** (the key one): start a short
    check-in, **force-kill the app and leave the phone locked**. The moment the
    deadline passes, the card must flip teal → red **on its own** with copy
    **Check-in overdue** and a count-up timer showing **how long
    overdue** (+ "OVERDUE" caption). No opening the app, no push required
    (this is the widget's staleDate flip — nothing may need to wake the app).
  - ☐ **Escalation while locked**: after grace, with the app still killed but
    then opened once — card shows **Notifying your Circle** → **Your Circle
    has been notified**; after CONTACT taps **Acknowledge** on the alert page,
    OWNER's card (app foregrounded once to poll) shows **Your alert was
    acknowledged** and the in-app heading matches word-for-word.
  - ☐ **Flips back**: extend the session out of overdue → card returns to teal
    with the countdown + fill bar restored.
  - ☐ **SOS variant**: SOS live activity shows status copy only (no countdown,
    no bar) and is danger-styled from the start.
  - ☐ Android: the ongoing notification flips teal → red **at the deadline**
    (within ~2s, not up to a minute late); the chronometer counts **down** to
    the deadline while active and **up** from it once overdue; the brand mark
    shows as the large icon; a progress bar fills left → right while active
    and disappears once overdue.
- ☐ **Splash** hides only after auth check + config fetch (no premature flash /
  no indefinite hang).
- ☐ Permission **denied** paths degrade gracefully (clear messaging, no crash).

### Point-of-use permission sufficiency (inline panels)

- ☐ **No cold prompts**: launch a fresh install and tap around (home, Circle,
  start-session) WITHOUT going through onboarding grants — no OS permission
  dialog appears except from a guided flow (onboarding, a panel's "Allow", or an
  explicit picker tap).
- ☐ **Create-session panel**: with Location < Always or Notifications off, a
  prominent warning row appears. "Start Session" stays enabled (warn, never
  block). "Learn more" opens the matching onboarding step; "Allow" (undetermined)
  prompts; "Open Settings" (denied/limited) deep-links to Settings.
- ☐ **Live re-check**: with the new-session or live session screen open,
  change a permission in system Settings and return — the panel updates without
  a restart, and the next gather begins using it.
- ☐ **Live session panel**: same guidance shows during a running session;
  granting mid-session clears the row and data starts flowing.
- ☐ **Contacts nudge**: shows only when there's room in the circle AND no visible
  phone contact could grow it (denied, iOS Limited, or all visible already
  added); hides the moment an addable contact is visible or the circle is full.

### Opportunistic session gather (battery)

- ☐ **Battery when location is off**: start a session with location sharing off,
  leave it running → battery readings still reach the backend (admin session
  detail shows battery rows with no map point; the location pin is NOT blanked
  by a battery-only ping).

---

## 12. Web pages & admin

- ☐ Landers render and are share-safe: `/referrals/{code}`, `/groups/{code}`,
  `/circles/{code}`, `/sponsorships/{code}`. Invalid codes show the
  friendly "not valid" page (no 500).
- ☐ `GET /` 301s to the marketing site (`www.madeithomeapp.com`); `GET /pricing`
  is gone (404) — marketing/pricing live only on marketing-site (owner
  decision 2026-09-23).
- ☐ Legal links go to the **marketing site** (`www.madeithomeapp.com/privacy`,
  `/terms`) from both the login screen and the Account tab.
- ☐ **Sponsorship management** (`/sponsorships`): phone → magic-link SMS →
  "Open billing portal" button → portal (Stripe) → "changes saved". Opening the
  link alone (or a chat app's link preview) must not use it up — only the button
  does. Expired/invalid/used token → friendly re-request.
- ☐ **Admin** (`/admin`): non-admin gets 403; admin can browse users,
  subscriptions, sessions, alerts, circle, OTPs, phone numbers; read-only
  entities can't be mutated; filters/search work.
- ☐ **Admin session detail — live map** (2026-07-19): on a live session the
  MapLibre trail shows the pulsing blue latest-position dot; leave the page
  open past the 15-min staleness window → dot grays out and the freshness
  caption goes amber, without a reload. Terminal sessions keep the red End
  marker.
- ☐ **Admin data management**: clear one ping's
  location (battery survives on the row) and one ping's battery (coords
  survive); the last-known pin moves everywhere after clearing the newest
  coords. Each action shows in the Admin Access Log.
- ☐ **Mark safe on their behalf** (2026-07-19): button on a live session → the
  double-confirmation page (consequence copy + required "directly verified"
  checkbox — the POST is rejected without it); confirming completes the
  session and CONTACT receives the real **all-clear** SMS/push; audit row
  `checkin_on_behalf` appears. Contrast: "Close as false alarm" still sends
  **nothing**.

---

## 13. Infra / ops smoke (per environment)

- ☐ `GET /health` → 200; `GET /health/ready` → 200 when DB healthy, 503 when
  degraded (verify it actually flips on a DB blip if you can).
- ☐ **DNS + TLS** valid for `app.madeithomeapp.com` and `madeitho.me`
  (+ `s.madeitho.me` for staging); HTTPS enforced; HTTP→HTTPS redirect.
- ☐ **Photo storage**: uploaded photos load on-device via presigned URL; CORS
  allows the app origin; deletion actually removes the object.
- ☐ **Rate limiting** active (global 60/min/IP; tighter on OTP) and disabled in
  test env only.
- ☐ **Error tracking — backend**: `BUGSNAG_API_KEY=… make error-reporting-smoke` passes
  from a dev machine; after deploy, admin dashboard → "Send error-reporting test event"
  → the event shows under the right release stage with the deployed `GIT_SHA`
  as version; `GET /health/ready` reports `error_reporting: configured`. Trigger a
  handled error (e.g. an OTP send with Twilio creds broken in staging) and
  confirm the `logger.error` arrives. Confirm **no PII** (only `user.id`,
  never name/phone) on any event.
- ☐ **Error tracking — mobile**: `MOBILE_BUGSNAG_API_KEY=… npm run error-reporting:smoke`
  passes; in a staging/dev-client run the EnvBanner "· test error reporting" link toasts
  a success; a network failure on the OTP screen (backend down) produces an
  `api.network` warning with the templated endpoint, and a second failure within
  10 min does NOT produce another; sessions appear under the release stage.
- ☐ **Production DB failover** (production only, planned drill): RDS Multi-AZ
  failover causes only a brief blip; app recovers. (DR/region-loss is the
  separate runbook `docs/dr-runbook-aws.md`.)
- ☐ **Worker liveness**: confirm `worker_tick` is actually running on schedule in
  prod (a deliberately-overdue test session that never alerts means the worker
  or its advisory lock is stuck).

---

## 14. Build, release & environment targeting

- ☐ **Staging build** points at the staging backend and shows the EnvBanner;
  **production build** points at prod and shows **no** banner.
- ☐ TestFlight (iOS) and Play **internal testing** (Android) builds install and
  launch; store metadata/privacy labels match actual data use.
- ☐ App version/build numbers correct; OTA/update channel correct per profile.
- ☐ **1.2.0 is a NATIVE release** (MapLibre replaces react-native-maps; also
  carries the 1.1.0 Live Activity redesign): runtimeVersion follows
  appVersion, so it must ship as a fresh EAS build + store release — an OTA
  push cannot deliver it, and older binaries must not receive the new JS.
- ☐ First-launch cold start on a fresh install is clean (no leftover state).

---

## 15. End-to-end cross-device scenarios (run these as scripted walk-throughs)

1. **The core safety loop**: OWNER (iOS) signs up → adds CONTACT (Android) →
   CONTACT accepts → OWNER starts a 30-min check-in with location → lets it
   lapse → CONTACT gets SMS, opens map+photo, acknowledges → OWNER marks
   safe → CONTACT gets all-clear. (Then repeat with OWNER on Android, CONTACT on
   iOS.)
2. **SOS**: OWNER triggers SOS → CONTACT alerted immediately → resolve.
3. **Invite cold-start**: CONTACT (no app) taps a real `madeitho.me/c/{code}`
   SMS link → opens the web lander (browser, not the app store — Circle
   invites are mobile-web-only) → logs in with phone OTP right there → taps
   accept → joins their Circle, no install required.
4. **Group**: OWNER buys group → invites CONTACT + CONTACT-2 → both join and
   get access → OWNER cancels → dependents get the lapse sequence → grace →
   cutoff.
5. **Sponsorship**: a sponsor (browser, no app) sponsors a plan to OWNER's phone → OWNER
   signs up and has access.
6. **Delete & restore**: OWNER deletes in-app → re-auth → Welcome Back → restore
   → everything intact.

---

## What automated tests already cover (don't re-test manually)

- Backend: pytest suite (1446 tests) — endpoint logic, access-gating rules,
  alert/session state machine, opt-out cascade logic, Stripe webhook handlers
  (mocked), short-link redirects, AASA path derivation, sponsorship token
  logic, REST conventions.
- Mobile: jest (`utils/authRedirect.ts` — destination capture/TTL/safety),
  tsc, eslint.
- These verify the **logic**; this plan verifies the **integrations** and
  **devices** they can't reach.
