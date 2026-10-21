# App Store & Google Play Listing Copy

Ready-to-paste store metadata for Made It Home, with character limits noted.
Copy is drawn from the actual feature set (Circle of Trust, check-in/SOS sessions,
live location during sessions, Acknowledge, pre-deadline reminders, all-clear,
group plan, phone-only auth, SOS always free) — keep it accurate to shipped behavior.

Related: `docs/mobile-release.md` (how to build/submit), `.claude/rules/domain-subscriptions.md`
(iOS shows no purchase CTAs — Apple 3.1.1).

## App Store Connect

**App name** (≤30): `Made It Home` (12)

**Subtitle** (≤30) — pick one:
- `Check in. Get home safe.` (24)  ← keyword string below assumes this one
- `Someone's got your back.` (24)
- `Let your people know you're ok` (30)

**Promotional text** (≤170, editable anytime without review):
> Heading out? Set a check-in time. If you don't make it, the people you trust are alerted automatically — with your location. Peace of mind in one tap. (149)

**Keywords** (≤100, no spaces after commas):
> `safety,SOS,emergency,walk,night,solo,travel,location,panic,alert,contacts,family,dating,curfew,GPS` (98)

Student/campus variant:
> `safety,SOS,emergency,walk,night,solo,campus,student,location,panic,alert,contacts,rideshare,curfew` (98)

Keyword rules: single words beat phrases (Apple auto-combines them with each other and
with the name/subtitle); never repeat words already in the name or subtitle (indexed
separately). The strings above exclude *check / in / home / safe* because the chosen
subtitle already covers them — re-dedupe if the subtitle changes. Avoid trademarks
(Uber/Lyft) — Apple rejects competitor/brand terms.

**Description** (≤4000):
```
Made It Home is the simple way to let the people you trust know you got where you're going.

Set a check-in time before you head out. Make it there, tap to check in — done. Don't check in? The people in your Circle of Trust are alerted automatically, with your location, so help can find you fast.

No accounts. No passwords. Just your phone number and the people who care about you.

HOW IT WORKS
• Set a check-in — tell us when you expect to be safe: walking home, a first date, a late run, a long drive.
• Check in when you arrive — one tap and everyone knows you're okay.
• Miss it, and we act — if you don't check in, your Circle of Trust is notified with your last location and a link to help.

FEATURES
• Circle of Trust — add the people who should know if something's off. They get a text and can tap Acknowledge to let you know they saw it.
• SOS — need help right now? Alert your whole circle instantly. SOS is always free.
• Live location — share where you are with your Circle of Trust while a check-in is active.
• Friendly reminders — a nudge before your deadline so a check-in never slips your mind.
• All clear — mark yourself safe and everyone gets the good news.
• Group plan — cover up to 5 people (family, roommates, or friends) under one subscription.

WHY MADE IT HOME
Walking home after dark. Meeting someone new. Traveling alone. Or just wanting someone to know you got in okay — Made It Home has your back without getting in your way.

Made It Home helps the people you trust look out for you. It is not a replacement for 911 or emergency services — in a life-threatening emergency, always call your local emergency number.
```

**What's New** (v1.0):
> Welcome to Made It Home! Set a check-in, build your Circle of Trust, and let the people who matter know you're safe. This is our very first release — tell us what you think.

## Google Play

**App name** (≤30): `Made It Home` (12)

**Short description** (≤80):
> Set a check-in time. If you don't make it home, your people get alerted. (72)

**Full description** (≤4000): the App Store Description above works as-is.

Play has **no keywords field** — ranking comes from title + short + full description.
Make sure these terms appear naturally (2–3× each, no stuffing — Play penalizes it):
*personal safety, check-in, emergency contacts, location sharing, SOS / panic button,
walking home, solo travel, family safety.* ("emergency contacts" is a search term people
use, not our in-app vocabulary — the feature is Circle of Trust; keep it here for ASO only)

## Notes

- **Safety disclaimer is intentional.** The "not a replacement for 911" line is honest
  (the app relies on your contacts, not dispatchers) and helps with Apple review of
  safety apps that imply guaranteed response.
- **iOS pricing language.** Per Apple 3.1.1, the iOS build shows no purchase CTAs — keep
  the iOS listing free of "subscribe now" / price copy. "Group plan … one subscription"
  as a factual feature line is fine. The Play listing can be more direct about pricing.
