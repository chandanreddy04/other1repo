# Account Deletion — Plan

## Context

The marketing site's Privacy Policy and Terms of Service both assert that users can delete their accounts. We haven't built it. We need to.

Three forcing functions:

1. **Apple App Store Review Guideline 5.1.1(v)** (effective June 30, 2022): any app that lets users create an account must let users initiate account deletion from within the app. Apple has been actively rejecting apps that don't comply.
2. **Google Play User Data policy** (enforced August 31, 2024): same in-app requirement, plus a separate web-based deletion path declared in Play Console.
3. **US state privacy laws** (CCPA/CPRA, VCDPA, CPA, CTDPA, UCPA — the app is US-only per the marketing site, so these are the relevant statutes): every state gives consumers a legal right to deletion. 45-day response window. Retention exceptions for legal, security, fraud, and tax purposes are standardized.

We satisfy all three with a single implementation: in-app deletion + web deletion path + actual data deletion within 30 days. This document is the plan.

## Compliance baseline

What the requirements force vs. what we choose:

| Required by Apple/Play/state law | Our choice |
|---|---|
| In-app deletion (not just web) | Yes — Account tab → Danger Zone → Delete Account |
| Web deletion path | Yes — `app.madeithomeapp.com/account/delete` (Google Play requires; useful for everyone) |
| Permanent deletion of personal data, not deactivation | Yes — soft-delete on day 0, hard-purge on day 30 |
| Subscriptions must be cancellable | Yes — `cancel_at_period_end=True` via Stripe |
| Can't block deletion on subscription/account state | Yes — every state allows deletion |
| Easy to find (Apple has been rejecting "buried" implementations) | Account tab, one section under About |
| Retention of legitimate business data permitted | Yes — Stripe transaction records, audit logs preserved (anonymized) |

## Policy decisions

| Decision | Choice |
|---|---|
| Delete model | Soft delete immediately + 30-day grace + hard-purge in place (scrub PII columns, keep `users.id` row). No row deletion. |
| Recovery during grace | "Welcome back" screen on sign-in shows scheduled deletion date + restore prompt. Not silent. |
| Confirmation gate (mobile) | Two locks: typed `delete` enables button + native `Alert.alert` destructive confirmation. |
| Subscription on delete — any tier | `stripe.Subscription.modify(cancel_at_period_end=True)`. No refund. No proration. Service continues through paid period. Annual was a commitment for a discount; we honor the period we sold. |
| Group plan owner deletes | Same `cancel_at_period_end` on the plan's sub. Members keep access through paid period naturally. No ownership transfer mechanism (the period-end behavior makes it unnecessary). |
| Active session at delete | Session continues running. If overdue → alerts fire to circle normally. SOS still fires. Hard purge waits until (t=30d) AND (no active sessions). |
| Sponsorship: user-sponsor deletes | User chooses per-sponsorship: **Stop sponsoring** (default, `cancel_at_period_end`) or **Keep sponsoring** (Stripe sub continues, manage via `madeitho.me/sponsorships`). |
| Sponsorship: beneficiary deletes | `cancel_at_period_end` on the sponsored sub. Sponsor stops being charged at next renewal. |
| Re-signup after grace | New User row, fresh start. **Re-attach Stripe Customer by phone metadata** so payment history is preserved + free trial gating still works. |
| Free trial after re-signup | **Deny** if the matched Stripe Customer has prior subscription history. |
| Stripe Customer object | Keep in Stripe forever (tax/audit retention). Sever the `user.stripe_customer_id` link at hard purge. Re-attach on re-signup. |
| Admin logs | Keep all rows. The `users.id` they reference becomes an anonymized stub (full_name=NULL, phone=NULL). No nullable-FK migration required. |
| Referrals | Same — preserve rows, anonymize via in-place scrub. No nullable-FK migration. |
| Notifications to downstream users | On any subscription state change (deletion or otherwise), group members + sponsored beneficiaries get SMS + Expo push + in-app banner at T=0, T−7d, T−1d, T=end. |

## System design

### Data model

Only one new column:

```sql
ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX ix_users_deleted_at ON users (deleted_at)
  WHERE deleted_at IS NOT NULL;
```

The partial index keeps the worker scan cheap (it only needs to find the few users that are scheduled for hard purge).

No new columns on `Session` (sessions terminate within hours; the 30-day grace keeps the user row's PII readable until long after any session at deletion time has resolved). No nullable-FK migrations (anonymize-in-place keeps every FK valid).

### Identity lifecycle (state machine)

```
                     ┌──────────────┐
                     │   active     │  (default)
                     └──────┬───────┘
                            │ DELETE /users/me
                            │ or web flow / re-signup denied
                            ▼
                     ┌──────────────┐
                     │ soft-deleted │  deleted_at = now()
   ┌─────────────────│              │  user can't auth
   │ OTP verify      │ within 30d   │  Stripe sub: cancel_at_period_end=true
   │ within 30d      └──────┬───────┘  affected dependents notified (T=0)
   │ + Restore confirm      │
   │                        │ worker tick t > deleted_at + 30d
   ▼                        │ AND no active sessions
┌──────────────┐            ▼
│   active     │     ┌──────────────┐
│ (restored)   │     │  hard-purged │  PII columns scrubbed
└──────────────┘     │              │  user_id row preserved
                     │              │  Stripe customer link severed
                     └──────────────┘
                            │
                            │ user signs up later with same phone
                            ▼
                     ┌──────────────┐
                     │  new active  │  brand-new user_id
                     │              │  Stripe Customer re-attached by phone metadata
                     │              │  free trial denied (Stripe history present)
                     └──────────────┘
```

### Notification surface

Notifications fire on **every** subscription state change (deletion is one path; direct cancel via Stripe portal, payment failure, manual cancel all use the same pipeline). This generalizes correctly and isn't deletion-specific.

| Stripe webhook | Behavior |
|---|---|
| `customer.subscription.updated` (cancel_at_period_end flipped true) | Identify dependents (group members, sponsored beneficiary). Send T=0 SMS + push immediately. Schedule T−7d and T−1d via worker tick. |
| `customer.subscription.deleted` (natural lapse at period end) | Send T=end SMS + push. Mark dependent's access flag. |
| `invoice.payment_failed` (after Stripe's retry budget exhausted) | Same as `cancel_at_period_end` — service will lapse imminently. |

Mobile gets a `<SubscriptionEndingBanner />` driven by `useSubscriptionStore` — shown when the active sub has a scheduled end date.

A backend redirect at `app.madeithomeapp.com/sub` (linked from SMS as `https://madeitho.me/sub`) lands on the existing pricing/upgrade flow.

## Implementation phases

Eleven phases. Each ends with green tests and a commit.

| # | Phase | What ships | Surface |
|---|---|---|---|
| 1 | **Schema** | `User.deleted_at` migration + model field | Backend |
| 2 | **Orchestrator** | `account_deletion.delete_user_account(user, sponsorship_choices)` service | Backend |
| 3 | **Endpoint + auth gating + restore** | `DELETE /api/v1/users/me`, `POST /api/v1/users/me/restore`, deletion_pending response on OTP verify | Backend |
| 4 | **Hard-purge worker** | Worker tick scans for users where `deleted_at < now() - 30d` AND no active sessions; scrubs PII in place | Backend (cron) |
| 4.5 | **Notification fan-out + `/sub` redirect** | Stripe webhook handlers for sub state changes; worker tick reminders; SMS + push + banner | Backend + Mobile |
| 5 | **Mobile UI — Danger Zone** | Account tab → Delete Account → Confirmation 1 → Confirmation 2 → API + reset stores + nav | Mobile |
| 6 | **Web deletion page** | `app.madeithomeapp.com/account/delete` Jinja2 template with phone-OTP flow | Backend |
| 7 | **Marketing site legal copy** | `privacy.html` + `terms.html` updates on the marketing site repo | Marketing site |
| 7.5 | **Sponsorship management page** | `app.madeithomeapp.com/sponsorships` magic-link flow → Stripe Customer Portal | Backend |
| 9 | **Re-signup linking** | OTP verify on fresh signup detects matching Stripe Customer by phone metadata, attaches, denies free trial | Backend |
| 10 | **Tests + docs runbook** | Coverage sweep + ops runbook in `docs/deployment.md` | Tests + docs |

Phase 8 doesn't exist; numbering kept this way to preserve task IDs already created.

Dependency ordering:
- 1 → 2 → 3 → 4 (linear backend stack)
- 4.5 needs 2 (orchestrator triggers the cancel_at_period_end change) but is otherwise independent
- 5 depends on 3 (endpoint) and 4.5 (banner) and the live ALB/HTTPS
- 6 depends on 2 and 3 (reuses orchestrator + restore)
- 7 can run any time after 5 + 6 are stable (so the policy text matches what we actually ship)
- 7.5 is independent; sequence after 4.5 so the SMS in the deletion confirmation can reference it
- 9 depends on 2 (uses anonymize-in-place state)
- 10 last

## UI flows

### Mobile deletion confirmation

```
[Account tab]
  About
  ─ Support
  ─ Terms
  ─ Privacy
  ─ Version 1.0.0

  Danger Zone           ← new
  ─ Delete account      ← new, danger-styled

  [Logout button]
```

Tap **Delete account** →

**Confirmation Screen 1** (full screen, not modal):

> ### Delete your account?
>
> You're about to permanently delete your Made It Home account. Here's what happens:
>
> **Your Group Annual plan** ends Aug 8, 2026. Members keep access until then. No refund — annual plans are non-refundable.
>
> **You're sponsoring 2 people**:
>   ○ +1 (415) 555-4567 — Stop sponsoring after Aug 8 (default)
>   ○ +1 (415) 555-4568 — Stop sponsoring after Aug 8 (default)
>   *(toggle to "Keep sponsoring" for each if desired — they'll be notified)*
>
> **Your active check-in** ("Movie with Alex", returning 11:30 PM tonight) will keep running. If you don't check in, your circle will be alerted normally. SOS will still work.
>
> **Your 47 photos** will be deleted within 30 days. Your sessions, alerts, and circle of trust will too.
>
> **You have 30 days** to sign back in if you change your mind. After that, this is permanent.
>
> [I understand, continue]

Tap **I understand, continue** →

**Confirmation Screen 2** (full screen):

> ### Final confirmation
>
> Type **delete** below to confirm.
>
> [____________]  ← TextInput
>
> [Delete my account]  ← disabled until input == "delete"

Tap the button → native iOS/Android `Alert.alert` modal pops:

> **Permanently delete your account?**
>
> [Cancel]  [Delete]  ← right button is destructive style (red)

User taps **Delete** → API call → success → reset all 4 Zustand stores → `router.replace('/(auth)/login')` → toast: *"Account deletion scheduled — sign back in within 30 days to restore."*

### Welcome back / recovery during grace

User signs back in (OTP verify succeeds) within 30 days of soft delete →

**Welcome Back Screen**:

> ### Welcome back, Alex.
>
> Your account is scheduled for permanent deletion on **Aug 8, 2026** (in 21 days). After that, your photos, sessions, and personal info will be permanently erased.
>
> [Restore my account] ← teal, primary action
> [Sign out]           ← secondary
>
> *Signing out will let the deletion proceed as scheduled.*

Tap **Restore** → API clears `deleted_at` → user goes to home tab as normal.

Tap **Sign out** → user is signed out; deletion timer continues; access cut.

### Sponsorship choice at deletion (detail)

In Confirmation Screen 1, for each active sponsorship the user is paying for, render:

```
[radio] Stop sponsoring after [period_end] (default)
[radio] Keep sponsoring at $X/mo — manage at madeitho.me/sponsorships
```

If user chooses "Keep sponsoring" for any, the API call to `DELETE /users/me` includes a JSON body:

```json
{
  "sponsorship_choices": {
    "sub_abc123": "keep",
    "sub_def456": "stop"
  }
}
```

Default is "stop" for any sub not mentioned. The orchestrator reads the choices and applies `cancel_at_period_end=True` only to subs flagged "stop"; subs flagged "keep" stay running, our User↔Stripe link severs at hard purge, the Stripe Customer (keyed by phone metadata) persists and bills the same card.

### Web deletion via `app.madeithomeapp.com/account/delete`

Mirrors the in-app flow but starts cold (no auth). Three steps:

1. **Enter phone** — backend POSTs to the existing `/api/v1/auth/request-otp`
2. **Enter OTP code** — backend verifies via new `/api/v1/auth/verify-otp-for-deletion` (authenticates the phone but issues no token — single-purpose flow)
3. **Personalized confirmation** (same as mobile Screen 1) → **typed gate** (same as Screen 2) → deletion runs synchronously → success page: *"Your account has been scheduled for deletion on [date]. Sign back in to the app within 30 days to restore."*

No mobile session is touched. The user's app, if they had one signed in, will get a 401 on next API call and is expected to handle that gracefully (the same auth gate from Phase 3).

### Sponsorship management at `app.madeithomeapp.com/sponsorships`

Independent of deletion. Useful today for the existing guest-checkout sponsors who have no way to manage their subs.

> **Superseded 2026-09-27:** the magic link is no longer a signed JWT — it is a 12-char one-time DB token (`app/models/sponsorship_sign_in_token.py`) sent as the short link `{SHORT_DOMAIN}/s/p/{token}` → `GET /sponsorships/portal/{token}`; see `.claude/rules/domain-subscriptions.md` (Management). The JWT-secret question below is moot.

1. Phone input → backend sends SMS with **magic link** (signed JWT, 10-min expiry, scoped to "sponsorship management for phone X")
2. Click link → backend verifies signature + expiry → looks up Stripe Customer where `metadata.phone == phone` → `stripe.billing_portal.Session.create(customer=...)` → 302 redirect to the Stripe-hosted portal
3. Stripe portal: cancel subs, update payment method, view invoices — handled by Stripe
4. Return URL lands on a "Changes saved" page on our side

No persistent session is created. Magic link is single-use.

## Copy

### Mobile screens

Confirmation 1 + 2 — drafted in the UI flow section above.

Welcome Back — drafted in the recovery flow section above.

Toast on success: *"Account deletion scheduled — sign back in within 30 days to restore."*

### SMS templates (notification fan-out)

All under 105 chars (single SMS segment). Token substitution: `{owner_name}`, `{sponsor_phone_full}`, `{date}`.

**Group member**:

| Moment | Copy |
|---|---|
| T=0 | Your group plan from {owner_name} ends {date}. Subscribe to keep coverage: https://madeitho.me/sub |
| T−7d | Your group plan ends in 7 days. Subscribe now to avoid a gap: https://madeitho.me/sub |
| T−1d | Last day: Your group plan ends tomorrow. Subscribe to keep coverage: https://madeitho.me/sub |
| T=end | Your Made It Home group plan ended today. Subscribe to continue: https://madeitho.me/sub |

**Sponsored beneficiary**:

| Moment | Copy |
|---|---|
| T=0 | Your sponsorship from {sponsor_phone_full} ends {date}. Subscribe to keep coverage: https://madeitho.me/sub |
| T−7d | Your sponsorship ends in 7 days. Subscribe now to avoid a gap: https://madeitho.me/sub |
| T−1d | Last day: Your sponsorship ends tomorrow. Subscribe to keep coverage: https://madeitho.me/sub |
| T=end | Your Made It Home sponsorship ended today. Subscribe to continue: https://madeitho.me/sub |

After hard purge of the owner/sponsor, T=0 references degrade: `{owner_name}` falls back to "the plan owner"; sponsor phone is still in Stripe metadata so we keep showing the number.

Example as it would appear in Messages:

> *Your sponsorship from +1 (415) 555-4567 ends Jul 6. Subscribe to keep coverage: https://madeitho.me/sub*

### Confirmation copy details

- Personalized numbers pulled live at confirmation render:
  - Subscription cost: from active Stripe sub
  - Period-end date: from `subscription.current_period_end`
  - Photo count: from `Session.outfit_photo_url IS NOT NULL`
  - Active session deadline: from any session with status ACTIVE
  - Sponsorship list: from Stripe subscriptions where this customer is payer + metadata.gifter_phone is set
  - Group plan members: from `GroupPlanMember`

## Out of scope / future work

Explicitly deferred from v1:

- **Data export before delete** — Apple/Play don't require it; nice-to-have for GDPR alignment if EU launch ever happens.
- **Multi-device push token invalidation** — currently the User has a single `expo_push_token` column. If we ever support multi-device sessions, we'd need a device-tokens table and revoke per-device. Not relevant today.
- **Ownership transfer for group plans** — `cancel_at_period_end` makes the member transition smooth; explicit transfer UI was unnecessary. Could be added later for cleaner UX.
- **In-app sponsorship management within the app itself** — phase 7.5 builds the web surface (magic link → Stripe portal). An in-app version that doesn't require leaving the app is possible but not required by Apple/Play and the Stripe portal redirect works fine.
- **Per-day proration on annual** — explicitly rejected (cancel_at_period_end + no refund is the policy).
- **Email notifications** — we don't capture email today; phone + push covers it. Could add later.
- **GDPR Article 17 strict compliance** — app is US-only; CCPA is the binding statute. If EU launch happens, audit the gap.

## Open questions / decisions still pending

None — all eight policy decisions are made and recorded above.

Engineering decisions still to make at implementation time:

- **JWT secret for sponsorship management magic links**: reuse the existing `SECRET_KEY`? Separate secret? Recommend separate so revoking the management surface doesn't invalidate user auth tokens.
- **`/sub` redirect destination** (resolved 2026-09-23): `/sub` is a thin redirect shim straight to `/plans` — the app's own paywall, not a marketing-site bounce (see `.claude/rules/domain-subscriptions.md`).
- **Magic link delivery from Twilio or Made-it-Home's existing SMS service**: reuse `sms_service` for consistency; just a different template.

Implementation kicks off at Phase 1.
