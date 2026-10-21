"""Single source of truth for all user-facing notification copy.

Push titles/bodies and SMS message templates consumed by session_tasks.py
and notification_helpers.py. Centralised here so alert wording changes
touch one file.

Invariant: most events have one TITLE and one BODY — push uses TITLE + BODY,
SMS uses BODY only (or TITLE + "\n" + BODY where the SMS is a push's backup).
An SMS-only kind with no push at all (ALL_CLEAR) may collapse to a single
merged string instead, since there's no push to ever read a separate title.

Related: services/session_tasks.py, services/notification_helpers.py
"""

# --- Titles (push only) ---
# SOS and missed check-in bodies are deliberately distinct: an SOS is a
# deliberate act (3-second hold, ~zero false positives) while a missed
# check-in is a passive inference (often benign). Identical wording would
# force recipients to either panic on every forgotten timer or shrug at a
# real SOS. Copy owner-approved 2026-07-02 — see docs/flow-review.md §4.3
# (B2). The old per-type SOS/missed push titles were deleted 2026-09-27:
# circle alerts are SMS-only (owner decision 2026-09-22), so a push title was
# never sent — see docs/notifications.md §3.
SESSION_EXPIRED_TITLE = "⚠️ You missed your check-in"

# --- Bodies (push + SMS share these) ---
# {time} is the expected-return time in the OWNER's local time (from
# sessions.tz_offset_minutes); when the client didn't send an offset the
# NO_TIME variant is used instead — never render a UTC clock time.
ALERT_MISSED_BODY = (
    "Made It Home: {name} hasn't checked in and expected to be back by "
    "{time}. Please check on them: {phone}."
)
ALERT_MISSED_BODY_NO_TIME = (
    "Made It Home: {name} hasn't checked in on time. "
    "Please check on them: {phone}."
)
ALERT_SOS_BODY = (
    "Made It Home EMERGENCY: {name} activated SOS and needs help now. "
    "Please check on them: {phone}."
)
# Circle re-nudge: fires ALERT_REMINDER_DELAY_MINUTES after the circle was
# alerted if no member has tapped Acknowledge. Superseded on acknowledge / when
# the owner marks safe, so it only ever reaches a circle that went quiet.
ALERT_RENUDGE_BODY = (
    "Made It Home: still no word from {name} and no one has responded yet. "
    "Can you check on them? {phone}"
)
SESSION_EXPIRED_BODY = "We're alerting your Circle. Mark yourself safe if you're okay."
# The server-side pre-deadline reminder copy was deleted 2026-09-27: no
# backend code has ever sent it (the client's local ladder
# covers every rung except the at-deadline one — see the invariant in
# .claude/rules/domain-sessions-alerts.md). mobile/services/notifications.ts
# is now the sole source of truth for that copy; nothing here mirrors it.
# At-deadline (minutes_remaining == 0) variant — the old copy rendered
# "expires in 0 minutes". This one opens the grace window with urgency and
# also goes out as SMS (reaches a phone with notifications denied/DND).
SESSION_DEADLINE_TITLE = "⏰ Time's up"
SESSION_DEADLINE_BODY = (
    "Check in now, or your Circle will be alerted in about "
    "{grace_minutes} minutes."
)
# Owner push once ≥1 circle member has actually been reached (MISSED →
# ALERTED promotion) — the mobile active-session screen must never claim
# "notified" from the client clock (flow-review C1/3.4).
CIRCLE_ALERTED_TITLE = "Your Circle has been notified"
CIRCLE_ALERTED_BODY = (
    "We've alerted your Circle of Trust. Mark yourself safe when you can."
)
# A circle member ACKNOWLEDGED the alert — SMS-only broadcast (owner
# decision 2026-07-18, no pushes). Copy states exactly what a tap proves:
# a deliberate acknowledgement, never "on their way" (nobody promised to
# travel). The owner learns WHO acknowledged (their own contact); other
# members only learn that SOMEONE did — the acknowledger's identity is
# never revealed to the rest of the circle (they may not know each other,
# and may have no way to reach each other).
ALERT_ACKNOWLEDGED_OWNER_BODY = (
    "Made It Home: {acknowledger} acknowledged your alert."
)
ALERT_ACKNOWLEDGED_MEMBER_BODY = "Made It Home: {owner}'s alert was acknowledged."
# Fallback when the owner has no full_name (a hard-purged owner — every live
# alert's owner has one from signup, so this is defensive). Keeps the
# "Made It Home: " prefix of the named variant; owner-reviewed 2026-09-27.
ALERT_ACKNOWLEDGED_MEMBER_BODY_NO_NAME = (
    "Made It Home: Your contact's alert was acknowledged."
)
# Group-plan members when the owner's subscription lapses — previously the
# 7-day grace ran silently and access just vanished (flow-review E3/§4.2).
GROUP_PLAN_GRACE_TITLE = "Your Group Plan has ended"
GROUP_PLAN_GRACE_BODY = (
    "{owner}'s Group Plan ended, so your access ends in {days} days. "
    "Subscribe to keep using Made It Home."
)
# The all-clear SMS is a single line (title+body merged into one string,
# owner-approved 2026-09-27) — ALL_CLEAR is SMS-only, so no push ever reads a
# separate title.
ALL_CLEAR_SMS = "✅ All clear: {name} checked in and marked themselves safe."

# Appended to alert bodies when the data warrants it (both are
# permission-dependent and the copy must degrade gracefully): destination
# whenever available; battery only when critically low (see
# session_tasks.LOW_BATTERY_ALERT_THRESHOLD — a dying phone is signal, a
# half-full one is noise).
ALERT_DESTINATION_SUFFIX = " They were headed to {destination}."
ALERT_BODY_BATTERY_SUFFIX = " Last known battery: {level}%."
# SMS-only, appended per member (each alert row is that member's access
# token to the public alert page — map, callback, Acknowledge).
# Push recipients get the same via in-app alert details instead.
ALERT_DETAILS_SUFFIX = " Details: {link}"

# Owner push+SMS when a circle member's alert delivery is refused/exhausted
# (opted out, no phone, retries used up) — the honest "we couldn't reach
# them" dead-end. {name} resolves from the circle membership's display_name
# for the refused delivery's phone id (services/notification_outbox.py
# _escalate_unreachable), falling back to "a Circle member" when the
# membership can't be found. SMS body is TITLE + "\n" + BODY like the other
# owner SMS.
CONTACT_UNREACHABLE_TITLE = "Couldn't reach a Circle member"
CONTACT_UNREACHABLE_BODY = (
    "We couldn't reach {name} about your session. "
    "Try calling or texting them directly."
)

# Post-session data cleanup notification to session owner. {started_at} is
# session.created_at rendered in the owner's local time (tz_offset_minutes)
# as "Sep 22 · 9:40 PM" — see notification_helpers._format_started_at. With
# no offset, DATA_DELETED_BODY_NO_TIME is sent instead (never a UTC time).
# No destination fallback: this notification always has a session to point
# at.
DATA_DELETED_TITLE = "Session data deleted"
DATA_DELETED_BODY = (
    "Your {started_at} session's location history and photo have been "
    "automatically deleted."
)
# Used when the session has no tz_offset_minutes: a timestamp without the
# owner's offset could only be UTC, and a UTC clock time is never rendered
# (see the {time} note above), so this variant names no time at all.
DATA_DELETED_BODY_NO_TIME = (
    "Your session's location history and photo have been automatically deleted."
)

# Post-acceptance confirmation SMS to new circle member — also the consent
# record for future alert texts. Front-loads the STOP consequence so a
# recipient who later texts STOP isn't surprised that opting out also
# removes them from someone's Circle, and asks them to save the number
# (step one of the DND-bypass guidance, flow-review §4.4b).
CIRCLE_WELCOME_SMS = (
    "Made It Home: You're now in {inviter_name}'s Circle of Trust. "
    "We'll text you only if they need help — save this number so "
    "alerts reach you. Reply STOP to opt out; that also removes you "
    "from their Circle."
)

# --- Opt-out cascade pushes (to owner whose contact left) ---

# A Circle member left, Circle of Trust still has others.
CONTACT_OPTED_OUT_TITLE = "Circle member unsubscribed"
CONTACT_OPTED_OUT_BODY = (
    "{name} asked us to stop texting them, so we removed them from "
    "your Circle of Trust. Add someone else to replace them."
)

# A Circle member left FROM THE WEB (POST /circles/{code}/leave), Circle of
# Trust still has others — same cascade shape as CONTACT_OPTED_OUT (STOP)
# but its own outbox kind (NotificationKind.CONTACT_LEFT) so the audit trail
# tells the two triggers apart. The emptied-circle kinds below are shared by
# both reasons.
CONTACT_LEFT_TITLE = "Circle member left"
CONTACT_LEFT_BODY = (
    "{name} left your Circle of Trust. Add someone else to replace them."
)

# Last Circle member left, no active session.
CIRCLE_EMPTIED_TITLE = "Your Circle of Trust is empty"
CIRCLE_EMPTIED_BODY = (
    "{name} left your Circle of Trust, and they were the last member. "
    "Add someone to alert on your next session."
)

# Last Circle member left during an active session. Phrased to nudge
# the owner toward an on-time check-in given no one will be alerted if
# they miss.
CIRCLE_EMPTIED_MID_SESSION_TITLE = "Your Circle of Trust is empty"
CIRCLE_EMPTIED_MID_SESSION_BODY = (
    "{name} left your Circle of Trust and they were the last member "
    "of your Circle. Check in on time — no one will be alerted if "
    "you miss it."
)

# --- Account-holder texted STOP (their own phone, not just a contact's) ---
# Goes only to the user themselves (not their circles' owners).
ACCOUNT_HOLDER_STOPPED_TITLE = "You unsubscribed from Made It Home"
ACCOUNT_HOLDER_STOPPED_BODY = (
    "Texts are off — including your sign-in codes and alerts about "
    "people whose Circle you're in. Tap to manage."
)

# Sent {grace_days} after the initial STOP if the user hasn't re-enabled
# texts, but ONLY when the worker actually set a subscription to cancel:
# an active, auto-renewing, self-paid Stripe subscription
# (sms_unsubscribe_tasks._act_on_unsubscribed_user). A user with no such
# subscription (free trial, sponsored/gift, group-plan member, or one
# that's already non-renewing) gets no push — there's nothing "set to
# cancel" to confirm. Confirms the cancel-at-period-end has been set.
ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_TITLE = "Subscription set to cancel"
ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_BODY = (
    "It's been {grace_days} days since you unsubscribed from texts. "
    "Your Made It Home subscription will end at your next billing date. "
    "Tap to re-subscribe or restart texts."
)

# --- Soft-stop gate (sent by our webhook to non-protected stop phrases) ---
# Personalized because they fire BEFORE the recipient is opted-out, so we
# can still dispatch via the SMS API. Five cases keyed off SenderProfile
# (services/sms_opt_out.py::get_sender_profile). Case A always has exactly
# one owner, so it names them; case D names them too when there's exactly
# one, and falls back to the count-only wording at 2+ (SenderProfile.
# owner_names is populated only in the single-owner shape).

SOFT_STOP_GATE_SINGLE_OWNER = (
    "Made It Home: We can stop texting you, but that would also remove "
    "you from {name}'s Circle of Trust — you wouldn't be alerted if "
    "they need help. Reply STOP to confirm, or ignore this to stay."
)

SOFT_STOP_GATE_MULTI_OWNER = (
    "Made It Home: We can stop texting you, but that would also remove "
    "you from {count} people's Circles of Trust. You will not be "
    "alerted if they need help. Reply STOP to confirm, or ignore "
    "this to stay."
)

SOFT_STOP_GATE_ACCOUNT_ONLY = (
    "Made It Home: We can stop texting you, but you also won't get "
    "sign-in codes for your account. Reply STOP to confirm, or ignore "
    "this to stay."
)

SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE = (
    "Made It Home: We can stop texting you, but that would also remove "
    "you from {name}'s Circle of Trust AND stop your account sign-in "
    "codes. Reply STOP to confirm, or ignore this to stay."
)

SOFT_STOP_GATE_ACCOUNT_AND_CONTACT = (
    "Made It Home: We can stop texting you, but that would also remove "
    "you from {count} people's Circles of Trust AND stop your "
    "account sign-in codes. Reply STOP to confirm, or ignore this to stay."
)

SOFT_STOP_GATE_GENERIC = (
    "Made It Home: Did you mean to opt out? Reply STOP to confirm, "
    "or ignore this to keep getting our texts."
)
