/**
 * Battery display helpers.
 *
 * Used by the owner's session screen (live and ended modes).
 */

import type { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../constants'

/**
 * True only when the device has actually reported a battery level (0..1).
 *
 * The API field `last_battery_level` is nullable (`float | None` → JSON `null`)
 * and stays null until the first location/battery update lands — so at session
 * start there is no reading yet. Guarding the UI with `!== undefined` is a trap:
 * `null !== undefined` is `true`, so a null level slips through and
 * `Math.round(null * 100)` renders a fake **"0%"** (the session-start bug). Use
 * this guard so the battery row hides until a real reading exists.
 *
 * A genuine `0` (a near-dead battery) IS a valid reading and passes — for a
 * safety app that's exactly when the level matters most.
 */
export function hasBatteryReading(level?: number | null): level is number {
  return typeof level === 'number'
}

/** Ionicons glyph for a battery level/state (charging wins over level). */
export function getBatteryIcon(
  level?: number | null,
  state?: string
): keyof typeof Ionicons.glyphMap {
  if (state === 'charging') return 'battery-charging'
  if (!hasBatteryReading(level)) return 'battery-half'
  if (level > 0.5) return 'battery-full'
  if (level > 0.1) return 'battery-half'
  return 'battery-dead'
}

/** Green above 50%, amber above 10%, red at/below — gray with no reading. */
export function getBatteryColor(level?: number | null): string {
  if (!hasBatteryReading(level)) return COLORS.textLight
  if (level > 0.5) return COLORS.accent.green
  if (level > 0.1) return COLORS.warning
  return COLORS.danger
}
