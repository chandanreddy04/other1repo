# Expo SDK 54 → 57 Upgrade Plan

Status: **planned / not started.** Authored 2026-08-02.

> **Headline verdict:** SDK **55 is reachable now**; SDK **56/57 is currently BLOCKED**
> by `@bugsnag/expo` (whose newest release is 55.0.0). Treat this as **two projects**:
> (1) execute `54 → 55` now, hold there; (2) advance to `56/57` only once the gating
> modules ship support (or we swap crash reporter / re-validate natives). This is the
> "one lagging native module holds the upgrade hostage" risk — confirmed with data below.

Companion docs: `docs/manual-test-plan.md` (device QA), `docs/deployment.md` (EAS/OTA).

### SDK 54 support timeline (why this isn't purely elective)
Expo publishes **no fixed calendar EOL** per SDK. Policy in practice: an SDK gets
**critical fixes until roughly the next SDK release**, with a **~1-year** effective
lifetime; Expo Go / EAS services support the recent SDKs, older ones age out.
- **SDK 54 shipped September 2025.** With **SDK 57 current (Aug 2026)**, 54 is ~3
  versions / ~11 months back — **at the tail of its active-support window**.
- **Expo Go for SDK 54** is still available on the App Store / Play Store.
- **Watch:** unconfirmed reports of EAS Update rejecting SDK 54
  (`"sdkVersion 54.0.0 is not supported"`, expo/expo #45275/#45279 — flagged
  incomplete). This app ships **OTA on production**, so a loss of EAS Update
  support for 54 would break the OTA pipeline — monitor it; it raises the priority
  of at least reaching **55**.
- SDK 54 was the **last SDK with Legacy Architecture** support — N/A here (already New Arch).

---

## 1. Current state (baseline to diff against)

| Thing | Value |
|---|---|
| Expo SDK | ~54.0.33 |
| React Native / React | 0.81.5 / 19.1.0 |
| Architecture | **New Architecture ON** (`newArchEnabled: true`) — biggest migration already done |
| Native project | **committed `ios/`** + custom **`modules/`** (not pure managed) |
| Patch | `patches/expo-live-activity+0.4.2.patch` (native iOS Swift widget, applied via `patch-package` postinstall) |
| Build/OTA | EAS build; `expo-updates` OTA on the **production** channel; `runtimeVersion` follows appVersion (currently 1.2.0) |
| npm `overrides` | `react-dom` 19.1.0, `shell-quote` 1.10.0, `postcss` ^8.5.25, `brace-expansion@5.0.6`→5.0.9, `metro.ws` 7.5.11, `react-native` 0.81.5 (defensive pin — see history: a prior `npm audit fix` pulled RN 0.86 nested) |

---

## 2. Compatibility matrix — the crux (registry-verified 2026-08-02)

| Module | Current | Latest available | Supports target SDK? | Risk |
|---|---|---|---|---|
| `expo` / `expo-router` | 54 | **57.0.9** | tracks SDK — moves with `expo install` | — |
| `react-native` / `react` | 0.81.5 / 19.1.0 | 0.86.2 / — | each SDK bumps RN; take what `expo install --fix` picks | — |
| **`@bugsnag/expo`** | ^54 | **55.0.0 (no 56/57)** | **caps at SDK 55** | 🔴 **hard blocker past 55** |
| `@bugsnag/plugin-expo-eas-sourcemaps` | ^54 | tracks bugsnag | same cap | 🔴 |
| **`expo-live-activity`** | 0.4.2 (patched) | 0.4.2 stable / 0.5.0-alpha1 | even the alpha's devDep pins `expo ~54.0.0` → **no real 55+ build** | 🟠 high — young module, custom patch |
| `@maplibre/maplibre-react-native` | 11.3.6 | **11.3.6 (no newer)** | peer is open (`expo>=54`, `rn>=0.80`) → *not* version-locked, but native RN-0.84+ compat **unverified** | 🟡 medium |
| `@notifee/react-native` | 9.1.8 | **9.1.8 (no newer)** | peer `react-native: *` → not version-locked, native compat **unverified** | 🟡 medium |
| `react-native-reanimated` | 4.1.1 | 4.5.3 | tracks RN — newer exists | 🟢 (RN-coupled) |
| `react-native-worklets` | 0.5.1 | 0.11.3 | pairs with reanimated | 🟢 |
| `nativewind` / `react-native-css-interop` | 4.1.23 / 0.2.x | 4.2.6 / 0.2.6 | newer exists | 🟢 |
| `expo-notifications` / `-screens` / `-safe-area-context` / `-updates` | SDK-54 pins | — | move via `expo install --fix` | 🟢 |

**Reading of the matrix:**
- **`@bugsnag/expo` is a hard version ceiling at SDK 55.** There is no 56/57 build. Going past 55 breaks mobile crash reporting unless Bugsnag ships newer **or** we replace it (e.g., Sentry, which has strong Expo support).
- **`maplibre` and `notifee` are not version-locked** (permissive peers), but neither has a release *newer* than what we run, and native compat with RN 0.84+/New-Arch changes at 56/57 is unverified — **device-test required**, with a swap contingency if they break.
- **`expo-live-activity` is the fragile long pole** — no real 55+ release, plus our custom native patch. Highest single-item risk.

---

## 3. Target & sequencing decision

- **Now:** execute **`54 → 55`** as a self-contained, shippable project. All gating modules have a 55-compatible path (`@bugsnag/expo@55` exists; maplibre/notifee permissive; reanimated/worklets/nativewind have newer; live-activity is SDK-54/55-era + patch).
- **Hold at 55.** Do **not** start 56/57 until the gate below clears.
- **Gate to 56/57** (all must be true):
  1. `@bugsnag/expo` ships 56/57 **— or —** we decide to migrate crash reporting to Sentry.
  2. `maplibre` + `notifee` verified working on the target RN on device (or replaced).
  3. `expo-live-activity` has a target-SDK release (or the patch is confirmed to re-apply + compile).
  Track these; revisit when Expo ships the next SDK or when Bugsnag releases.

---

## 4. Guiding principles

- **One SDK per hop.** Even though the immediate target is just 55, the same discipline applies later for 56 and 57. Never skip.
- **Branch per hop**, merge only after a clean EAS build + device-QA pass.
- **Let `npx expo install --fix` pick versions** for all `expo-*`/RN/react — don't hand-pin. You'll rewrite the `react-native` override each hop.
- **Freeze mobile feature work** during a hop.
- **New Arch is already on** — don't toggle it.

---

## 5. Risk register

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Bugsnag caps at 55** — blocks 56/57 | Hold at 55; open the "wait vs. swap to Sentry" decision before attempting 56 |
| R2 | **`expo-live-activity` patch** won't re-apply / won't compile; module lags SDK | **Stabilize the pending widget redesign on 54 first** (per project notes it "never compiled locally"); regenerate `patch-package` against the resolved version each hop; coordinate with the maintainer / consider vendoring the module |
| R3 | **maplibre** native break on new RN | Device-test session trail maps every hop; contingency: pin, patch, or evaluate alternative |
| R4 | **notifee** native break on new RN (notifications are safety-critical) | Device-test all notification paths; contingency: replace notifee with expo-notifications-only or another lib |
| R5 | **committed `ios/` + custom `modules/`** drift | Re-run prebuild/CNG reconciliation; update `modules/` for the new Expo Modules API; resolve native build errors before QA |
| R6 | **npm `overrides` staleness** (shell-quote/postcss/brace-expansion/metro.ws/RN pin) | Reconcile each hop: the RN pin must move to the new RN; the security overrides (added 2026-08-02) may become unnecessary — re-run `npm audit` and prune |
| R7 | **OTA/runtimeVersion** — native changes can't OTA | New `runtimeVersion` + new build; keep `production` channel on the old runtime until the new build rolls; plan store review + force-update |
| R8 | **reanimated/worklets** New-Arch regressions (jank, worklet crashes) | Only surface on device — weight QA toward animations/gestures |

---

## 6. Phase 0 — Pre-flight (once, before the 55 hop)

- [ ] **Baseline:** confirm current `main` is green — `make verify`, a known-good EAS build, and a **full `manual-test-plan.md` pass on 54** as the reference.
- [ ] **Stabilize `expo-live-activity`** on 54 (land the pending redesign green) so you're not regenerating a broken patch.
- [ ] **Confirm the 55 matrix** with `npx expo install --fix --dry-run` behavior + each gating module's 55 support (bugsnag@55 ✓; maplibre/notifee peer ✓; live-activity resolve).
- [ ] **Toolchain:** Xcode / Android SDK / EAS build image for the RN that SDK 55 pulls.
- [ ] Freeze mobile feature work.

## 7. The `54 → 55` hop playbook

1. Branch `chore/expo-sdk-55` off `main`.
2. `npx expo install expo@^55` → `npx expo install --fix` (aligns expo-*, RN, react).
3. Bump gating natives to 55-compatible: `@bugsnag/expo@55` + `@bugsnag/plugin-expo-eas-sourcemaps@55`, `react-native-reanimated`/`worklets`, `nativewind`/`css-interop`. Verify maplibre 11.3.6 + notifee 9.1.8 resolve (peers permit).
4. **Rewrite the `react-native` override** to the new RN; **re-run `npm audit`** and prune/retarget the security overrides (shell-quote/postcss/brace-expansion) that may no longer be needed.
5. **Regenerate the Live Activity patch** — the resolved `expo-live-activity` will differ, so `patches/expo-live-activity+0.4.2.patch` stops applying. Re-apply the Swift widget changes → `npx patch-package expo-live-activity`.
6. **Reconcile native:** prebuild against the committed `ios/`; update custom `modules/` for the new Expo Modules API; clear native build errors.
7. Static gates: `make mobile-tsc`, `make mobile-lint`, `make mobile-test` (bump `jest-expo`), `make mobile-audit`.
8. **EAS dev/preview build, iOS + Android** — where lagging modules/patches actually surface.
9. **Device QA** (§8), both platforms.
10. Merge → ship a **new native build** to the internal TestFlight/Play track; bake; bump app version (runtimeVersion follows).

## 8. Verification & device-QA matrix (per hop, iOS + Android)

Automated (must pass): `make verify` (backend unaffected but keep green) + `make mobile-*` + clean EAS build both platforms.

Device QA — weighted to native (tie to `manual-test-plan.md`):

| Area | Why it's at risk |
|---|---|
| **Live Activity** — start, T-30/10/5/0 ladder, overdue flip (staleDate), end | patched native widget + RN bump |
| **Notifications** — notifee + expo-notifications, push receipt, ongoing/Android channel | notifee native compat |
| **Maps** — session trail, pulsing/stale dot | maplibre native compat |
| **Background location / gather** (`sessionGather`) | RN/native task changes |
| Camera / image-picker, deep links (`/g/ /r/ /sub /plans /subscription`), OTA apply, reanimated animations/gestures | broad RN surface |

## 9. Rollback

Each hop is a branch + a versioned build. If build/QA fails and the fix isn't quick, **abandon the branch, stay on the last shipped SDK.** One-at-a-time means a bad hop never endangers a shipped one.

## 10. Definition of done — SDK 55

- Green `make mobile-*` + clean EAS build (iOS + Android), device-QA pass, shipped + stable to internal track, `production` OTA channel healthy on the new runtime.
- Overrides reconciled (RN pin moved; stale security overrides pruned).

## 11. Gate & path to 56 / 57

Do not start until §3's gate clears. When it does, repeat §7 per hop (55→56, 56→57). The **crash-reporter decision** is the pivotal 56 prerequisite:
- **Wait for `@bugsnag/expo@56/57`**, or
- **Migrate to Sentry** (`@sentry/react-native` + `sentry-expo`), updating both mobile init and the EAS sourcemap upload; keep backend Bugsnag as-is or migrate in tandem.
Re-validate maplibre/notifee/live-activity on the target RN at that point.

## 12. Post-upgrade cleanup

- Re-run `npm audit` and **prune the 2026-08-02 security overrides** if the new SDK ships patched deps (esp. the exact `brace-expansion@5.0.6` override, which silently no-ops if the version moves).
- Confirm the 26 moderate `uuid` build-tooling vulns cleared (they should, via newer `@expo/config-plugins`/`xcode`).
- Remove any now-unnecessary `metro.ws` / RN overrides.

## 13. Effort

Dominated by native-module compat + the Live Activity patch + 2-platform device QA. The `54→55` hop is a focused multi-day effort **if** live-activity/maplibre/notifee cooperate; `56/57` is **calendar-gated** on third-party releases (Bugsnag especially), not just hands-on time.
