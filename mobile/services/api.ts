import NetInfo from '@react-native-community/netinfo'
import { API_BASE_URL } from '../constants'
import { markReported, notify, report } from './errorReporting'
import {
  NetworkError,
  ReportThrottle,
  failureKey,
  isRetryableApiError,
  templatePath,
  withTimeout,
  type FailureKind,
} from './apiReporting'
import {
  getAccessToken,
  getRefreshToken,
  setTokens as setSecureTokens,
  clearTokens as clearSecureTokens,
  initTokenStorage,
} from './tokenStorage'
import {
  AuthTokens,
  User,
  Session,
  CircleOfTrustMember,
  CircleOfTrustSettings,
  SubscriptionStatus,
  GroupPlan,
  GroupPlanMember,
} from '../types'

// Discriminated union of structured error details. Each variant
// corresponds to a backend `HTTPException(detail={code, ...})` shape.
// Callers branch on `details.code` and TS narrows to the right payload —
// if the backend renames a field, the compile breaks here instead of
// silently returning undefined at runtime.
//
// Codes not in this union show up at runtime as `details: undefined`
// and force callers to fall back to `error.code` (untyped string) and
// `error.message`. Add new variants here as new structured error
// surfaces ship.
export type ApiErrorDetails =
  | { code: 'phone_opted_out'; support_number: string }
  | { code: 'blocked_opt_out'; phone: string }

export interface ApiError extends Error {
  statusCode?: number
  // A 502/503/504 whose body wasn't JSON — the gateway answered, our server
  // didn't. Drives isNetworkFailure() (queue-and-retry) vs a real refusal.
  isGatewayError?: boolean
  requiresSubscription?: boolean
  requiresProfile?: boolean
  retryAfter?: number
  // Top-level `code` carries whatever the backend sent (typed or
  // not) so callers can branch broadly. Use `details` for narrowing
  // to a known payload shape.
  code?: string
  details?: ApiErrorDetails
}

interface ValidationErrorDetail {
  loc?: string[]
  msg: string
}

function _narrowApiErrorDetails(raw: unknown): ApiErrorDetails | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined
  const code = (raw as { code?: unknown }).code
  if (typeof code !== 'string') return undefined
  if (code === 'phone_opted_out') {
    const sn = (raw as { support_number?: unknown }).support_number
    return typeof sn === 'string' ? { code, support_number: sn } : undefined
  }
  if (code === 'blocked_opt_out') {
    const phone = (raw as { phone?: unknown }).phone
    return typeof phone === 'string' ? { code, phone } : undefined
  }
  return undefined
}

interface OutfitPhotoFile {
  uri: string
  type?: string
  fileName?: string
}

interface ReferralApplyResult {
  message: string
  free_credit_end: string
}

class ApiService {
  private readonly reportThrottle = new ReportThrottle()
  private static instance: ApiService
  private baseURL = API_BASE_URL
  private refreshPromise: Promise<boolean> | null = null

  private constructor() {}

  static getInstance(): ApiService {
    if (!ApiService.instance) {
      ApiService.instance = new ApiService()
    }
    return ApiService.instance
  }

  async init() {
    await initTokenStorage()
    await this.getHeaders(true)
  }

  /**
   * The single fetch seam. Every failure — no response at all, or a 5xx — is
   * reported to Bugsnag through the throttle, WITHOUT waiting on anything:
   * the error is flagged `reported` synchronously (so screens don't duplicate)
   * and the send happens in the background. Network failures are rethrown as
   * NetworkError (same message as the raw TypeError). Request breadcrumbs come
   * from @bugsnag/expo's own network plugin, not from here.
   */
  private async doFetch(
    endpoint: string,
    init: RequestInit
  ): Promise<Response> {
    const method = (init.method ?? 'GET').toUpperCase()
    let response: Response
    try {
      response = await fetch(`${this.baseURL}${endpoint}`, init)
    } catch (cause) {
      const err = new NetworkError(method, endpoint, cause)
      this.reportFailure('network', err, method, endpoint)
      throw err
    }
    if (response.status >= 500) {
      this.reportFailure(
        'server',
        new Error(
          `HTTP ${response.status} ${method} ${templatePath(endpoint)}`
        ),
        method,
        endpoint,
        response.status
      )
    }
    return response
  }

  private reportFailure(
    kind: FailureKind,
    err: Error,
    method: string,
    endpoint: string,
    status?: number
  ): void {
    // Whether or not this instance is sent, the caller's error is accounted for.
    markReported(err)
    if (
      !this.reportThrottle.shouldReport(
        failureKey(kind, method, endpoint, status)
      )
    )
      return
    void this.sendFailureReport(kind, err, method, endpoint, status)
  }

  private async sendFailureReport(
    kind: FailureKind,
    err: Error,
    method: string,
    endpoint: string,
    status?: number
  ): Promise<void> {
    // Connectivity is optional context: bounded so a stalled native read in
    // exactly the dead-zone case can't delay anything (the caller isn't
    // waiting on this anyway).
    const state = await withTimeout(NetInfo.fetch(), 1000, null)
    const connectivity = state
      ? {
          isConnected: state.isConnected,
          isInternetReachable: state.isInternetReachable,
          connectionType: state.type,
        }
      : {}
    // groupingHash: every API failure is a `new Error` built on one line, so
    // Bugsnag's stack grouping would fold every endpoint and status together.
    report(
      err,
      kind === 'network' ? 'api.network' : 'api.server',
      { method, endpoint: templatePath(endpoint), status, ...connectivity },
      kind === 'network' ? 'warning' : 'error',
      failureKey(kind, method, endpoint, status)
    )
  }

  private async getHeaders(includeAuth = true): Promise<HeadersInit> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }

    if (includeAuth) {
      const token = await getAccessToken()
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }
    }

    return headers
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      let bodyWasNotJson = false
      const error = await response.json().catch(() => {
        // benign: a non-JSON error body is expected from gateway pages
        bodyWasNotJson = true
        return { detail: 'Unexpected response' }
      })

      // Handle subscription required (402)
      if (response.status === 402) {
        const subscriptionError: ApiError = new Error(
          error.detail || 'Subscription required'
        )
        subscriptionError.statusCode = 402
        subscriptionError.requiresSubscription = true
        throw subscriptionError
      }

      // Handle OTP cooldown (429) — backend returns retry_after seconds
      if (response.status === 429) {
        const rateLimitError: ApiError = new Error(
          error.detail?.message || error.detail || 'Too many requests'
        )
        rateLimitError.statusCode = 429
        rateLimitError.retryAfter = error.detail?.retry_after
        throw rateLimitError
      }

      // Handle profile incomplete (428)
      if (response.status === 428) {
        // Profile incomplete - this should redirect to complete profile
        const profileError: ApiError = new Error(
          error.detail || 'Please complete your profile first'
        )
        profileError.statusCode = 428
        profileError.requiresProfile = true
        throw profileError
      }

      // Handle validation errors (422)
      if (response.status === 422 && error.detail) {
        if (Array.isArray(error.detail)) {
          // FastAPI validation error format
          const messages = error.detail
            .map(
              (err: ValidationErrorDetail) =>
                `${err.loc?.join('.') || 'Field'}: ${err.msg}`
            )
            .join(', ')
          throw new Error(messages)
        }
      }

      // Generic error path — always stamp `statusCode` so callers can
      // branch on specific codes (e.g. 410 Gone from /me/restore signals
      // grace expired → route to fresh-signup) without parsing the
      // error message.
      const messageFromDetail =
        typeof error.detail === 'string'
          ? error.detail
          : error.detail?.message ||
            (error.detail?.code ? String(error.detail.code) : null)
      const apiError: ApiError = new Error(
        messageFromDetail || error.message || `HTTP ${response.status}`
      )
      apiError.statusCode = response.status
      // Any non-JSON 5xx came from in front of the app (ALB, Cloudflare's
      // 52x pages) — the origin itself always answers JSON — so treat it as
      // the network failure it is (mark-safe queues, retries continue).
      apiError.isGatewayError = response.status >= 500 && bodyWasNotJson
      // Surface structured `detail.code` for callers that need to
      // branch on it — e.g. login.tsx renders the START recovery
      // surface on `phone_opted_out`, add-contact renders 4a on
      // `blocked_opt_out`.
      //
      // `details` is only set when the runtime shape matches a known
      // ApiErrorDetails variant; mis-shaped or unknown-code payloads
      // leave it undefined so consumers don't accidentally cast their
      // way into NaN/undefined-of-the-day bugs.
      if (typeof error.detail === 'object' && error.detail !== null) {
        if (typeof error.detail.code === 'string') {
          apiError.code = error.detail.code
        }
        apiError.details = _narrowApiErrorDetails(error.detail)
      }
      // 5xx was already reported by doFetch (context 'api.server'); a screen
      // that catches this and calls notify() must not create a duplicate.
      if (response.status >= 500) markReported(apiError)
      throw apiError
    }
    return response.json()
  }

  private async refreshTokens(): Promise<boolean> {
    // If a refresh is already in-flight, reuse it so concurrent 401s
    // don't race each other and invalidate the new token.
    if (this.refreshPromise) return this.refreshPromise

    this.refreshPromise = this.doRefreshTokens()
    try {
      return await this.refreshPromise
    } finally {
      this.refreshPromise = null
    }
  }

  private async doRefreshTokens(): Promise<boolean> {
    try {
      const refreshToken = await getRefreshToken()
      if (!refreshToken) return false

      const response = await this.doFetch('/auth/refresh', {
        method: 'POST',
        headers: await this.getHeaders(false),
        body: JSON.stringify({ refresh_token: refreshToken }),
      })

      if (response.ok) {
        const tokens: AuthTokens = await response.json()
        await this.setTokens(tokens)
        return true
      }
    } catch (err) {
      // A dead refresh logs the user out; an auth outage must be visible.
      // (Network failures were already reported by doFetch — notify dedupes.)
      notify(err, 'api.refresh-tokens')
    }
    return false
  }

  async setTokens(tokens: AuthTokens) {
    if (tokens.access_token && tokens.refresh_token) {
      await setSecureTokens(tokens.access_token, tokens.refresh_token)
    }
  }

  async clearTokens() {
    await clearSecureTokens()
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    retry = true
  ): Promise<T> {
    const headers = await this.getHeaders()
    const fetchOptions = {
      ...options,
      headers: {
        ...headers,
        ...options.headers,
      },
    }

    const response = await this.doFetch(endpoint, fetchOptions)

    if (response.status === 401 && retry) {
      const refreshed = await this.refreshTokens()
      if (refreshed) {
        return this.request(endpoint, options, false)
      }
      // Refresh failed — the session is truly dead. Clear the stale tokens so
      // we stop hammering 401s and the app's auth check routes back to login,
      // instead of leaving the user stuck with dead credentials mid-session.
      await clearSecureTokens()
    }

    return this.handleResponse<T>(response)
  }

  // Auth endpoints

  async requestOTP(
    phoneNumber: string
  ): Promise<{ success: boolean; message: string }> {
    return await this.request('/auth/request-otp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ phone_number: phoneNumber }),
    })
  }

  async verifyOTP(
    phoneNumber: string,
    otpCode: string
  ): Promise<{
    access_token: string
    refresh_token: string
    token_type: string
    is_new_user: boolean
    user?: User
    // Set when the user signs back in during the 30-day soft-delete
    // grace. The issued tokens authenticate only `/users/me/restore`
    // until the user calls it. Mobile routes to the Welcome Back screen
    // when this is true.
    deletion_pending?: boolean
    scheduled_deletion_at?: string | null
  }> {
    const response = await this.request<{
      access_token: string
      refresh_token: string
      token_type: string
      is_new_user: boolean
      user?: User
      deletion_pending?: boolean
      scheduled_deletion_at?: string | null
    }>('/auth/verify-otp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ phone_number: phoneNumber, otp_code: otpCode }),
    })

    await this.setTokens(response)
    return response
  }

  async resendOTP(
    phoneNumber: string
  ): Promise<{ success: boolean; message: string }> {
    return await this.request('/auth/resend-otp', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ phone_number: phoneNumber }),
    })
  }

  async logout() {
    await this.clearTokens()
  }

  // User endpoints
  async getCurrentUser(): Promise<User> {
    return this.request('/users/me')
  }

  async updateUser(data: Partial<User>): Promise<User> {
    return this.request('/users/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async uploadProfilePhoto(uri: string): Promise<User> {
    const token = await getAccessToken()
    const formData = new FormData()
    // React Native's FormData accepts object with uri/type/name for file uploads
    formData.append('file', {
      uri,
      type: 'image/jpeg',
      name: 'profile.jpg',
    } as unknown as Blob)

    const response = await this.doFetch(`/users/me/profile-photo`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    })

    return this.handleResponse(response)
  }

  // Account deletion — see docs/account-deletion-plan.md
  async deleteAccount(
    sponsorshipChoices?: Record<string, 'keep' | 'stop'>
  ): Promise<{
    soft_deleted: boolean
    scheduled_deletion_at: string
    grace_days: number
  }> {
    return this.request('/users/me', {
      method: 'DELETE',
      body: JSON.stringify({ sponsorship_choices: sponsorshipChoices ?? {} }),
    })
  }

  // Restore a soft-deleted account during the 30-day grace.
  // Caller must hold a token issued by verify-otp's deletion_pending
  // branch. Returns 410 Gone if the grace window has expired — the
  // mobile flow should treat that as "go through new-account signup."
  async restoreAccount(): Promise<User> {
    return this.request('/users/me/restore', {
      method: 'POST',
    })
  }

  // Check-in endpoints
  async getSessions(skip = 0, limit = 20): Promise<Session[]> {
    return this.request(`/sessions?skip=${skip}&limit=${limit}`)
  }

  async getActiveSession(): Promise<Session | null> {
    try {
      return await this.request('/sessions/active')
    } catch (error) {
      if (error instanceof Error && error.message.includes('404')) {
        return null
      }
      throw error
    }
  }

  async createSession(data: {
    expected_return_time: string
    destination?: string
    location_sharing_enabled?: boolean
  }): Promise<Session> {
    // Payload mirrors the backend SessionCreate schema exactly. The previous
    // version sent legacy fields (location_name, expected_duration_minutes,
    // outfit_photo_base64) the backend never accepted — every check-in
    // creation 422'd because the required expected_return_time was missing.
    const payload: Record<string, string | number | boolean> = {
      expected_return_time: data.expected_return_time,
      // Owner's UTC offset (minutes east of UTC) so alert SMS can render
      // "expected back by 10:30 PM" in local time. JS getTimezoneOffset()
      // returns minutes BEHIND UTC, hence the negation.
      tz_offset_minutes: -new Date().getTimezoneOffset(),
    }

    if (data.destination) {
      payload.destination = data.destination
    }

    if (data.location_sharing_enabled !== undefined) {
      payload.location_sharing_enabled = data.location_sharing_enabled
    }

    const delays = [1000, 2000, 4000]
    for (let attempt = 0; attempt <= delays.length; attempt++) {
      try {
        return await this.request<Session>('/sessions', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      } catch (error) {
        const msg = error instanceof Error ? error.message : ''
        // If server says active session exists, fetch and return it
        if (msg.toLowerCase().includes('already have an active session')) {
          const existing = await this.getActiveSession()
          if (existing) return existing
        }
        // Retry network failures and 5xx/gateway blips, never a 4xx refusal
        if (!isRetryableApiError(error) || attempt >= delays.length) throw error
        await new Promise(r => setTimeout(r, delays[attempt]))
      }
    }
    throw new Error('Failed to create session')
  }

  async uploadOutfitPhoto(
    sessionId: string,
    file: OutfitPhotoFile
  ): Promise<{ outfit_photo_url: string }> {
    const formData = new FormData()
    // React Native's FormData accepts object with uri/type/name for file uploads
    formData.append('file', {
      uri: file.uri,
      type: file.type || 'image/jpeg',
      name: file.fileName || 'outfit.jpg',
    } as unknown as Blob)
    // The endpoint keys the photo onto an existing session — session_id is a
    // required Form field, so the session must be created first.
    formData.append('session_id', sessionId)

    const token = await getAccessToken()
    const response = await this.doFetch(`/sessions/outfit-photos`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    })

    return this.handleResponse(response)
  }

  async completeSession(sessionId: string): Promise<Session> {
    // PUT per the backend contract — this POSTed before and every mark-safe
    // 405'd (found by backend/tests/test_mobile_api_contract.py).
    return this.request(`/sessions/${sessionId}/complete`, {
      method: 'PUT',
    })
  }

  async extendSession(
    sessionId: string,
    additionalMinutes: number
  ): Promise<Session> {
    // PUT + minutes_to_extend per the backend contract — this previously
    // POSTed additional_minutes and every extend attempt 405'd.
    return this.request(`/sessions/${sessionId}/extend`, {
      method: 'PUT',
      body: JSON.stringify({ minutes_to_extend: additionalMinutes }),
    })
  }

  /**
   * Adjust the post-session data purge date by ±7 days. Omitting `days`
   * keeps the historical single-extension behavior. Reductions are clamped
   * server-side to the floor (original deletion date or today, whichever is
   * later) — the client's canReduceRetention gate mirrors that math.
   */
  async adjustSessionRetention(
    sessionId: string,
    days?: number
  ): Promise<Session> {
    return this.request(`/sessions/${sessionId}/retention`, {
      method: 'PUT',
      ...(days !== undefined ? { body: JSON.stringify({ days }) } : {}),
    })
  }

  /**
   * Fetch one session by id. /sessions/active only returns ACTIVE sessions,
   * so the session screen's live mode polls this (via the store) to learn
   * the server-truth status transition (active → missed → alerted) — the
   * client clock must never claim the circle was notified.
   */
  async getSession(sessionId: string): Promise<Session> {
    return this.request(`/sessions/${sessionId}`)
  }

  async updateLocation(
    sessionId: string,
    latitude?: string,
    longitude?: string,
    batteryLevel?: number,
    batteryState?: string
  ): Promise<void> {
    // Coordinates are optional: an opportunistic heartbeat can report battery
    // alone when location is off. Coords are only sent when both are present.
    const payload: Record<string, string | number> = {}
    if (latitude !== undefined && longitude !== undefined) {
      payload.latitude = latitude
      payload.longitude = longitude
    }
    if (batteryLevel !== undefined) payload.battery_level = batteryLevel
    if (batteryState) payload.battery_state = batteryState
    return this.request(`/sessions/${sessionId}/locations`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  async getLocationHistory(
    sessionId: string
  ): Promise<{ latitude: string; longitude: string; recorded_at: string }[]> {
    return this.request(`/sessions/${sessionId}/locations`)
  }

  async sendSOS(location?: {
    latitude: number
    longitude: number
    battery_level?: number
    battery_state?: string
  }): Promise<Session> {
    // SOS is the panic button — retry network failures with backoff (like
    // createSession) so a flaky connection doesn't silently drop the alert.
    // The optional last-known location rides along so the first alert already
    // shows the map pin (the server enables location sharing for SOS).
    const delays = [1000, 2000, 4000]
    for (let attempt = 0; attempt <= delays.length; attempt++) {
      try {
        return await this.request<Session>('/sessions', {
          method: 'POST',
          body: JSON.stringify({ session_type: 'sos', ...location }),
        })
      } catch (error) {
        if (!isRetryableApiError(error) || attempt >= delays.length) throw error
        await new Promise(r => setTimeout(r, delays[attempt]))
      }
    }
    throw new Error('Failed to send SOS')
  }

  // Circle of Trust endpoints
  async getCircleOfTrust(): Promise<CircleOfTrustMember[]> {
    return this.request('/circle/members')
  }

  async getCircleOfTrustSettings(): Promise<CircleOfTrustSettings> {
    return this.request('/circle/settings')
  }

  async updateCircleOfTrustSettings(
    settings: Partial<CircleOfTrustSettings>
  ): Promise<CircleOfTrustSettings> {
    return this.request('/circle/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
  }

  async addToCircleOfTrust(member: {
    nickname: string
    contact_phone?: string
    contact_email?: string
  }): Promise<CircleOfTrustMember> {
    // `nickname` is the backend's field for the contact's name (renamed from
    // the old `contact_name`); sending the old key silently dropped the name.
    return this.request('/circle/members', {
      method: 'POST',
      body: JSON.stringify({
        nickname: member.nickname,
        contact_phone_number: member.contact_phone,
      }),
    })
  }

  async removeFromCircleOfTrust(memberId: string): Promise<void> {
    return this.request(`/circle/members/${memberId}`, {
      method: 'DELETE',
    })
  }

  // Subscription endpoints
  async getSubscriptionStatus(): Promise<SubscriptionStatus> {
    return this.request('/subscriptions')
  }

  /** One-time $0.99 day pass — Stripe checkout in the external browser. */
  async createDayPassCheckout(): Promise<{ checkout_url: string }> {
    return this.request('/subscriptions/day-pass', { method: 'POST' })
  }

  async createCheckoutSession(
    planType: string
  ): Promise<{ checkout_url: string }> {
    return this.request('/subscriptions/checkout', {
      method: 'POST',
      body: JSON.stringify({ plan_type: planType }),
    })
  }

  async createPortalSession(): Promise<{ portal_url: string }> {
    return this.request('/subscriptions/portal', {
      method: 'POST',
    })
  }

  /**
   * Update the current user's subscription renewal intent (native
   * cancel / reactivate). `cancelAtPeriodEnd=true` schedules cancellation at
   * the paid period end; `false` reactivates a pending cancel. Returns the
   * fresh subscription status. Change-plan / payment-method stay on the hosted
   * portal (createPortalSession).
   */
  async updateSubscription(
    cancelAtPeriodEnd: boolean
  ): Promise<SubscriptionStatus> {
    return this.request('/subscriptions', {
      method: 'PATCH',
      body: JSON.stringify({ cancel_at_period_end: cancelAtPeriodEnd }),
    })
  }

  async applyReferralCode(code: string): Promise<ReferralApplyResult> {
    return this.request('/referrals', {
      method: 'POST',
      body: JSON.stringify({ referral_code: code }),
    })
  }

  async getReferralInfo(): Promise<{
    referral_code: string
    can_refer: boolean
    referrals_used: number
    referrals_max: number
  }> {
    return this.request('/referrals')
  }

  async recordGiftRequest(targetPhone: string): Promise<void> {
    await this.request('/sponsorship-requests', {
      method: 'POST',
      body: JSON.stringify({ target_phone: targetPhone }),
    })
  }

  // Group plan endpoints
  async getGroupPlan(): Promise<GroupPlan | null> {
    return this.request('/groups')
  }

  async joinGroupPlan(inviteCode: string): Promise<GroupPlanMember> {
    return this.request(`/groups/${inviteCode}/members`, {
      method: 'POST',
    })
  }

  // Leaving deletes the caller's own membership on that plan.
  async leaveGroupPlan(planId: string): Promise<void> {
    return this.request(`/groups/${planId}/members/me`, {
      method: 'DELETE',
    })
  }

  async removeGroupMember(planId: string, memberId: string): Promise<void> {
    return this.request(`/groups/${planId}/members/${memberId}`, {
      method: 'DELETE',
    })
  }

  async regenerateGroupInvite(
    planId: string
  ): Promise<{ invite_code: string }> {
    return this.request(`/groups/${planId}/invite-code`, {
      method: 'POST',
    })
  }
}

export default ApiService.getInstance()
