# Mobile Release: TestFlight (iOS) & Google Play (Android)

How to build and distribute the Made It Home mobile app via EAS. This covers the
two beta channels — Apple **TestFlight** and Google Play **Internal testing** —
plus a standalone **APK** for direct sideload/QA.

Related files:
- `mobile/eas.json` — build + submit profiles
- `mobile/app.config.js` — bundle IDs, version, EAS project ID
- `mobile/package.json` — `build:*` / `submit:*` scripts
- `docs/mobile-rotation-runbook.md` — when a change needs a full release vs an OTA `eas update`

## Distribution matrix

| Artifact | Profile | Format | Goes to | Requires |
| --- | --- | --- | --- | --- |
| iOS beta | `production` | `.ipa` (store) | TestFlight | Apple Developer + ASC app |
| Android beta | `production` | `.aab` | Play Internal testing | Play Console + service account |
| Android sideload | `preview` | `.apk` | Direct install / manual QA | nothing (download artifact) |

> Google Play does **not** accept APKs on any track (internal/alpha/beta/production)
> for apps created after Aug 2021 — it requires the AAB. The `preview` APK is for
> sideloading onto devices outside Play only.

## One-time setup

### 1. iOS identifiers in `eas.json`

`submit.production.ios` carries `appleTeamId` (`6S752DDCCQ`) — not a secret, so it's
committed. That's all interactive submit needs. Optionally add `ascAppId` (the numeric
App ID from the app's App Store Connect URL,
`https://appstoreconnect.apple.com/apps/<THIS_NUMBER>/...`) once the app record exists,
so repeat submits skip the app-selection prompt.

### 2. iOS submit auth

**Non-interactive submit is set up and working (as of 2026-07-04).** An App Store
Connect API key (`[Expo] EAS Submit`, Key ID `78NKQHHV9N`) is stored on **EAS servers**,
and `submit.production.ios` carries `appleTeamId` + `ascAppId` (`6787024225`). So a full
unattended deploy is one command:

```
eas build -p ios --profile production --auto-submit --non-interactive
```

No Apple 2FA needed — the stored key authenticates and `ascAppId` resolves the app. (The
key was auto-created/saved by EAS during the first interactive `eas submit`; to rotate or
inspect it: `eas credentials -p ios` → App Store Connect API Key.) Fallback if the key is
ever removed: `eas submit -p ios` interactively prompts for the Apple login and re-saves a
key.

Signing certs + provisioning profiles are managed by EAS automatically — the first
`eas build -p ios` prompts once to generate and store them on EAS servers (done: cert
`2D541662CF06EF4F8BA72005FC926B1B`, profiles for `com.madeithome.app` +
`com.madeithome.app.LiveActivity`).

### 3. Android credentials (Google service account)

1. Play Console → Setup → API access → create/link a Google Cloud service account
   with the **Release manager** permission.
2. Download its JSON key to `mobile/credentials/google-service-account.json`.

The Android upload keystore is generated and stored by EAS on the first
`eas build -p android` — **back it up** (`eas credentials`); losing it blocks future
Play updates for this package.

## Build numbers

`eas.json` sets `cli.appVersionSource: "remote"` and `autoIncrement: true` on the
release profiles, so EAS owns `ios.buildNumber` / `android.versionCode` and bumps
them each build. `version` in `app.config.js` (currently `1.4.0`) is the user-facing marketing
version — bump it by hand for a real release, and for every NATIVE change
(`runtimeVersion` follows it, so the bump keeps new OTA bundles off older
binaries; `app.config.js` comments record why each version bumped); the build number auto-increments for
repeated TestFlight/Play uploads of the same version.

## Release steps

Run from `mobile/`. You must be logged in: `eas whoami` (currently `ragarwal6397`).

### iOS → TestFlight

```bash
npm run build:ios       # eas build --platform ios --profile production
npm run submit:ios      # eas submit --platform ios --profile production
```

After submit, the build processes in App Store Connect (a few minutes to ~an hour),
then appears under TestFlight. Add internal testers (up to 100, no review) or an
external group (requires a first-build Beta App Review). Export-compliance is
pre-answered via `ITSAppUsesNonExemptEncryption: false` in `app.config.js`.

### Android → Play Internal testing

```bash
npm run build:android   # eas build --platform android --profile production  (AAB)
npm run submit:android  # eas submit --platform android --profile production (track: internal)
```

The AAB uploads to the **internal** track. In Play Console, add testers to the
Internal testing track and share the opt-in link. Promote internal → production in
Play Console when ready (or change `track` in `eas.json` and re-submit).

### Android → sideload APK

```bash
npm run build:apk       # eas build --platform android --profile preview  (APK)
```

EAS returns a download URL for the `.apk`. Share it; installing requires "Install
unknown apps" enabled on the device. This path never touches Play.

### Build both stores at once

```bash
npm run build:release   # eas build --platform all --profile production
```

## Store-review sign-in (phone OTP apps)

Reviewers can't receive real SMS, so create an **admin-managed account grant** with a
fixed login code — no env vars, no redeploy. Set it up in the admin at
`/admin/account-grants`:

1. **New account grant** → Phone = reviewer number (E164, e.g. `+12345678900`), Label =
   "App Store reviewer", Fixed login code = a **random** 6-digit (e.g. `680684`), Enabled = on.
2. Done. The account now accepts the fixed code with no SMS and is comped so gated
   check-in is reachable.

How it works: an enabled `AccountGrant` with an `otp_code` makes `otp_service.send_otp`
store the fixed code and skip SMS (code never logged); `verify_otp` validates it normally;
on login `ensure_comp_access` grants a far-future `COMP` subscription. An empty `otp_code`
→ standard SMS OTP. See `.claude/rules/domain-subscriptions.md`.

**Time-box it:** toggle the row's `Enabled` off after approval (and on again for the next
review) — instant, audited (`AdminAccessLog`), no redeploy. Disabled → the account falls
back to normal SMS OTP (which no one can receive) → effectively locked.

Give the credentials to the stores:
- **App Store Connect** → your app → **App Review Information → Sign-In required**: User
  Name = phone number, Password = the fixed code. Notes: "Phone-OTP login — enter the
  number, request the code, then enter the fixed code above."
- **Google Play Console** → **App content → App access** → "restricted" → same number + code.

**Security:** use a random code (not `123456`); it's a shared credential, so keep it in the
(private) store consoles and disable the grant when not under review.

**Account-deletion URL (Google Play requirement):** when you fill in the Data safety form
(Play Console → Data safety → Delete account URL), use
`https://app.madeithomeapp.com/account/delete` (renamed from `/delete-account` on
2026-09-23, with no redirect — the app hasn't been submitted yet, so there is no live
listing value to update).

## Tech debt — do at the next Expo SDK upgrade

**Migrate the Live Activity off `expo-live-activity` → `expo-widgets`.**
`expo-live-activity` is **deprecated** (its README points to Expo's official
`expo-widgets`) and we carry a local `patch-package` patch
(`mobile/patches/expo-live-activity+0.4.2.patch`) that adds native behavior the
deprecated package never exposed (see `services/liveStatus.ts`):
`startOrUpdateActivity` / `endAllActivities`, plus a fully **branded rewrite of
the widget UI** (`ios-files/LiveActivityView.swift` + `LiveActivityWidget.swift`):
fixed-size brand mark, hero countdown, a progress bar that fills left → right
over the whole session, and an overdue treatment (danger background, count-up
"how long overdue" timer, pre-baked "Time's up" copy) that flips **on-device at
the deadline** via `staleDate`/`context.isStale` — no app process needed, no
end+restart. Any expo-widgets migration must re-implement all of that.
The brand mark shown on the card + Dynamic Island is bundled from
`mobile/assets/liveActivity/MadeItHomeMark.png` (≤4KB per the iOS limit).

- `expo-widgets` is the supported successor and covers what we use (Live Activity
  start/update/end, Dynamic Island, countdown/progress), but it's **versioned to
  the Expo SDK and has no SDK-54 build** (lowest is `sdk-55`). So it can't be
  adopted until we upgrade Expo SDK ≥ 55.
- The SDK upgrade is also when `expo-live-activity` is most likely to break (a
  dead lib on a new SDK), so migrate *as part of* that upgrade: replace the
  library, drop the patch + the `patch-package` postinstall (if nothing else
  needs it), rewrite the iOS activity in `expo-widgets` (`DeliveryActivity`
  SwiftUI model), and **device-test** it (start → relaunch → mark safe → card
  clears; start → kill → complete elsewhere → clears on next launch).
- Android is unaffected — no Live Activities there; it stays on the Notifee
  ongoing notification.

## Notes

- OTA-eligible changes (JS-only) ship via `eas update`, not a rebuild — see
  `docs/mobile-rotation-runbook.md` for the "release vs OTA" decision table.
- Plan selection is in-app on both platforms; only the Stripe **checkout page**
  opens in the browser. The iOS external-checkout link relies on the US
  external-purchase carve-out — **this is the App Review risk surface**; if a
  build is rejected over it, the fallback is reverting to web-only-no-CTA (git
  has that version). See `.claude/rules/domain-subscriptions.md`.
- `MOBILE_BUGSNAG_API_KEY` must exist as an EAS **environment variable** in the
  `preview` (staging builds/updates) and `production` environments
  (`eas env:list --environment preview|production`). Each `eas.json` build
  profile is bound to its EAS environment (`environment`), and OTA updates go
  through `npm run update:staging` / `npm run update:production` (which pass
  `--environment`), so the key — and `EXPO_PUBLIC_APP_ENV` — reach every bundle.
  `app.config.js` **throws** when `EXPO_PUBLIC_APP_ENV` is staging/production
  and the key is empty: a keyless bundle can no longer ship with reporting off.
- Verify reporting before shipping: `MOBILE_BUGSNAG_API_KEY=<key> npm run error-reporting:smoke`
  (key + network, from your machine), then in a staging/dev-client run tap the
  EnvBanner's **· test error reporting** link — it toasts the delivery result. Source
  maps upload on EAS builds via the `eas-build-on-success` script
  (`@bugsnag/plugin-expo-eas-sourcemaps` + `@bugsnag/cli`).
