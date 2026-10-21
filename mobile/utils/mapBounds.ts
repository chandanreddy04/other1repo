/**
 * Pure camera-fitting math for trail maps.
 *
 * Computes the bounding box a map camera should frame to show a session's
 * location trail. Kept free of any map library so it can be unit-tested
 * (SessionTrailMap on the owner's session screen).
 *
 * Related: components/SessionTrailMap.tsx, hooks/useLocationTrail.ts
 */

export interface TrailPoint {
  latitude: number
  longitude: number
}

/**
 * MapLibre's flat LngLatBounds shape: [west, south, east, north]
 * (south-west then north-east corner, GeoJSON RFC order).
 */
export type TrailBounds = [
  west: number,
  south: number,
  east: number,
  north: number,
]

/**
 * Minimum span (degrees, ~1.1 km of latitude) for either axis. A single fix —
 * or a user standing still — must not zoom the camera to a postage stamp.
 */
export const MIN_BOUNDS_SPAN_DEG = 0.01

/**
 * Fit a bounding box around the given points, expanding degenerate spans to
 * MIN_BOUNDS_SPAN_DEG per axis (centered). Returns null with no points — the
 * caller renders its "waiting for location" placeholder instead of a map.
 *
 * View-edge padding is deliberately NOT applied here: the map camera pads in
 * screen pixels (a rendering concern), while this is pure geography.
 */
export function fitBoundsToPoints(points: TrailPoint[]): TrailBounds | null {
  if (points.length === 0) return null

  let minLat = Infinity
  let maxLat = -Infinity
  let minLng = Infinity
  let maxLng = -Infinity
  for (const p of points) {
    if (p.latitude < minLat) minLat = p.latitude
    if (p.latitude > maxLat) maxLat = p.latitude
    if (p.longitude < minLng) minLng = p.longitude
    if (p.longitude > maxLng) maxLng = p.longitude
  }

  const expand = (min: number, max: number): [number, number] => {
    const span = max - min
    if (span >= MIN_BOUNDS_SPAN_DEG) return [min, max]
    const pad = (MIN_BOUNDS_SPAN_DEG - span) / 2
    return [min - pad, max + pad]
  }

  const [south, north] = expand(minLat, maxLat)
  const [west, east] = expand(minLng, maxLng)

  return [west, south, east, north]
}
