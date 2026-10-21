/**
 * Error reporting (Bugsnag today) — the ONLY module that talks to @bugsnag/expo.
 * Everything else reports through `notify()` / `leaveBreadcrumb()` / `setUser()`.
 *
 * Why it looks like this (2026-09-06 — not one mobile event had ever reached
 * Bugsnag):
 *   - `startErrorReporting()` is SYNCHRONOUS and runs first thing in app/_layout.tsx,
 *     so the native-module probe and the root ErrorBoundary have a live client.
 *     The old version awaited a dynamic import inside a bare `catch {}`.
 *   - The key is read from `extra.bugsnag.apiKey` — the shape @bugsnag/expo and
 *     the EAS source-map plugin both read. app.config.js refuses to evaluate for
 *     a staging/production bundle without it, so a keyless build or OTA update
 *     can no longer ship with reporting silently off.
 *   - A missing key or a failed start is logged loudly, never swallowed.
 *   - `notify()` skips errors the API layer already reported (`markReported`),
 *     so a screen re-reporting the same failure is a no-op, not a duplicate.
 *   - Outside production/staging nothing is sent (enabledReleaseStages); in
 *     __DEV__ `notify()` echoes to the console — started or not — so nothing
 *     is silent on a dev machine that happens to carry the key.
 *
 * PII: only the user id is ever attached (`setUser(id)`), never name or phone
 * (.claude/rules/security.md), and `scrubEvent` redacts E.164 numbers from
 * every event's messages, context and breadcrumbs on-device before delivery
 * (a native `Linking.openURL('sms:…')` rejection embeds the number).
 *
 * Related: app/_layout.tsx (start + ErrorBoundary), services/api.ts (network /
 * 5xx reporting), components/EnvBanner.tsx (in-app smoke test),
 * scripts/error-reporting-smoke.js (key check from a dev machine),
 * services/errorReporting.test.ts.
 */

import Bugsnag from '@bugsnag/expo'
import type { BreadcrumbType, Event } from '@bugsnag/core'
import NetInfo from '@react-native-community/netinfo'
import Constants from 'expo-constants'
import * as Updates from 'expo-updates'
import { APP_ENV } from '../constants/config'

export const ENABLED_RELEASE_STAGES: readonly string[] = [
  'production',
  'staging',
]
export type Severity = 'error' | 'warning' | 'info'

let started = false
let startFailure: string | null = null
// Errors already reported lower in the stack (services/api.ts). A screen that
// catches the same error and calls notify() again must not create a duplicate.
const reported = new WeakSet<object>()

// E.164 numbers anywhere in event text → "[PHONE]" (the mobile twin of the
// backend's redaction in app/core/error_reporting.py).
const PHONE_RE = /\+[1-9]\d{6,14}/g
export function redactPhones(text: string): string {
  return text.replace(PHONE_RE, '[PHONE]')
}
function redactValue(value: unknown): unknown {
  if (typeof value === 'string') return redactPhones(value)
  if (Array.isArray(value)) return value.map(redactValue)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        redactValue(v),
      ])
    )
  }
  return value
}
/** Global onError: scrub every text field of the event before delivery. */
export function scrubEvent(event: Event): boolean {
  for (const error of event.errors) {
    error.errorMessage = redactPhones(error.errorMessage)
  }
  if (event.context) event.context = redactPhones(event.context)
  if (event.groupingHash) event.groupingHash = redactPhones(event.groupingHash)
  for (const crumb of event.breadcrumbs) {
    crumb.message = redactPhones(crumb.message)
    crumb.metadata = redactValue(crumb.metadata) as typeof crumb.metadata
  }
  return true
}

/** The key baked into this bundle (`extra.bugsnag.apiKey`), or undefined. */
export function readApiKey(): string | undefined {
  const extra = Constants.expoConfig?.extra as
    | { bugsnag?: { apiKey?: string } }
    | undefined
  return extra?.bugsnag?.apiKey || undefined
}

/** Start the client. Idempotent. Returns whether reporting is live. */
export function startErrorReporting(): boolean {
  if (started) return true
  const apiKey = readApiKey()
  if (!apiKey) {
    startFailure = 'MOBILE_BUGSNAG_API_KEY was empty when this bundle was built'
    if (ENABLED_RELEASE_STAGES.includes(APP_ENV)) {
      console.error(
        `[error-reporting] ${startFailure} — errors in this ${APP_ENV} build will NOT be reported`
      )
    }
    return false
  }
  try {
    Bugsnag.start({
      apiKey,
      releaseStage: APP_ENV,
      enabledReleaseStages: [...ENABLED_RELEASE_STAGES],
      appVersion: Constants.expoConfig?.version,
      onError: scrubEvent,
      metadata: {
        app: {
          channel: Updates.channel ?? 'none',
          updateId: Updates.updateId ?? 'embedded',
          runtimeVersion: Updates.runtimeVersion ?? 'unknown',
        },
      },
    })
    started = true
    startFailure = null
    return true
  } catch (err) {
    startFailure = err instanceof Error ? err.message : String(err)
    console.error('[error-reporting] start failed', err)
    return false
  }
}

export function isStarted(): boolean {
  return started
}

export function startFailureReason(): string | null {
  return startFailure
}

/** Flag an error as already reported so a later notify() is a no-op. */
export function markReported(error: unknown): void {
  if (typeof error === 'object' && error !== null) reported.add(error)
}

export function wasReported(error: unknown): boolean {
  return typeof error === 'object' && error !== null && reported.has(error)
}

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error))
}

/**
 * 4xx statuses this API uses for the ACCOUNT'S STATE — the UI routes each one
 * (re-login, paywall, "already have a session", expired invite, profile
 * incomplete, rate limit) and they are never a defect. Everything else in 4xx
 * (400 payload, 403/404 client-vs-server disagreement, 405 route drift, 422
 * schema) is a bug on one side and IS reported. A screen that expects a
 * specific 400 (the wrong-OTP path) opts out itself.
 */
const ACCOUNT_STATE_STATUSES: readonly number[] = [401, 402, 409, 410, 428, 429]
export function isExpectedRefusal(error: unknown): boolean {
  const status = (error as { statusCode?: number } | null)?.statusCode
  return typeof status === 'number' && ACCOUNT_STATE_STATUSES.includes(status)
}

/**
 * Report a caught error. `context` names where it happened (kebab-case, e.g.
 * 'request-otp', 'notifications.save-token'); `metadata` lands in a
 * "context" tab — never put a phone number or a name in it. Skips what the
 * API layer already reported and ordinary 4xx refusals (a wrong OTP is not
 * an error in this app).
 */
export function notify(
  error: unknown,
  context: string,
  metadata?: Record<string, unknown>,
  severity: Severity = 'error'
): void {
  if (wasReported(error) || isExpectedRefusal(error)) return
  report(error, context, metadata, severity)
}

/**
 * Report unconditionally (no `reported` check) — for the API layer, which
 * flags the error as reported synchronously and sends in the background.
 * `groupingHash` overrides Bugsnag's stack-based grouping for errors built at
 * one code line (every API failure is a `new Error` in one place).
 */
export function report(
  error: unknown,
  context: string,
  metadata?: Record<string, unknown>,
  severity: Severity = 'error',
  groupingHash?: string
): void {
  const err = toError(error)
  // Anything that will not actually reach Bugsnag — no client, or a release
  // stage the SDK silently drops (a dev machine that carries the key) — is
  // echoed to the console so nothing is silent locally.
  const delivered = started && ENABLED_RELEASE_STAGES.includes(APP_ENV)
  if (__DEV__ && !delivered) {
    console.error(`[error-reporting:${context}]`, err, metadata ?? '')
  }
  if (!started) {
    // Not marked: an error notified before the client started (or in a
    // keyless build) must stay reportable once it is.
    return
  }
  markReported(error)
  markReported(err)
  Bugsnag.notify(err, (event: Event) => {
    // The global onError (scrubEvent) has already run by now — scrub what
    // this callback adds itself.
    event.context = redactPhones(context)
    event.severity = severity
    if (groupingHash) event.groupingHash = redactPhones(groupingHash)
    if (metadata) {
      event.addMetadata(
        'context',
        redactValue(metadata) as Record<string, unknown>
      )
    }
  })
}

export function leaveBreadcrumb(
  message: string,
  metadata?: Record<string, unknown>,
  type: BreadcrumbType = 'manual'
): void {
  if (!started) return
  Bugsnag.leaveBreadcrumb(message, metadata, type)
}

export function setUser(id: string): void {
  if (!started) return
  Bugsnag.setUser(id)
}

/**
 * Send a deliberate test event and resolve with the delivery outcome (the
 * EnvBanner "test error reporting" action). Not started, a filtered release stage, an
 * offline device (the SDK would silently queue the event and report success)
 * and a delivery failure all resolve `ok: false`.
 */
export async function sendSmokeTest(): Promise<{
  ok: boolean
  detail: string
}> {
  if (!started) {
    return { ok: false, detail: startFailure ?? 'Bugsnag is not started' }
  }
  if (!ENABLED_RELEASE_STAGES.includes(APP_ENV)) {
    return {
      ok: false,
      detail: `release stage "${APP_ENV}" is never reported — run with EXPO_PUBLIC_APP_ENV=staging`,
    }
  }
  const net = await NetInfo.fetch().catch(() => null)
  if (net && net.isConnected === false) {
    return { ok: false, detail: 'device is offline — nothing was sent' }
  }
  return new Promise(resolve => {
    Bugsnag.notify(
      new Error('Bugsnag smoke test from the app'),
      (event: Event) => {
        event.context = 'smoke-test'
        event.severity = 'info'
        event.addMetadata('smoke', {
          releaseStage: APP_ENV,
          updateId: Updates.updateId ?? 'embedded',
        })
      },
      (deliveryError: unknown) => {
        if (deliveryError) {
          const message =
            deliveryError instanceof Error
              ? deliveryError.message
              : String(deliveryError)
          resolve({ ok: false, detail: `delivery failed: ${message}` })
        } else {
          resolve({
            ok: true,
            detail: `accepted by Bugsnag under release stage "${APP_ENV}"`,
          })
        }
      }
    )
  })
}
