# SMS STOP-flow setup (Twilio Messaging Service)

One-time operator config to enable the opt-out flow shipped in the
`feat(opt-out): …` commit series. Without these console steps, STOP
texts trigger Twilio's default replies (no brand identification, no
consequence framing) and our inbound webhook never fires.

Repeat for each environment's Messaging Service (staging and production
each have their own).

## 1. Inbound webhook URL

**Twilio Console → Messaging → Services → [your service] → Integration**

Set **Incoming Messages → Send a webhook** to:

```
POST https://{env-domain}/webhooks/sms/twilio-inbound
```

Same hostname pattern as the delivery webhook (already configured).

Twilio's Advanced Opt-Out treats six keywords as "STOP-equivalent":
`STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` (case-insensitive,
single-keyword bodies only). Any of them triggers the configuration in
§2 and our cascade webhook. Three more are "START-equivalent": `START`,
`UNSTOP`, `YES`.

## 2. Advanced Opt-Out — STOP confirmation

**Same screen → Opt-Out Management → Edit Advanced Opt-Out**

Enable Advanced Opt-Out. In the **Opt-Out Confirmation Message** field, paste:

```
Made It Home: Unsubscribed from texts. You will no longer be notified
if anyone who added you needs help. Text START to resubscribe to texts.
```

This replaces Twilio's default "You have successfully unsubscribed…"
generic message. The brand prefix satisfies CTIA / 10DLC requirements;
the consequence line lets the recipient realize they just removed
themselves as somebody's emergency contact and points them to the undo.

## 3. Advanced Opt-Out — HELP reply

In the **Help Response Message** field, paste:

```
Made It Home (safety alerts). STOP to opt out. Help: support@madeithomeapp.com
```

## 4. START — leave default

The default carrier "You have successfully been re-subscribed…" reply is
fine — we don't customize it. Behind the scenes our webhook still fires
for `START` / `UNSTOP` / `YES` and restores `OPTED_OUT` memberships
back to `ACTIVE` **in the same row** (no re-add required, no new
invitation flow). The row was preserved at STOP time precisely so this
restoration is in-place — auto-restore for the "I didn't realize" case.

Soft-stop intent phrases (`please stop`, `stop texting`, `remove me`,
`leave me alone`, `don't text me`, `no more texts`) are NOT Twilio-
protected — they reach our webhook, which sends a personalized
confirmation gate so the sender realizes the cost of opting out before
they type `STOP`. There's a **24-hour cooldown per phone** on this
gate: a contact who keeps replying "please stop, please stop" gets at
most one gate SMS per day.

## 5. Smoke test

From a phone we control:

1. Get added to a test owner's Circle of Trust.
2. Text **STOP** to the Messaging Service number.
   - You should receive the **Made It Home: Unsubscribed from texts…** message above.
   - The test owner should receive a **"Emergency contact removed"** push within seconds.
3. Text **START**.
   - You should receive Twilio's default "You have successfully been re-subscribed…" message.
   - Verify in admin that your Circle membership status is back to `ACTIVE` (not a new row).
4. Text **please stop** (soft-stop intent).
   - You should receive the personalized 1c gate ("We can stop texting you, but…").
   - Verify in admin that your phone's `sms_opted_out_at` is still NULL — the gate is a confirmation, not an action.

## 6. Failure modes

- If STOP from a phone with no Made It Home record arrives, our webhook
  no-ops on the cascade (nothing to cascade). Twilio still honors the
  opt-out on their side and sends our 1b confirmation.
- If the soft-stop gate SMS dispatch fails (provider outage), the
  webhook acks 200 to Twilio (logged via Bugsnag) so Twilio doesn't
  retry indefinitely.
- If the inbound webhook URL is misconfigured (404), Twilio retries
  with backoff and pages on persistent failure — set up an alert on
  the Messaging Service's error dashboard.
