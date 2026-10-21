import {
  LIVE_POLL_LEAD_MS,
  isInPollWindow,
  liveStatusChanged,
  pickSessionSource,
  sessionScreenMode,
  shouldContinuePolling,
} from './sessionMode'
import { isDataHeld } from './retention'
import type { Session } from '../types'

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    user_id: 'u1',
    session_type: 'checkin',
    expected_return_time: '2026-01-01T12:00:00Z',
    location_sharing_enabled: false,
    status: 'active',
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-01-01T10:00:00Z',
    ...overrides,
  }
}

describe('sessionScreenMode', () => {
  const cases: Array<[Session['status'], 'live' | 'ended']> = [
    ['active', 'live'],
    ['missed', 'live'],
    ['alerted', 'live'],
    ['completed', 'ended'],
    ['cancelled', 'ended'],
  ]

  it.each(cases)('%s -> %s', (status, mode) => {
    expect(sessionScreenMode(status)).toBe(mode)
  })
})

describe('pickSessionSource', () => {
  it('prefers the live store copy for this id over the fetched copy', () => {
    const fetched = makeSession({ status: 'active' })
    const active = makeSession({ status: 'alerted' })
    expect(pickSessionSource(fetched, active, 's1')).toBe(active)
  })

  it('an ENDED fetched copy beats a stale live store copy', () => {
    const fetched = makeSession({ status: 'completed' })
    const active = makeSession({ status: 'active' })
    expect(pickSessionSource(fetched, active, 's1')).toBe(fetched)
  })

  it('an ended store copy does not shadow the fetched copy', () => {
    const fetched = makeSession({ status: 'completed', purge_after: 'x' })
    const active = makeSession({ status: 'completed' })
    expect(pickSessionSource(fetched, active, 's1')).toBe(fetched)
  })

  it('never leaks a store session for a different id', () => {
    const fetched = makeSession({ id: 's1', status: 'missed' })
    const other = makeSession({ id: 's2', status: 'active' })
    expect(pickSessionSource(fetched, other, 's1')).toBe(fetched)
    expect(pickSessionSource(null, other, 's1')).toBeNull()
  })

  it('falls back to the matching store copy when the fetch failed', () => {
    const active = makeSession({ status: 'active' })
    expect(pickSessionSource(null, active, 's1')).toBe(active)
  })

  it('falls back to the fetched copy once the store session is gone', () => {
    const fetched = makeSession({ status: 'active' })
    expect(pickSessionSource(fetched, null, 's1')).toBe(fetched)
  })

  it('ignores a fetched copy for a different id (route param changed)', () => {
    const fetched = makeSession({ id: 's2' })
    expect(pickSessionSource(fetched, null, 's1')).toBeNull()
  })
})

describe('shouldContinuePolling', () => {
  it('keeps polling through the escalation ladder', () => {
    expect(shouldContinuePolling('active', false)).toBe(true)
    expect(shouldContinuePolling('missed', false)).toBe(true)
    expect(shouldContinuePolling('alerted', false)).toBe(true)
  })

  it('stops once alerted AND acknowledged', () => {
    expect(shouldContinuePolling('alerted', true)).toBe(false)
  })

  it('stops once the session ended', () => {
    expect(shouldContinuePolling('completed', false)).toBe(false)
    expect(shouldContinuePolling('cancelled', false)).toBe(false)
  })
})

describe('isInPollWindow', () => {
  const deadline = 1_000_000_000
  it('is closed before T-2min and open from T-2min on', () => {
    expect(isInPollWindow(deadline, deadline - LIVE_POLL_LEAD_MS - 1)).toBe(
      false
    )
    expect(isInPollWindow(deadline, deadline - LIVE_POLL_LEAD_MS)).toBe(true)
    expect(isInPollWindow(deadline, deadline + 60_000)).toBe(true)
  })

  it('never opens without a deadline', () => {
    expect(isInPollWindow(null, Date.now())).toBe(false)
  })
})

describe('liveStatusChanged', () => {
  it('is false when nothing the lock screen renders changed', () => {
    const a = makeSession({ status: 'missed', last_battery_level: 0.5 })
    const b = makeSession({ status: 'missed', last_battery_level: 0.4 })
    expect(liveStatusChanged(a, b)).toBe(false)
  })

  it('detects status, acknowledged and unreachable changes', () => {
    const base = makeSession({ status: 'missed' })
    expect(liveStatusChanged(base, makeSession({ status: 'alerted' }))).toBe(
      true
    )
    expect(
      liveStatusChanged(
        makeSession({ status: 'alerted' }),
        makeSession({ status: 'alerted', alert_acknowledged: true })
      )
    ).toBe(true)
    expect(
      liveStatusChanged(base, makeSession({ circle_unreachable: true }))
    ).toBe(true)
  })

  it('treats absent flags as false', () => {
    expect(
      liveStatusChanged(
        makeSession({ status: 'missed' }),
        makeSession({
          status: 'missed',
          alert_acknowledged: false,
          circle_unreachable: false,
        })
      )
    ).toBe(false)
  })
})

describe('purged detection (utils/retention.isDataHeld — the ended-mode purge axis)', () => {
  it('purged_at set means data is gone (purged)', () => {
    expect(isDataHeld({ purged_at: '2026-01-01T00:00:00Z' })).toBe(false)
  })

  it('purge_after in the future means data is still held (not purged)', () => {
    const future = new Date(Date.now() + 100_000).toISOString()
    expect(isDataHeld({ purge_after: future })).toBe(true)
  })

  it('purge_after in the past means data is gone (purged)', () => {
    const past = new Date(Date.now() - 100_000).toISOString()
    expect(isDataHeld({ purge_after: past })).toBe(false)
  })

  it('no purge_after at all means data is gone (legacy row)', () => {
    expect(isDataHeld({})).toBe(false)
  })
})
