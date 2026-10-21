# Mobile rotation runbook

What to do when something the mobile app reads changes — a Twilio phone
number, a Bugsnag key, a marketing URL, the app domain. Each row below
maps the change to the right rotation channel so you don't ship an App
Store / Play Store review when you don't need one.

## Rotation channels, fastest → slowest

| Channel              | What it can change                                                 | Reaches users                                          | Effort                                    |
| -------------------- | ------------------------------------------------------------------ | ------------------------------------------------------ | ----------------------------------------- |
| **Backend env var**  | Any value served by `GET /api/v1/config`                           | Next mobile cold start (cached until then)             | Update Secrets Manager + roll ECS service |
| **EAS Update (OTA)** | Anything in the JS bundle: Bugsnag key, dependency bumps, JS logic | Next app launch with network                           | `eas update --channel <env>`              |
| **App release**      | Native modules, permissions, bundle ID, native config              | Days–weeks (Apple/Google review) + user-driven updates | Full release pipeline                     |

## Decision matrix

| Thing you're changing                                  | Channel             | Why                                                                                  |
| ------------------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------ |
| Twilio sender number (`SMS_DISPLAY_NUMBER`)            | **Backend env var** | Served by `/config` — mobile reads at cold start, cache replaces on next launch.     |
| Support email (`SUPPORT_EMAIL`)                        | **Backend env var** | Same — surfaced via `appConfig.supportEmail`.                                        |
| App / short / marketing domain                         | **Backend env var** | `APP_DOMAIN`, `SHORT_DOMAIN`, `MARKETING_ORIGIN`. Terms + privacy URLs derive from MARKETING_ORIGIN server-side. |
| Bugsnag API key (`MOBILE_BUGSNAG_API_KEY`)             | **EAS Update**      | Baked into `extra.bugsnag.apiKey` at bundle time; rotate the EAS environment variable, then publish via `npm run update:<env>` (never a bare `eas update` — it would ship an empty key and app.config.js now refuses to). |
| Any JS/TS code change                                  | **EAS Update**      | Standard OTA path.                                                                   |
| Stripe publishable key (if switching Stripe accounts)  | **App release**     | The publishable key is only consumed by the web checkout flow today; pivoting to in-app SDK would also be an app release because it's a new native module. |
| Bundle ID, permissions, new native module              | **App release**     | Native config; cannot OTA.                                                           |
| API base URL (`mobile/constants/config.ts:WEB_ORIGINS`) | **EAS Update**      | The URL is hard-coded per env at build time; an OTA bundle replaces it.              |

## Procedure: backend env var rotation

1. Update the value in `infra/secrets/<env>.secrets.env`.
2. `infra/aws/scripts/populate-secrets.sh <env>` to push to Secrets Manager.
3. Roll the ECS service so the running task picks up the new secret:
   ```
   aws ecs update-service \
     --cluster madeithome-cluster-<env> \
     --service madeithome-web-<env> \
     --force-new-deployment --region us-west-2
   ```
4. Verify: `curl https://<app-domain>/api/v1/config | jq` shows the new value.
5. Mobile picks it up on each user's next cold start. There's no push;
   it's eventually-consistent on the cache TTL (which is "until the
   user kills the app").

## Procedure: EAS Update (OTA) rotation

Used for the Bugsnag key and any JS-side code change.

1. Update the value in the EAS environment the channel is bound to
   (`preview` for staging, `production` for production):
   `eas env:update --environment <preview|production> --name MOBILE_BUGSNAG_API_KEY --value <new>`
   (or `populate-secrets.sh <env>`, which writes the same variable).
2. Build the new JS bundle and publish to the env channel — always through the
   npm script, which passes `--environment` so the key and `EXPO_PUBLIC_APP_ENV`
   are injected (a bare `eas update` makes `app.config.js` throw):
   ```
   cd mobile
   npm run update:<staging|production> -- --message "rotate bugsnag key"
   ```
3. Users get the new bundle on next app launch (assuming network at launch).
   `expo-updates` checks the channel at launch and applies updates before
   rendering.
4. Verify by checking the Bugsnag dashboard — events should attribute to
   the new project's key within minutes of users launching.

Caveat: OTA bundles cannot change native code, native permissions, or
the bundle ID. If the update fails to apply (size, network), the user
keeps the prior bundle and we have no way to force the update. For
critical security rotations, follow up with a regular app release.

## Procedure: full app release

Used when none of the above can carry the change.

1. Bump `version` and (for iOS) `runtimeVersion.policy = "appVersion"`
   handles the rest — see `mobile/app.config.js`.
2. `eas build --platform all --profile production`.
3. `eas submit --platform ios` and `--platform android`.
4. Apple TestFlight + Play Internal Track first for staging users.
5. Store review: Apple 24–72 hours typical, Google a few hours.

## What's NOT in the rotation channels (and why)

- **API base URL per env.** It's evaluated at JS-bundle build time so
  the app knows where to talk before any network call. Changing it
  requires an EAS Update at minimum. Don't try to runtime-fetch
  this — there'd be no way to bootstrap.
- **EAS project ID** (`mobile/app.config.js → extra.eas.projectId`).
  Tied to the Expo project. Changing it would mean a new project and
  effectively a new app from the store's perspective.
- **Auth tokens.** Stored in `expo-secure-store` (Keychain/Keystore).
  Not in scope for "rotate via env var" — these are per-user, not
  per-env config.

## Tests gating the contract

- `backend/tests/test_app_config_endpoint.py` covers the `/config`
  endpoint shape. Mobile depends on every field listed there; adding
  fields is safe, renaming/removing breaks deployed app installs that
  can't upgrade until they hit the store, so the field set is
  effectively an API contract.
- Mobile fallback behavior (cache miss → fallback defaults; network
  fail → cached value) lives in `mobile/services/runtimeConfig.ts`
  and `mobile/store/useAppConfigStore.ts`. Manually verify when adding
  new fields by toggling airplane mode on a launch with a fresh
  install.
