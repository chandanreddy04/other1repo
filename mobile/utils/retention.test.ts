import {
  canReduceRetention,
  formatDaysHours,
  getDisplayedDeletionDate,
  getOriginalDeletionDate,
  getRetentionFloor,
  getSessionEnd,
  isDataHeld,
} from './retention'
import { CHECKIN_CONFIG } from '../constants'

const DAY_MS = 24 * 60 * 60 * 1000
const NOW = new Date('2026-07-19T12:00:00Z').getTime()
const iso = (offsetDays: number) => new Date(NOW + offsetDays * DAY_MS).toISOString()

describe('getSessionEnd', () => {
  it('prefers the owner mark-safe time', () => {
    expect(
      getSessionEnd({ actual_return_time: iso(-1), cancelled_at: iso(-2) })
    ).toEqual(new Date(iso(-1)))
  })

  it('falls back to the admin cancel time', () => {
    expect(getSessionEnd({ cancelled_at: iso(-2) })).toEqual(new Date(iso(-2)))
  })

  it('null for legacy rows missing both anchors', () => {
    expect(getSessionEnd({})).toBeNull()
  })
})

describe('getRetentionFloor', () => {
  it('is the original deletion date while still in the future', () => {
    // Ended 2 days ago → original = end + 7d = now + 5d.
    const session = { actual_return_time: iso(-2) }
    expect(getRetentionFloor(session, NOW)).toEqual(
      new Date(NOW + 5 * DAY_MS)
    )
  })

  it('rises to now once the original date has passed', () => {
    // Ended 20 days ago → original long past → floor = now.
    const session = { actual_return_time: iso(-20) }
    expect(getRetentionFloor(session, NOW)).toEqual(new Date(NOW))
  })

  it('null without an end anchor — extend-only', () => {
    expect(getRetentionFloor({}, NOW)).toBeNull()
  })
})

describe('canReduceRetention', () => {
  it('true when the schedule sits above the floor (an extension to walk back)', () => {
    const session = {
      actual_return_time: iso(-2),
      purge_after: iso(12), // original (+5d) + one extension
    }
    expect(canReduceRetention(session, NOW)).toBe(true)
  })

  it('false at the original deletion date — the evidence window holds', () => {
    const session = { actual_return_time: iso(-2), purge_after: iso(5) }
    expect(canReduceRetention(session, NOW)).toBe(false)
  })

  it('false without an anchor (legacy) or without a schedule', () => {
    expect(canReduceRetention({ purge_after: iso(5) }, NOW)).toBe(false)
    expect(canReduceRetention({ actual_return_time: iso(-2) }, NOW)).toBe(false)
  })
})

describe('isDataHeld', () => {
  it('held while the purge date is ahead and nothing was purged', () => {
    expect(isDataHeld({ purge_after: iso(3) }, NOW)).toBe(true)
  })

  it('not held once purged_at is stamped — even with a future schedule (admin early purge)', () => {
    expect(
      isDataHeld({ purge_after: iso(3), purged_at: iso(-1) }, NOW)
    ).toBe(false)
  })

  it('not held past the schedule or with no schedule (legacy purgeable)', () => {
    expect(isDataHeld({ purge_after: iso(-1) }, NOW)).toBe(false)
    expect(isDataHeld({}, NOW)).toBe(false)
  })
})

describe('getDisplayedDeletionDate', () => {
  it('the actual purge stamp wins', () => {
    expect(
      getDisplayedDeletionDate({ purged_at: iso(-1), actual_return_time: iso(-20) })
    ).toEqual(new Date(iso(-1)))
  })

  it('falls back to session end + retention for pre-column purges', () => {
    expect(
      getDisplayedDeletionDate({ actual_return_time: iso(-20) })
    ).toEqual(
      new Date(NOW + (CHECKIN_CONFIG.SESSION_DATA_RETENTION_DAYS - 20) * DAY_MS)
    )
  })

  it('last resort: the last known schedule', () => {
    expect(getDisplayedDeletionDate({ purge_after: iso(-3) })).toEqual(
      new Date(iso(-3))
    )
  })
})

describe('formatDaysHours', () => {
  it('days + hours', () => {
    expect(formatDaysHours(6 * DAY_MS + 23 * 60 * 60 * 1000)).toBe('6d 23h')
  })

  it('hours only under a day', () => {
    expect(formatDaysHours(5 * 60 * 60 * 1000)).toBe('5h')
  })

  it('sub-hour and clamped-zero cases', () => {
    expect(formatDaysHours(30 * 60 * 1000)).toBe('<1h')
    expect(formatDaysHours(-5000)).toBe('0h')
  })
})
