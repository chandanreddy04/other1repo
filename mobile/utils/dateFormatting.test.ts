import {
  formatCountdown,
  formatTimeAgo,
  roundToNearest30Minutes,
} from './dateFormatting'

describe('formatTimeAgo', () => {
  const now = new Date('2026-07-19T12:00:00Z').getTime()
  const ago = (ms: number) => new Date(now - ms)

  it('under a minute is "just now"', () => {
    expect(formatTimeAgo(ago(30_000), now)).toBe('just now')
  })

  it('minutes under an hour', () => {
    expect(formatTimeAgo(ago(12 * 60_000), now)).toBe('12m ago')
  })

  it('hours with minute remainder under a day', () => {
    expect(formatTimeAgo(ago((60 + 5) * 60_000), now)).toBe('1h 5m ago')
  })

  it('days beyond 24h', () => {
    expect(formatTimeAgo(ago(49 * 60 * 60_000), now)).toBe('2d ago')
  })

  it('accepts ISO strings (the API wire format)', () => {
    expect(formatTimeAgo('2026-07-19T11:48:00Z', now)).toBe('12m ago')
  })
})

describe('formatCountdown', () => {
  it('returns "Overdue" for a passed or zero deadline', () => {
    expect(formatCountdown(0)).toBe('Overdue')
    expect(formatCountdown(-1000)).toBe('Overdue')
    expect(formatCountdown(-60 * 60 * 1000)).toBe('Overdue')
  })

  it('shows hours and minutes when more than an hour remains', () => {
    expect(formatCountdown(2 * 60 * 60 * 1000 + 15 * 60 * 1000)).toBe('2h 15m left')
    expect(formatCountdown(60 * 60 * 1000)).toBe('1h 0m left')
  })

  it('shows whole minutes between 5 minutes and an hour', () => {
    expect(formatCountdown(30 * 60 * 1000)).toBe('30m left')
    expect(formatCountdown(5 * 60 * 1000)).toBe('5m left')
  })

  it('ticks down to the second inside the final 5 minutes', () => {
    expect(formatCountdown(4 * 60 * 1000 + 59 * 1000)).toBe('4:59 left')
    expect(formatCountdown(90 * 1000)).toBe('1:30 left')
    expect(formatCountdown(5 * 1000)).toBe('0:05 left')
  })
})

describe('roundToNearest30Minutes', () => {
  const at = (h: number, m: number, s = 30) => new Date(2026, 0, 1, h, m, s, 500)

  it('rounds down below the :15 / :45 midpoint', () => {
    expect(roundToNearest30Minutes(at(17, 12)).getMinutes()).toBe(0)
    expect(roundToNearest30Minutes(at(17, 44)).getMinutes()).toBe(30)
  })

  it('rounds up at/above the midpoint (ties go up)', () => {
    expect(roundToNearest30Minutes(at(17, 15)).getMinutes()).toBe(30)
    expect(roundToNearest30Minutes(at(17, 47)).getMinutes()).toBe(0)
  })

  it('carries into the next hour when rounding up past :59', () => {
    const r = roundToNearest30Minutes(at(17, 47))
    expect(r.getHours()).toBe(18)
    expect(r.getMinutes()).toBe(0)
  })

  it('zeroes seconds and milliseconds', () => {
    const r = roundToNearest30Minutes(at(17, 30, 45))
    expect(r.getSeconds()).toBe(0)
    expect(r.getMilliseconds()).toBe(0)
  })

  it('does not mutate the input', () => {
    const input = at(17, 12)
    roundToNearest30Minutes(input)
    expect(input.getMinutes()).toBe(12)
  })
})
