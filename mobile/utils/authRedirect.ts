import AsyncStorage from '@react-native-async-storage/async-storage'
import type { Href } from 'expo-router'

/**
 * Where the user was headed before we forced them through authentication.
 *
 * A universal link can launch the app from a killed state straight onto a
 * gated screen (e.g. /g/{code}, /r/{code}). If the user isn't signed in we
 * send them to login — but they must come back to exactly where they were
 * going, not get dumped on the home tab. The gated screen stashes its path
 * here before redirecting to login; the auth flow replays it on the way
 * into the app (existing user → login success; new user → after profile +
 * onboarding).
 *
 * Persisted to AsyncStorage (not just memory) so it survives the app being
 * killed mid-flow — reading an SMS OTP routinely backgrounds the app, and
 * a memory-constrained device may kill it before the code is entered. A
 * short TTL bounds stale replay: if the user abandons auth and signs in
 * for something unrelated later, an old destination is ignored rather than
 * yanking them somewhere unexpected.
 */
const PENDING_ROUTE_KEY = '@MadeItHome:pendingRoute'
const PENDING_ROUTE_TTL_MS = 15 * 60 * 1000 // 15 minutes

interface StoredRoute {
  path: string
  ts: number
}

// Internal absolute paths only — mirrors the backend redirect-safety rule
// (.claude/rules/security.md): must start with "/" and not "//", so a
// captured value can never become a protocol-relative / off-app target.
function isSafeInternalPath(path: string): boolean {
  return path.startsWith('/') && !path.startsWith('//')
}

/**
 * The path to stash for a screen reached by URL: its pathname plus its
 * string query params, so e.g. `/plans?checkout=success` (the Stripe return)
 * replays onto the same step after login. Only meant for routes WITHOUT
 * dynamic segments — expo-router folds those into the params too, and they'd
 * be duplicated into the query. Non-string (array) params are dropped.
 */
export function pathWithQuery(
  pathname: string,
  params: Record<string, string | string[] | undefined>
): string {
  const query = Object.entries(params)
    .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
  return query ? `${pathname}?${query}` : pathname
}

/** Capture the destination to return to after auth. No-op for unsafe paths. */
export async function setPendingRoute(path: string): Promise<void> {
  if (!isSafeInternalPath(path)) return
  const value: StoredRoute = { path, ts: Date.now() }
  try {
    await AsyncStorage.setItem(PENDING_ROUTE_KEY, JSON.stringify(value))
  } catch {
    // benign: Best-effort: failing to stash a destination must never break the
    // redirect to login that the caller is about to perform.
  }
}

/** Discard any captured destination (e.g. on logout or an unrelated flow). */
export async function clearPendingRoute(): Promise<void> {
  try {
    await AsyncStorage.removeItem(PENDING_ROUTE_KEY)
  } catch {
    // benign: ignore
  }
}

/**
 * The route to land on after authentication: the captured destination if
 * there is a fresh, valid one (read once, then cleared), else the app home.
 * `wasPending` lets callers tell whether they're honoring a deep link or
 * doing the normal post-auth landing.
 */
export async function consumeLandingRoute(): Promise<{
  href: Href
  wasPending: boolean
}> {
  let path: string | null = null
  try {
    const raw = await AsyncStorage.getItem(PENDING_ROUTE_KEY)
    if (raw) {
      await AsyncStorage.removeItem(PENDING_ROUTE_KEY)
      const stored = JSON.parse(raw) as Partial<StoredRoute>
      if (
        typeof stored.path === 'string' &&
        isSafeInternalPath(stored.path) &&
        typeof stored.ts === 'number' &&
        Date.now() - stored.ts < PENDING_ROUTE_TTL_MS
      ) {
        path = stored.path
      }
    }
  } catch {
    // benign: Corrupt/unreadable value → fall back to home.
  }
  return {
    // typedRoutes is on, so a runtime path string needs the Href cast;
    // it's validated as an internal path at capture and consume time.
    href: (path ?? '/(tabs)') as Href,
    wasPending: path != null,
  }
}
