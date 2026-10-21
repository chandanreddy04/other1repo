/**
 * Live location trail for a session — fetches the server-stored history
 * (GET /sessions/{id}/locations) when the screen gains focus and
 * refreshes on an interval while focused, so the owner's session screen
 * (live mode) renders a trail that keeps moving during an incident instead
 * of freezing at first render.
 *
 * Server truth only: these are the points the circle actually sees, never the
 * device's own GPS. Related: utils/mapBounds.ts, components/SessionTrailMap.tsx
 */

import { useCallback, useState } from 'react'
import { useFocusEffect } from 'expo-router'
import api from '../services/api'

export interface TrailFix {
  latitude: number
  longitude: number
  recordedAt: string
}

interface RawLocationPoint {
  latitude: string
  longitude: string
  recorded_at: string
}

export const TRAIL_REFRESH_INTERVAL_MS = 60_000

/**
 * Parse API rows (string coords) into numeric fixes, dropping malformed rows
 * and sorting oldest-first so callers can rely on [0] = start, [last] = latest.
 */
export function toTrailFixes(history: RawLocationPoint[]): TrailFix[] {
  return history
    .map(p => ({
      latitude: Number.parseFloat(p.latitude),
      longitude: Number.parseFloat(p.longitude),
      recordedAt: p.recorded_at,
    }))
    .filter(f => Number.isFinite(f.latitude) && Number.isFinite(f.longitude))
    .sort(
      (a, b) =>
        new Date(a.recordedAt).getTime() - new Date(b.recordedAt).getTime()
    )
}

export function useLocationTrail(
  sessionId: string | null | undefined,
  options: {
    /**
     * Keep the trail refreshing every 60s while focused (default). Pass
     * false for CLOSED incidents/sessions — the trail is history, polling
     * it would only imply liveness the server no longer claims.
     */
    refresh?: boolean
  } = {}
): {
  fixes: TrailFix[]
  latest: TrailFix | null
  loading: boolean
} {
  const { refresh = true } = options
  const [fixes, setFixes] = useState<TrailFix[]>([])
  // Loading only until the FIRST result for a session — interval refreshes
  // swap data in place without flashing a spinner over a rendered map.
  const [loading, setLoading] = useState(!!sessionId)

  useFocusEffect(
    useCallback(() => {
      if (!sessionId) {
        setFixes([])
        setLoading(false)
        return
      }
      let cancelled = false
      setLoading(true)

      const load = async () => {
        try {
          const history = await api.getLocationHistory(sessionId)
          if (!cancelled) setFixes(toTrailFixes(history))
        } catch {
          // benign: Transient fetch failure — keep the last known trail.
        } finally {
          if (!cancelled) setLoading(false)
        }
      }

      void load()
      if (!refresh) return
      const interval = setInterval(() => void load(), TRAIL_REFRESH_INTERVAL_MS)
      return () => {
        cancelled = true
        clearInterval(interval)
      }
    }, [sessionId, refresh])
  )

  return {
    fixes,
    latest: fixes.length > 0 ? fixes[fixes.length - 1] : null,
    loading,
  }
}
