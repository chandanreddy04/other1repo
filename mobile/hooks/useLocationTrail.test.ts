jest.mock('expo-router', () => ({ useFocusEffect: jest.fn() }))
jest.mock('../services/api', () => ({ getLocationHistory: jest.fn() }))

import { toTrailFixes } from './useLocationTrail'

describe('toTrailFixes', () => {
  it('parses string coordinates into numbers', () => {
    expect(
      toTrailFixes([
        { latitude: '37.775', longitude: '-122.419', recorded_at: '2026-07-19T01:00:00Z' },
      ])
    ).toEqual([
      { latitude: 37.775, longitude: -122.419, recordedAt: '2026-07-19T01:00:00Z' },
    ])
  })

  it('sorts oldest-first so [0] is the start and [last] the latest fix', () => {
    const fixes = toTrailFixes([
      { latitude: '2', longitude: '2', recorded_at: '2026-07-19T02:00:00Z' },
      { latitude: '1', longitude: '1', recorded_at: '2026-07-19T01:00:00Z' },
      { latitude: '3', longitude: '3', recorded_at: '2026-07-19T03:00:00Z' },
    ])
    expect(fixes.map(f => f.latitude)).toEqual([1, 2, 3])
  })

  it('drops malformed rows instead of feeding NaN to the map', () => {
    const fixes = toTrailFixes([
      { latitude: 'not-a-number', longitude: '-122.4', recorded_at: '2026-07-19T01:00:00Z' },
      { latitude: '37.8', longitude: '', recorded_at: '2026-07-19T02:00:00Z' },
      { latitude: '37.7', longitude: '-122.5', recorded_at: '2026-07-19T03:00:00Z' },
    ])
    expect(fixes).toHaveLength(1)
    expect(fixes[0].latitude).toBe(37.7)
  })

  it('returns empty for an empty history', () => {
    expect(toTrailFixes([])).toEqual([])
  })
})
