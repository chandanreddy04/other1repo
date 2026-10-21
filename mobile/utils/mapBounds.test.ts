import {
  fitBoundsToPoints,
  MIN_BOUNDS_SPAN_DEG,
  TrailPoint,
} from './mapBounds'

const pt = (latitude: number, longitude: number): TrailPoint => ({
  latitude,
  longitude,
})

describe('fitBoundsToPoints', () => {
  it('returns null for no points — caller shows the waiting placeholder', () => {
    expect(fitBoundsToPoints([])).toBeNull()
  })

  it('expands a single point to the minimum span, centered on it', () => {
    const [west, south, east, north] = fitBoundsToPoints([
      pt(37.775, -122.419),
    ])!
    expect(north - south).toBeCloseTo(MIN_BOUNDS_SPAN_DEG, 10)
    expect(east - west).toBeCloseTo(MIN_BOUNDS_SPAN_DEG, 10)
    expect((north + south) / 2).toBeCloseTo(37.775, 10)
    expect((east + west) / 2).toBeCloseTo(-122.419, 10)
  })

  it('frames the min/max of a spread trail exactly (no geographic padding)', () => {
    const bounds = fitBoundsToPoints([
      pt(37.7, -122.5),
      pt(37.8, -122.4),
      pt(37.75, -122.45),
    ])!
    expect(bounds).toEqual([-122.5, 37.7, -122.4, 37.8])
  })

  it('expands only the degenerate axis — a straight north-south walk keeps its latitude span', () => {
    const [west, south, east, north] = fitBoundsToPoints([
      pt(37.7, -122.45),
      pt(37.8, -122.45),
    ])!
    // Latitude span was already wide enough — untouched.
    expect(south).toBeCloseTo(37.7, 10)
    expect(north).toBeCloseTo(37.8, 10)
    // Longitude was a zero-width line — expanded to the minimum, centered.
    expect(east - west).toBeCloseTo(MIN_BOUNDS_SPAN_DEG, 10)
    expect((east + west) / 2).toBeCloseTo(-122.45, 10)
  })

  it('a user standing still (jittering fixes) never zooms below the minimum span', () => {
    const [west, south, east, north] = fitBoundsToPoints([
      pt(37.7751, -122.4191),
      pt(37.7752, -122.419),
      pt(37.775, -122.4192),
    ])!
    expect(north - south).toBeGreaterThanOrEqual(MIN_BOUNDS_SPAN_DEG - 1e-12)
    expect(east - west).toBeGreaterThanOrEqual(MIN_BOUNDS_SPAN_DEG - 1e-12)
  })

  it('corners come back in MapLibre flat [west, south, east, north] order', () => {
    expect(fitBoundsToPoints([pt(10, 20), pt(11, 21)])).toEqual([20, 10, 21, 11])
  })
})
