/**
 * Pure helpers behind services/api.ts's failure reporting (unit-tested here so
 * the fetch layer stays thin).
 *
 * Owner decision 2026-09-06: every API failure reports, throttled. A 5xx is an
 * error; a network failure is a warning. Each (kind, method, templated path,
 * status) reports at most once per REPORT_WINDOW_MS per app run — a phone in a
 * dead zone with a background heartbeat every few minutes must not flood
 * Bugsnag, but the first failure of every kind must be visible.
 *
 * Related: services/api.ts, services/errorReporting.ts, services/apiReporting.test.ts.
 */

export const REPORT_WINDOW_MS = 10 * 60 * 1000

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
// Path words that are followed by a user-facing code (invite / share / gift /
// referral codes are access tokens — they must never reach the tracker).
const CODE_BEARING = new Set([
  'join',
  'redeem',
  'referrals',
  'r',
  'c',
  'g',
  // /groups/{invite_code}/members — the invite code no longer follows a
  // "join" segment now that joining is POST /groups/{invite_code}/members.
  'groups',
])

/**
 * `/sessions/3f2…/photos?x=1` → `/sessions/{id}/photos`: no ids, no codes, no
 * query. A segment is an identifier if it's a UUID, numeric, contains a digit
 * (no route word does; most codes do), or follows a code-bearing word — the
 * rule that catches codes WITHOUT a digit (a group invite code is
 * token_urlsafe(16): 22 chars of [A-Za-z0-9_-], ~2% of them digit-less).
 */
export function templatePath(endpoint: string): string {
  const segments = endpoint.split('?')[0].split('/')
  return segments
    .map((segment, i) => {
      if (segment === '') return segment
      const afterCodeWord = i > 0 && CODE_BEARING.has(segments[i - 1])
      if (UUID_RE.test(segment) || afterCodeWord || /\d/.test(segment))
        return '{id}'
      return segment
    })
    .join('/')
}

export type FailureKind = 'network' | 'server'

/** A `fetch` that never produced a response. Message mirrors the underlying
 *  error ("Network request failed") so existing retry/queue checks keep
 *  matching on it. */
export class NetworkError extends Error {
  readonly isNetworkError = true

  constructor(
    readonly method: string,
    readonly endpoint: string,
    readonly cause: unknown
  ) {
    super(cause instanceof Error ? cause.message : 'Network request failed')
    this.name = 'NetworkError'
  }
}

export function failureKey(
  kind: FailureKind,
  method: string,
  endpoint: string,
  status?: number
): string {
  const path = templatePath(endpoint)
  return status === undefined
    ? `${kind}:${method} ${path}`
    : `${kind}:${method} ${path} ${status}`
}

/**
 * "The request never got an answer from OUR server": a fetch that failed, or
 * a 5xx page with a non-JSON body (the load balancer during a deploy, a
 * Cloudflare 52x). This — and only this — is when a check-in may be queued and the
 * session cleared optimistically; a 5xx WITH a JSON body is a server that
 * answered and refused, and must surface as an error.
 */
export function isNetworkFailure(err: unknown): boolean {
  if (err instanceof NetworkError) return true
  const e = err as {
    isNetworkError?: boolean
    isGatewayError?: boolean
    statusCode?: number
    message?: string
  } | null
  if (e?.isNetworkError || e?.isGatewayError) return true
  if (typeof e?.statusCode === 'number') return false
  const msg = typeof e?.message === 'string' ? e.message : ''
  return msg.includes('Network') || msg.includes('fetch')
}

/**
 * Retry / queue decision for a failed API call. Status-based first (a 5xx or
 * a gateway page is retryable no matter what text came back), then the
 * network-failure shapes. Replaces the old `msg.includes('Network')` sniffing.
 */
export function isRetryableApiError(err: unknown): boolean {
  if (err instanceof NetworkError) return true
  const e = err as {
    isNetworkError?: boolean
    statusCode?: number
    message?: string
  } | null
  if (e?.isNetworkError) return true
  if (typeof e?.statusCode === 'number') {
    return e.statusCode >= 500 || e.statusCode === 408 || e.statusCode === 429
  }
  const msg = typeof e?.message === 'string' ? e.message : ''
  return msg.includes('Network') || msg.includes('fetch')
}

/** Resolve `promise`, or `fallback` after `ms` — never lets optional context
 *  gathering (a native connectivity read) hold up the caller. */
export function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  fallback: T
): Promise<T> {
  return new Promise<T>(resolve => {
    const timer = setTimeout(() => resolve(fallback), ms)
    promise.then(
      value => {
        clearTimeout(timer)
        resolve(value)
      },
      () => {
        clearTimeout(timer)
        resolve(fallback)
      }
    )
  })
}

/** Once-per-key-per-window gate. */
export class ReportThrottle {
  private readonly last = new Map<string, number>()

  constructor(private readonly windowMs: number = REPORT_WINDOW_MS) {}

  shouldReport(key: string, now: number = Date.now()): boolean {
    const previous = this.last.get(key)
    if (previous !== undefined && now - previous < this.windowMs) return false
    this.last.set(key, now)
    return true
  }

  reset(): void {
    this.last.clear()
  }
}
