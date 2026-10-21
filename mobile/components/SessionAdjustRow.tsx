/**
 * The ±30m session-time adjusters — one pill row shared by the Home card and
 * the session detail screen's live mode so the affordance can't drift
 * between the two surfaces (same 30-minute step, same min-lead gating, same
 * look). Also reused, with a 7-day step, for the ended mode's retention
 * adjust.
 *
 * Gating stays with the CALLER (it owns the clock math): pass canReduce from
 * the MIN_SESSION_LEAD_MINUTES check, and simply don't render this row once
 * the session escalates (the server rejects extends after MISSED).
 *
 * Related: app/(tabs)/index.tsx, app/sessions/[id].tsx,
 *          constants/config.ts (MIN_SESSION_LEAD_MINUTES)
 */

import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { COLORS, RADIUS, SPACING, TYPOGRAPHY } from '../constants'

interface SessionAdjustRowProps {
  /** Called with ±step in the caller's unit (minutes for the session clock,
   *  days for the retention date). */
  onAdjust: (amount: number) => void
  canReduce: boolean
  disabled?: boolean
  /** Grace-window escape hatch mode: only extend makes sense once overdue. */
  hideReduce?: boolean
  /** Step size + unit label: 30/"m" (session deadline, default) or 7/"d"
   *  (data-retention date on the session summary). */
  step?: number
  unit?: string
  testID?: string
}

export function SessionAdjustRow({
  onAdjust,
  canReduce,
  disabled = false,
  hideReduce = false,
  step = 30,
  unit = 'm',
  testID,
}: SessionAdjustRowProps) {
  return (
    <View style={styles.row} testID={testID}>
      {!hideReduce && (
        <TouchableOpacity
          style={[
            styles.button,
            (disabled || !canReduce) && styles.buttonDisabled,
          ]}
          onPress={() => onAdjust(-step)}
          disabled={disabled || !canReduce}
        >
          <Text style={styles.buttonText}>{`-${step}${unit}`}</Text>
        </TouchableOpacity>
      )}
      <TouchableOpacity
        style={[styles.button, disabled && styles.buttonDisabled]}
        onPress={() => onAdjust(step)}
        disabled={disabled}
      >
        <Text style={styles.buttonText}>{`+${step}${unit}`}</Text>
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: SPACING.sm,
  },
  button: {
    borderWidth: 1,
    borderColor: COLORS.primary,
    borderRadius: RADIUS.full,
    paddingVertical: 6,
    paddingHorizontal: SPACING.md,
  },
  buttonDisabled: {
    opacity: 0.4,
  },
  buttonText: {
    color: COLORS.primary,
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
  },
})
