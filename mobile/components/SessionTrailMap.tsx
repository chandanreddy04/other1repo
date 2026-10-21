/**
 * Shared session trail map — the ONE map treatment for a session's location
 * trail, rendered on the owner's session screen (live and ended modes).
 *
 * Presentational only: callers feed it fixes (usually from useLocationTrail).
 * The latest position is a pulsing blue dot while fresh; once the newest fix
 * is older than CHECKIN_CONFIG.LOCATION_STALE_THRESHOLD_MS it flips to a
 * static gray dot — the pulse is a liveness claim, so it must be provable
 * (owner decision 2026-07-19). MapLibre + keyless OSM-based OpenFreeMap
 * tiles: no Google SDK, no API key, identical iOS/Android rendering.
 *
 * Related: hooks/useLocationTrail.ts, utils/mapBounds.ts,
 *          utils/sessionTiming.ts (isLocationStale)
 */

import { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Animated, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import {
  Camera,
  GeoJSONSource,
  Layer,
  Map as MapLibreMap,
  Marker,
} from '@maplibre/maplibre-react-native'
import { COLORS, RADIUS, SHADOWS, SPACING, TYPOGRAPHY } from '../constants'
import type { TrailFix } from '../hooks/useLocationTrail'
import { fitBoundsToPoints } from '../utils/mapBounds'
import { formatDateTime, formatTimeAgo } from '../utils/dateFormatting'
import { isLocationStale } from '../utils/sessionTiming'

// OSM-based vector tiles from OpenFreeMap — free, keyless, no usage caps.
// Never point at OpenStreetMap's own raw tile servers (their usage policy
// disallows apps).
const MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'

// Re-evaluate staleness/caption twice a minute — cheap, and the dot grays
// out while the user is watching instead of on the next data refresh.
const STALENESS_TICK_MS = 30_000

interface SessionTrailMapProps {
  fixes: TrailFix[]
  loading?: boolean
  /**
   * False for CLOSED incidents/sessions (owner summary, resolved alert):
   * the latest fix is history, not a position claim — static gray dot, no
   * pulse, no staleness alarm, absolute "Last update" caption.
   */
  live?: boolean
  testID?: string
}

/**
 * Google-Maps-style position dot. Fresh: solid blue with a looping expanding
 * halo. Stale: static gray, no pulse.
 */
function PositionDot({ stale }: { stale: boolean }) {
  const pulse = useRef(new Animated.Value(0)).current

  useEffect(() => {
    if (stale) return
    const loop = Animated.loop(
      Animated.timing(pulse, {
        toValue: 1,
        duration: 1800,
        useNativeDriver: true,
      })
    )
    loop.start()
    return () => {
      loop.stop()
      pulse.setValue(0)
    }
  }, [stale, pulse])

  return (
    <View style={styles.dotWrap} pointerEvents="none">
      {!stale && (
        <Animated.View
          style={[
            styles.dotHalo,
            {
              opacity: pulse.interpolate({
                inputRange: [0, 1],
                outputRange: [0.45, 0],
              }),
              transform: [
                {
                  scale: pulse.interpolate({
                    inputRange: [0, 1],
                    outputRange: [1, 2.6],
                  }),
                },
              ],
            },
          ]}
        />
      )}
      <View style={[styles.dotCore, stale && styles.dotCoreStale]} />
    </View>
  )
}

export function SessionTrailMap({
  fixes,
  loading = false,
  live = true,
  testID,
}: SessionTrailMapProps) {
  // Ticks staleness + the "updated X ago" caption between data refreshes.
  // Closed sessions don't tick — nothing about them changes.
  const [nowTick, setNowTick] = useState(() => Date.now())
  useEffect(() => {
    if (!live || fixes.length === 0) return
    const id = setInterval(() => setNowTick(Date.now()), STALENESS_TICK_MS)
    return () => clearInterval(id)
  }, [live, fixes.length])

  if (fixes.length === 0) {
    return (
      <View style={styles.placeholder} testID={testID}>
        {loading ? (
          <ActivityIndicator size="small" color={COLORS.primary} />
        ) : (
          <>
            <Ionicons
              name="location-outline"
              size={22}
              color={COLORS.textLight}
            />
            <Text style={styles.placeholderText}>
              Waiting for your first location…
            </Text>
          </>
        )}
      </View>
    )
  }

  const latest = fixes[fixes.length - 1]
  // A closed session's dot is always the static gray one — the pulse and the
  // staleness alarm are both live-position claims.
  const stale = !live || isLocationStale(latest.recordedAt, nowTick)
  const bounds = fitBoundsToPoints(fixes)!
  const trailGeoJSON: GeoJSON.Feature = {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'LineString',
      coordinates: fixes.map(f => [f.longitude, f.latitude]),
    },
  }

  return (
    <View testID={testID}>
      <View style={styles.mapContainer}>
        <MapLibreMap
          style={styles.map}
          mapStyle={MAP_STYLE_URL}
          attributionPosition={{ bottom: 4, right: 4 }}
        >
          {/* Controlled bounds: the camera re-fits as the trail grows, so the
              dot never wanders off-screen between refreshes. */}
          <Camera
            bounds={bounds}
            padding={{ top: 32, bottom: 32, left: 32, right: 32 }}
            duration={600}
          />
          {fixes.length > 1 && (
            <GeoJSONSource id="session-trail" data={trailGeoJSON}>
              <Layer
                id="session-trail-line"
                type="line"
                paint={{
                  'line-color': COLORS.primary,
                  'line-width': 3,
                  'line-opacity': 0.85,
                }}
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              />
            </GeoJSONSource>
          )}
          {fixes.length > 1 && (
            <Marker lngLat={[fixes[0].longitude, fixes[0].latitude]}>
              <View style={styles.startDot} pointerEvents="none" />
            </Marker>
          )}
          <Marker lngLat={[latest.longitude, latest.latitude]}>
            <PositionDot stale={stale} />
          </Marker>
        </MapLibreMap>
      </View>
      {/* Freshness caption — quiet while live, prominent once the dot grays
          out so "why is it gray" answers itself. Closed sessions get the
          neutral absolute timestamp (no alarm — nothing is wrong). */}
      <Text
        style={[styles.updatedText, live && stale && styles.updatedTextStale]}
        testID={testID ? `${testID}-updated` : undefined}
      >
        {!live
          ? `Last update ${formatDateTime(latest.recordedAt)}`
          : stale
            ? `No location update since ${formatTimeAgo(latest.recordedAt, nowTick).replace(' ago', '')} ago`
            : `Updated ${formatTimeAgo(latest.recordedAt, nowTick)}`}
      </Text>
    </View>
  )
}

const styles = StyleSheet.create({
  mapContainer: {
    borderRadius: RADIUS.lg,
    overflow: 'hidden',
    ...SHADOWS.sm,
  },
  map: {
    height: 240,
    width: '100%',
  },
  placeholder: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    height: 72,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.lightGray,
  },
  placeholderText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  dotWrap: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotHalo: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: COLORS.accent.blue,
  },
  dotCore: {
    width: 15,
    height: 15,
    borderRadius: 8,
    backgroundColor: COLORS.accent.blue,
    borderWidth: 2.5,
    borderColor: COLORS.white,
    ...SHADOWS.sm,
  },
  dotCoreStale: {
    backgroundColor: COLORS.textLight,
  },
  startDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: COLORS.white,
    borderWidth: 2,
    borderColor: COLORS.textLight,
  },
  updatedText: {
    marginTop: SPACING.xs,
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    textAlign: 'right',
  },
  updatedTextStale: {
    color: COLORS.warning,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    textAlign: 'left',
  },
})
