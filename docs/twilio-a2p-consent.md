# Twilio A2P 10DLC — SMS Consent & Campaign Reference

This is the source-of-truth for our SMS consent disclosures and the evidence
Twilio needs for A2P 10DLC campaign vetting. Update it whenever the consent
copy, the set of messages we send, or the opt-in surfaces change.

## What Twilio requires (consent form)

Every point where a user submits **their own** phone number for SMS must show an
explicit opt-in form with all of:

1. Phone number input field
2. Consent checkbox that is **not pre-selected** (actively checked by the user)
3. Clear description of the message **types**
4. Message **frequency** disclosure
5. **Message & data rates** disclaimer
6. **HELP and STOP** instructions
7. Links to **Terms of Service** and **Privacy Policy**
8. Submit button with clear language

## Where consent is collected (opt-in surfaces)

| Surface | File | Mechanism |
| --- | --- | --- |
| Mobile login (primary opt-in) | `mobile/app/(auth)/login.tsx` | Unchecked checkbox; **Send Code is disabled until checked** (hard gate) |
| Web `/login` + circle-join | `backend/app/web/templates/fragments/auth_form.html` | `required` checkbox in the form |
| Web sponsorship checkout | `backend/app/web/templates/fragments/sponsorship_auth_form.html` | `required` checkbox |
| Web referral claim | `backend/app/web/templates/fragments/referral_auth_form.html` | `required` checkbox |

All web surfaces include the shared partial
`backend/app/web/templates/fragments/sms_consent.html`. The disclosure copy is
single-sourced on mobile in `SMS_CONSENT_COPY` (`mobile/constants/config.ts`) and
kept textually identical in the web partial.

### Consent copy (verbatim)

> **Promise (prominent, standalone):** We never sell your number and never send
> spam — you'll only ever get texts tied to relevant activity in the app.
>
> **Agreement (the checkbox label):** I agree to receive automated text messages
> from Made It Home at the number above: sign-in codes, check-in and safety
> alerts, and occasional account messages (referrals & billing). Message
> frequency varies, and message & data rates may apply.
>
> **Help line:** Text HELP for assistance with the app or STOP to cancel anytime.
>
> Plus Terms and Privacy Policy links.

## Opt-In Policy Proof (for the Twilio campaign form)

The real opt-in lives in the app (behind nothing, but not a crawlable web page),
so Twilio accepts a **hosted screenshot**:

1. Run the app, open the login screen, screenshot the consent form (checkbox
   unchecked, Send Code disabled).
2. Upload to a publicly accessible link (Google Drive / OneDrive).
3. Paste that URL into the campaign's **Opt-In Policy Proof** field.
4. Record the URL here: **PROOF URL: _<paste after upload>_**

The public web `/login` form also carries the same disclosure and can be linked
directly as supporting evidence.

## Per-flow coverage — who gets SMS and how they consented

Verified by tracing every Twilio send site (`.send_sms` / `gated_send_sms`).

| Flow | New number entered? | First SMS via | How consent is obtained |
| --- | --- | --- | --- |
| **Login / OTP** | Yes — own | Twilio (`services/otp.py`) | The opt-in form above |
| **Referral success** | No | Twilio → your **own** number (`services/referral.py`) | Login opt-in (copy names "referrals") |
| **Group / sponsorship lapse** | No (join via invite code) | Twilio → member's **own** number (`services/sub_lapse_notifications.py`) | Login opt-in (copy names "billing") |
| **Add to Circle** | Yes — third party's | User's **native SMS app** (`Linking sms:`), not Twilio. First Twilio msg = welcome after the recipient accepts on the web (lander `POST /circles/{code}/accept`, or the logged-in `/circles` page) | Recipient accepts the invite on the web; the lander's accept form carries the consent disclosure |
| **Sponsorship request** | Yes — third party's | User's **native SMS app**; `sponsorship_requests.py` sends no Twilio SMS | No Twilio message reaches a non-consented number |
| **Emergency alerts / all-clear** | No | Twilio → circle members who **accepted** (`services/session_tasks.py`) | Consent = the accept action |

**Takeaway:** only the self-opt-in points (mobile + web login) need the embedded
form. Everything else messages an already-consented app user on their own number
or reaches a third party only via native SMS / after they opt in themselves.

## Registered message samples (per category, for campaign use-case)

- **2FA / account access (OTP):** "Your Made It Home verification code is:
  123456. This code expires in 15 minutes."
- **Safety alert (SOS / missed check-in):** "🚨 Emergency Alert: {name} may need
  help. Please check on them immediately."
- **All-clear:** "✅ All Clear: {name} has checked-in and marked themselves safe!"
- **Circle welcome (post-accept):** "Made It Home: You're now {name}'s emergency
  contact. We'll text you only if they need help. To opt out, reply STOP, but
  note that this also removes you as their emergency contact."
- **Account / billing (lapse):** "Your group plan from {name} ends {date}.
  Subscribe to keep coverage: https://madeitho.me/sub"
- **Referral:** "Great news! {name} used your Made It Home referral. You both got
  a free month!"

**2026-09-27: re-register these samples.** The 2026-09-26/27 owner copy
review (`docs/notifications.md` §4) changed the live template for three of
the six sampled categories (all-clear, circle welcome, group lapse); the OTP
and safety-alert samples never matched the live text to begin with, so they
go in the same console trip. Referral is unchanged and still matches. See
`docs/notifications.md` §4 for the full comparison table and the 12
server-sent SMS with no registered sample. The verbatim strings to register:

- **2FA / OTP** (unchanged text — registering only to finally match live):
  "Made It Home: Your verification code is {otp_code}\n\nIt expires in 15
  minutes."
- **Safety alert (SOS body, M1):** "Made It Home EMERGENCY: {name} activated
  SOS and needs help now. Please check on them: {phone}."
- **All-clear:** "✅ All clear: {name} checked in and marked themselves safe."
- **Circle welcome (post-accept):** "Made It Home: You're now in
  {inviter_name}'s Circle of Trust. We'll text you only if they need help —
  save this number so alerts reach you. Reply STOP to opt out; that also
  removes you from their Circle."
- **Group lapse T_ZERO:** "Your Group Plan from {owner_name} ends {date}.
  Subscribe to keep access: https://madeitho.me/sub"

## STOP / HELP / START handling

- **STOP / STOPALL / UNSUBSCRIBE / CANCEL / END / QUIT** and **HELP** and
  **START / UNSTOP / YES** are owned by **Twilio Advanced Opt-Out** (auto-reply +
  carrier-level enforcement). See `backend/app/api/v1/endpoints/inbound_sms.py`.
- The backend mirrors opt-out state and cascades it to Circle-of-Trust
  membership, and supports a soft-stop confirmation gate for non-protected
  phrases ("please stop", "remove me", …). See `backend/app/services/sms_opt_out.py`.
- Opted-out numbers are excluded from all alert dispatch; a later START restores
  the relationship in place.

## Tests

- `backend/tests/test_sms_consent_disclosure.py` — asserts `/login` renders the
  full disclosure and that all four web phone-entry forms include the partial.
- `mobile/constants/config.test.ts` — guards `SMS_CONSENT_COPY` against losing a
  required element.
