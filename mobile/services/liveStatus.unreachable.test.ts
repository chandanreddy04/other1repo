/**
 * circle_unreachable → LIVE_STATUS_COPY.unreachable: a MISSED session whose
 * circle-alert deliveries are all terminally undeliverable must say so,
 * instead of "Notifying your circle…" forever (false reassurance).
 */
import { Session } from '../types'
import {
  LIVE_STATUS_COPY,
  homePillStatusTitle,
  liveStatusContent,
} from './liveStatus'

jest.mock('./nativeModules', () => ({
  loadNativeModule: () => null,
}))

function makeSession(overrides: Record<string, unknown> = {}): Session {
  return {
    id: 's1',
    status: 'missed',
    session_type: 'checkin',
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    expected_return_time: new Date(Date.now() - 600_000).toISOString(),
    ...overrides,
  } as unknown as Session
}

describe('liveStatusContent — circle_unreachable', () => {
  it('shows the unreachable copy for a missed session the server flagged', () => {
    const content = liveStatusContent(
      makeSession({ circle_unreachable: true })
    )
    expect(content.title).toBe(LIVE_STATUS_COPY.unreachable.title)
    expect(content.subtitle).toBe(LIVE_STATUS_COPY.unreachable.subtitle)
    expect(content.overdue).toBe(true)
  })

  it('keeps the normal "notifying" copy while the flag is absent/false', () => {
    expect(liveStatusContent(makeSession()).title).toBe(
      LIVE_STATUS_COPY.missed.title
    )
    expect(
      liveStatusContent(makeSession({ circle_unreachable: false })).title
    ).toBe(LIVE_STATUS_COPY.missed.title)
  })

  it('never applies the unreachable copy to an alerted session', () => {
    // alerted means at least one contact WAS reached — the backend only
    // computes the flag for MISSED, and the client must not invent it.
    const content = liveStatusContent(
      makeSession({ status: 'alerted', circle_unreachable: true })
    )
    expect(content.title).toBe(LIVE_STATUS_COPY.alerted.title)
  })
})

describe('homePillStatusTitle — compact Home pill label', () => {
  it('relabels missed/alerted from the shared table', () => {
    expect(homePillStatusTitle(makeSession())).toBe(
      LIVE_STATUS_COPY.missed.title
    )
    expect(
      homePillStatusTitle(makeSession({ circle_unreachable: true }))
    ).toBe(LIVE_STATUS_COPY.unreachable.title)
    expect(homePillStatusTitle(makeSession({ status: 'alerted' }))).toBe(
      LIVE_STATUS_COPY.alerted.title
    )
  })

  it('returns null for active sessions (clock label passes through)', () => {
    expect(homePillStatusTitle(makeSession({ status: 'active' }))).toBeNull()
  })

  it('never shows acknowledged on the pill — that state belongs to the session screen', () => {
    expect(
      homePillStatusTitle(
        makeSession({ status: 'alerted', alert_acknowledged: true })
      )
    ).toBe(LIVE_STATUS_COPY.alerted.title)
  })
})
