# Privacy Review — Remediation Plan

Findings from a full-stack privacy review (2026-05-11). Lens: what PII is collected, where it flows, how long it's kept, and what control users have. Security review plan has been fully implemented and removed.

**Surfaces covered:** backend models + services, third-party integrations (Stripe / Twilio / AWS SNS / AWS S3 / Bugsnag / Expo Push), mobile app permissions and disclosures.

**PII inventory (summary):**
- Identifiers: phone number (E164, primary), full name, optional profile photo, Stripe customer ID, Expo push token
- Location: precise lat/long every ~5 min during an active session (`session_updates`)
- Photos: outfit photo per session (the background session-photo pipeline, including its EXIF lat/long, was removed 2026-09-05)
- Third-party PII: Circle-of-Trust contacts' names + phone numbers (these people did not sign up)
- Auth artifacts: OTP records (phone + 6-digit code)

---

## Priority 1 — Subject rights (deletion + export)

### 1.1 No account-deletion endpoint — **DEFERRED**
Not in scope for current stage. Handle deletion requests manually for now. When this is picked up, the cascade to think through is: `sessions` (→ `session_updates`, `alerts`), `circle_of_trust_members` (both as `user_id` and `contact_user_id`), `subscriptions`, `sponsorship_requests`, `group_plan_members` (and the plan itself if owner — needs an ownership-transfer story), `otps` for this phone, `expo_push_tokens`, S3 objects under the user's prefix, and the Stripe customer record. PhoneNumber rows shared with other users' circles should be preserved.

### 1.2 No data-export endpoint — **DEFERRED**
Not in scope for current stage. Bundle with 1.1 when account deletion is built — same model traversal applies. Until then, handle export requests as an ad-hoc admin query.

---

## Priority 2 — Third-party contact rights

**Reframing note:** An earlier draft of this section assumed Circle of Trust contacts were added silently and received alerts without ever consenting. That was wrong. The existing invitation flow (`app/api/v1/endpoints/invitations.py` + `crud_circle_of_trust`) requires the recipient to sign up and call `POST /invitations/{code}/accept` before they become `ACTIVE`. Alert dispatch in `session_tasks.py:164, :231` filters on `ContactStatus.ACTIVE`, so PENDING invitees never get SMS. The third-party-consent gap is therefore not what I originally claimed.

### 2.1 STOP handling — **DEFERRED**
Lower priority than originally framed, because active circle members are app users and can leave a circle via `DELETE /memberships/{id}` from within the app. SMS-STOP is only valuable for users who want to opt out without opening the app. When picked up, the UX complication remains: opt-out has to remove them from the circle (the relationship is meaningless if they won't receive alerts), and the owner needs to be told their safety circle just shrank, or the safety guarantee breaks silently.

### 2.2 ~~Identify the sender on first contact~~ — not needed
Recipients have explicitly accepted the invitation and know what Made It Home is by the time any alert fires.

### 2.3 Post-acceptance confirmation SMS — **DONE**
Implemented in commit `5c74fd4`. Welcome SMS sent from all three accept paths (API, deep-link, HTMX). Fire-and-forget — SMS failure does not block acceptance. 4 tests in `test_circle_welcome_sms.py`.

---

## Priority 3 — Retention

### 3.1 OTP table grows unbounded — **NOT PURSUING**
Phone numbers already exist on `User` / `PhoneNumber`, so OTP rows aren't a uniquely sensitive store. Storage cost is negligible at current scale.

### 3.2 Delete location and photos on session terminate (no retention window) — **DONE**
Implemented in commit `419bf9f`. Removed `PHOTO_EXPIRY_HOURS` from config and the time-based filter from `cleanup_expired_data`. Terminal sessions are cleaned up on the next worker tick (~60s). Tests updated.

### 3.3 Dev-mode logs phone + OTP + SMS body — **NOT PURSUING**
Existing `ENVIRONMENT == "development"` guard is sufficient. Risk depends on deployment hygiene, not code.

---

## Priority 4 — Data minimization at third-party boundaries

### 4.1 Bugsnag PII — **DONE**
Fixed in security plan commit `3c0ac72`. PII stripped from Bugsnag — only `user.id` sent. Codified in `.claude/rules/security.md`.

### 4.2 Stripe data minimization audit — **NOT PURSUING**
Phone on Stripe Customer is appropriate for receipts/disputes. Gift-flow metadata is required for the webhook handler.

### 4.3 EXIF location on session photos — SUPERSEDED 2026-09-05
Was confirmed as a feature at the time. The whole background session-photo pipeline (and the EXIF columns with it) was removed on 2026-09-05; only the outfit photo remains and no EXIF is stored.

### 4.4 Push notification payloads — **NOT PURSUING**
Lock-screen name visibility is the intended behavior; no coordinates currently in payload.

---

## Priority 5 — User-visible privacy posture

### 5.1 Privacy policy link — already in place
Linked from the Account tab (`mobile/app/(tabs)/account.tsx`). Worth cross-checking once that the hosted policy actually reflects the behavior decided in this plan (location/photo delete-on-terminate, post-acceptance SMS to circle contacts) once those land, but no code change here.

### 5.2 Admin audit log — **DONE**
Implemented in commit `9e9356d`. `AdminAccessLog` model with `admin_user_id`, `target_user_id`, `entity`, `entity_id`, `action`, `created_at`. Audit rows written from list/detail/edit/create/delete handlers. Read-only admin view at `/admin/admin-access-logs`. 8 tests in `test_admin_audit_log.py`.

### 5.3 `Session.destination` free-form text — **NOT PURSUING**
User's own data, shown back to themselves and their circle — no new exfiltration surface.

---

## Cleared during review (no action)

- **Analytics SDKs:** None present (no Amplitude, Mixpanel, Segment, Firebase Analytics, Sentry, etc.). Only Bugsnag for crash reporting. Good baseline.
- **Location coordinates in SMS:** Verified — coordinates are never interpolated into outbound SMS to circle contacts. Only the user's name and (in a low-battery case) battery percentage.
- **Phone number normalization:** Original input is discarded at the parse step; only E164 form is stored. No "best-effort" parsing keeping the raw string.
- **Photo access:** S3 photos served via per-request presigned URLs, read-only, 1-hour expiry. Path keyed by authenticated `user_id`. Bucket is not public.
- **Push notification location:** Push `data` dict carries `alert_id`, `user_id`, `type` only — no coordinates, no full address.
- **Client IP storage:** IPs used for rate-limiting only (slowapi), not persisted.
- **Email collection:** No email is collected. The minimal-PII posture here is good.
