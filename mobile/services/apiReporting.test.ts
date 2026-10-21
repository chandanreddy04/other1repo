import {
  NetworkError,
  REPORT_WINDOW_MS,
  ReportThrottle,
  failureKey,
  isNetworkFailure,
  isRetryableApiError,
  templatePath,
  withTimeout,
} from './apiReporting'

describe('templatePath', () => {
  it('replaces UUIDs and numeric ids and drops the query string', () => {
    expect(
      templatePath('/sessions/3f2504e0-4f89-41d3-9a0c-0305e82c3301/photos?x=1')
    ).toBe('/sessions/{id}/photos')
    expect(templatePath('/alerts?skip=0&limit=20')).toBe('/alerts')
    expect(templatePath('/things/42')).toBe('/things/{id}')
  })

  it('never lets an invite, share or referral code through', () => {
    expect(templatePath('/groups/K7PQ2M9X/members')).toBe(
      '/groups/{id}/members'
    )
    expect(templatePath('/referrals/ABCDEFGH')).toBe('/referrals/{id}')
    expect(templatePath('/c/x9y8z7w6')).toBe('/c/{id}')
    // Route words are untouched.
    expect(templatePath('/sessions/outfit-photos')).toBe(
      '/sessions/outfit-photos'
    )
    expect(
      templatePath('/groups/3f2504e0-4f89-41d3-9a0c-0305e82c3301/invite-code')
    ).toBe('/groups/{id}/invite-code')
  })

  it('redacts a digit-less group invite code (token_urlsafe(16), 22 chars)', () => {
    // No digit, so only the "groups" code-bearing rule can catch it.
    expect(templatePath('/groups/AbCdEfGhIjKlMnOpQr_-Xy/members')).toBe(
      '/groups/{id}/members'
    )
  })

  it('templates the plan-id group member routes, keeping the "me" word', () => {
    const plan = '3f2504e0-4f89-41d3-9a0c-0305e82c3301'
    const member = '9b2d6c1a-7e4f-4a3b-8c5d-1e2f3a4b5c6d'
    expect(templatePath(`/groups/${plan}/members/me`)).toBe(
      '/groups/{id}/members/me'
    )
    expect(templatePath(`/groups/${plan}/members/${member}`)).toBe(
      '/groups/{id}/members/{id}'
    )
  })
})

describe('NetworkError', () => {
  it('keeps the underlying message so "Network" retry checks still match', () => {
    const err = new NetworkError(
      'POST',
      '/sessions',
      new TypeError('Network request failed')
    )
    expect(err.message).toBe('Network request failed')
    expect(err.isNetworkError).toBe(true)
    expect(err.method).toBe('POST')
    expect(err.name).toBe('NetworkError')
    expect(new NetworkError('GET', '/x', 'weird').message).toBe(
      'Network request failed'
    )
  })
})

describe('failureKey', () => {
  it('groups by kind, method, templated path and status', () => {
    expect(failureKey('network', 'POST', '/auth/request-otp')).toBe(
      'network:POST /auth/request-otp'
    )
    expect(
      failureKey(
        'server',
        'GET',
        '/sessions/3f2504e0-4f89-41d3-9a0c-0305e82c3301',
        502
      )
    ).toBe('server:GET /sessions/{id} 502')
  })
})

describe('isRetryableApiError', () => {
  it('retries network failures, 5xx and gateway pages, never a 4xx refusal', () => {
    expect(
      isRetryableApiError(
        new NetworkError('POST', '/x', new TypeError('Network request failed'))
      )
    ).toBe(true)
    // An ALB 502 with an HTML body: no JSON, message is the fallback text.
    expect(
      isRetryableApiError(
        Object.assign(new Error('Unexpected response'), { statusCode: 502 })
      )
    ).toBe(true)
    expect(
      isRetryableApiError(Object.assign(new Error('x'), { statusCode: 503 }))
    ).toBe(true)
    expect(
      isRetryableApiError(Object.assign(new Error('x'), { statusCode: 429 }))
    ).toBe(true)
    expect(
      isRetryableApiError(
        Object.assign(new Error('No active circle'), { statusCode: 400 })
      )
    ).toBe(false)
    expect(
      isRetryableApiError(Object.assign(new Error('x'), { statusCode: 402 }))
    ).toBe(false)
    // Legacy shapes without a status still match on the message.
    expect(isRetryableApiError(new TypeError('Network request failed'))).toBe(
      true
    )
    expect(isRetryableApiError(new Error('Failed to fetch'))).toBe(true)
    expect(isRetryableApiError(new Error('something else'))).toBe(false)
    expect(isRetryableApiError(null)).toBe(false)
  })
})

describe('isNetworkFailure (queue-and-clear predicate)', () => {
  it('is true only when our server never answered', () => {
    expect(
      isNetworkFailure(
        new NetworkError('PUT', '/x', new TypeError('Network request failed'))
      )
    ).toBe(true)
    // ALB page during a deploy: 502 + non-JSON body.
    expect(
      isNetworkFailure(
        Object.assign(new Error('Unexpected response'), {
          statusCode: 502,
          isGatewayError: true,
        })
      )
    ).toBe(true)
    // A server that answered — even with 500 or 429 — is a refusal, not offline.
    expect(
      isNetworkFailure(
        Object.assign(new Error('Internal server error'), { statusCode: 500 })
      )
    ).toBe(false)
    expect(
      isNetworkFailure(
        Object.assign(new Error('Too many requests'), { statusCode: 429 })
      )
    ).toBe(false)
    expect(
      isNetworkFailure(Object.assign(new Error('x'), { statusCode: 400 }))
    ).toBe(false)
    // Legacy shapes without a status.
    expect(isNetworkFailure(new TypeError('Network request failed'))).toBe(true)
    expect(isNetworkFailure(new Error('nope'))).toBe(false)
  })
})

describe('withTimeout', () => {
  it('resolves the value when in time and the fallback when late or rejected', async () => {
    await expect(withTimeout(Promise.resolve('v'), 50, 'fb')).resolves.toBe('v')
    await expect(withTimeout(new Promise(() => {}), 10, 'fb')).resolves.toBe(
      'fb'
    )
    await expect(
      withTimeout(Promise.reject(new Error('x')), 50, 'fb')
    ).resolves.toBe('fb')
  })
})

describe('ReportThrottle', () => {
  it('reports once per key per window, then again after the window', () => {
    const t = new ReportThrottle()
    expect(t.shouldReport('k', 0)).toBe(true)
    expect(t.shouldReport('k', 1000)).toBe(false)
    expect(t.shouldReport('other', 1000)).toBe(true)
    expect(t.shouldReport('k', REPORT_WINDOW_MS - 1)).toBe(false)
    expect(t.shouldReport('k', REPORT_WINDOW_MS)).toBe(true)
  })

  it('reset clears the memory', () => {
    const t = new ReportThrottle()
    t.shouldReport('k', 0)
    t.reset()
    expect(t.shouldReport('k', 1)).toBe(true)
  })
})
