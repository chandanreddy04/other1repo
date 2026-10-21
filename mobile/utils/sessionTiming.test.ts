import {
  getSessionDeadline,
  computeReminderRungs,
  isLocationStale,
  nextOccurrenceOfTime,
  REMINDER_LADDER_MINUTES,
} from './sessionTiming'
import { CHECKIN_CONFIG } from '../constants/config'

describe('isLocationStale', () => {
  const now = new Date('2026-07-19T12:00:00Z').getTime()
  const threshold = CHECKIN_CONFIG.LOCATION_STALE_THRESHOLD_MS

  it('fresh within the threshold — dot keeps pulsing', () => {
    expect(isLocationStale(new Date(now - threshold + 1000), now)).toBe(false)
  })

  it('stale strictly past the threshold — dot goes gray', () => {
    expect(isLocationStale(new Date(now - threshold - 1000), now)).toBe(true)
  })

  it('exactly at the threshold is still fresh (strict >)', () => {
    expect(isLocationStale(new Date(now - threshold), now)).toBe(false)
  })

  it('accepts ISO strings (the API wire format)', () => {
    expect(isLocationStale('2026-07-19T11:59:00Z', now)).toBe(false)
    expect(isLocationStale('2026-07-19T11:00:00Z', now)).toBe(true)
  })

  it('threshold is 15 minutes — 3 missed cycles of the 5-min capture cadence', () => {
    expect(threshold).toBe(15 * 60 * 1000)
    expect(threshold).toBe(3 * CHECKIN_CONFIG.LOCATION_UPDATE_INTERVAL)
  })
})

describe('getSessionDeadline', () => {
  it('prefers expected_arrival_time when present', () => {
    const d = getSessionDeadline({
      expected_arrival_time: '2026-07-09T10:00:00.000Z',
      expected_return_time: '2026-07-09T11:00:00.000Z',
      expected_end_time: '2026-07-09T12:00:00.000Z',
    })
    expect(d?.toISOString()).toBe('2026-07-09T10:00:00.000Z')
  })

  it('falls back to expected_return_time when arrival is absent', () => {
    const d = getSessionDeadline({
      expected_return_time: '2026-07-09T11:00:00.000Z',
      expected_end_time: '2026-07-09T12:00:00.000Z',
    })
    expect(d?.toISOString()).toBe('2026-07-09T11:00:00.000Z')
  })

  it('falls back to expected_end_time when the others are absent', () => {
    const d = getSessionDeadline({
      expected_end_time: '2026-07-09T12:00:00.000Z',
    })
    expect(d?.toISOString()).toBe('2026-07-09T12:00:00.000Z')
  })

  it('returns null when no timestamp is present', () => {
    expect(getSessionDeadline({})).toBeNull()
    expect(
      getSessionDeadline({ expected_return_time: null, expected_end_time: '' })
    ).toBeNull()
  })
})

describe('computeReminderRungs', () => {
  const now = new Date('2026-07-09T10:00:00.000Z')

  it('schedules the full ladder for a long session', () => {
    const deadline = new Date('2026-07-09T11:00:00.000Z') // 60 min out
    const rungs = computeReminderRungs(deadline, now)
    expect(rungs.map(r => r.minutesBefore)).toEqual([
      ...REMINDER_LADDER_MINUTES,
    ])
    expect(rungs.map(r => r.fireAt.toISOString())).toEqual([
      '2026-07-09T10:30:00.000Z', // T-30
      '2026-07-09T10:50:00.000Z', // T-10
      '2026-07-09T10:55:00.000Z', // T-5
      '2026-07-09T11:00:00.000Z', // T-0
    ])
  })

  it('drops past rungs for a short session but keeps the rest', () => {
    const deadline = new Date('2026-07-09T10:08:00.000Z') // 8 min out
    const rungs = computeReminderRungs(deadline, now)
    expect(rungs.map(r => r.minutesBefore)).toEqual([5, 0])
  })

  it('returns nothing when the deadline is already past', () => {
    const deadline = new Date('2026-07-09T09:30:00.000Z')
    expect(computeReminderRungs(deadline, now)).toEqual([])
  })

  it('excludes the exact-boundary rung (fire instant not strictly future)', () => {
    const deadline = new Date('2026-07-09T10:05:00.000Z') // T-5 lands on now
    const rungs = computeReminderRungs(deadline, now)
    expect(rungs.map(r => r.minutesBefore)).toEqual([0])
  })
})

describe('nextOccurrenceOfTime — alarm-app clock entry', () => {
  const now = new Date('2026-07-09T22:00:00') // 10 PM local

  it('picks today when the time is still ahead', () => {
    const d = nextOccurrenceOfTime(23, 30, now)
    expect(d.getDate()).toBe(now.getDate())
    expect(d.getHours()).toBe(23)
    expect(d.getMinutes()).toBe(30)
  })

  it('rolls to tomorrow when the time already passed (1 AM at 10 PM)', () => {
    const d = nextOccurrenceOfTime(1, 0, now)
    expect(d.getTime()).toBeGreaterThan(now.getTime())
    expect(d.getDate()).toBe(now.getDate() + 1)
    expect(d.getHours()).toBe(1)
  })

  it('the exact current minute counts as passed (rolls a day ahead)', () => {
    const d = nextOccurrenceOfTime(22, 0, now)
    expect(d.getDate()).toBe(now.getDate() + 1)
  })

  it('always lands within the 24h session cap', () => {
    for (const [h, m] of [[0, 0], [12, 30], [21, 59], [22, 1]]) {
      const d = nextOccurrenceOfTime(h, m, now)
      expect(d.getTime()).toBeGreaterThan(now.getTime())
      expect(d.getTime() - now.getTime()).toBeLessThanOrEqual(24 * 60 * 60 * 1000)
    }
  })

  it('rolls to tomorrow when the occurrence is inside the minimum lead', () => {
    // 22:20 picked at 22:00 with a 30-min floor → tomorrow 22:20, never a
    // 20-minute session.
    const d = nextOccurrenceOfTime(22, 20, now, 30)
    expect(d.getDate()).toBe(now.getDate() + 1)
    // Exactly at the floor boundary (22:30) also rolls (must be > lead).
    const boundary = nextOccurrenceOfTime(22, 30, now, 30)
    expect(boundary.getDate()).toBe(now.getDate() + 1)
    // Comfortably past the floor stays today.
    const ok = nextOccurrenceOfTime(22, 45, now, 30)
    expect(ok.getDate()).toBe(now.getDate())
  })

  it('zeroes seconds/millis so countdowns start clean', () => {
    const messy = new Date('2026-07-09T22:00:41.337')
    const d = nextOccurrenceOfTime(23, 0, messy)
    expect(d.getSeconds()).toBe(0)
    expect(d.getMilliseconds()).toBe(0)
  })
})
