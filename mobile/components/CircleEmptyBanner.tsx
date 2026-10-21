import React, { useEffect } from 'react'
import { Text, TouchableOpacity, StyleSheet, Platform } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import { useCircleStore } from '../store/useCircleStore'
import { COLORS, SPACING, TYPOGRAPHY } from '../constants'
import { leaveBreadcrumb } from '../services/errorReporting'

/**
 * Persistent banner shown at the top of every tab when the user's
 * Circle of Trust is empty — but tuned to the situation:
 *
 *   - Fresh signup (no memberships at all): no banner. The home tab's
 *     existing "Build your Circle of Trust" empty state handles the
 *     nudge; layering a red bar on top of it is alarming and noisy
 *     for someone who just made an account.
 *   - Mid-life empty (had members, lost them all — typically because
 *     a contact texted STOP): RED banner. This is a functional outage
 *     of SOS / sessions and the visual urgency should match.
 *
 * Tap routes to Contacts. The list endpoint returns ALL statuses
 * (active, pending, opted_out) so `circleOfTrust.length > 0` is a
 * truthful "had anyone, ever" check until the row is hard-removed via
 * the opted-out action sheet's "Remove from your list".
 */

/** Shared by the tab layout's safe-area wrapper so it only renders
 * its red background when the banner itself would render. Without this
 * the SafeAreaView paints red into the status-bar area even when the
 * banner is hidden. */
export function useShouldShowEmptyBanner(): boolean {
  const circleOfTrust = useCircleStore(s => s.circleOfTrust)
  // Suppress while loading — banner shouldn't flash on cold start.
  if (!circleOfTrust) return false
  // Fresh signup: no membership history at all → home tab handles it.
  if (circleOfTrust.length === 0) return false
  // Has an active member → nothing to warn about.
  return !circleOfTrust.some(m => m.status === 'active')
}

export const CircleEmptyBanner: React.FC = () => {
  const router = useRouter()
  const visible = useShouldShowEmptyBanner()
  const insets = useSafeAreaInsets()

  // Drop a breadcrumb on first render of the banner so SafeArea layout
  // issues (e.g. banner clipped behind the Android status bar) surface
  // next to whatever error report the user generates. Cheap, opt-in
  // free instrumentation — only fires when the banner actually shows.
  useEffect(() => {
    if (!visible) return
    leaveBreadcrumb('CircleEmptyBanner rendered', {
      platform: Platform.OS,
      platformVersion: String(Platform.Version),
      insetsTop: insets.top,
    })
  }, [visible, insets.top])

  if (!visible) return null
  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => router.push('/(tabs)/circle')}
      activeOpacity={0.85}
      accessibilityRole="button"
      accessibilityLabel="Your Circle of Trust is empty. Tap to add a Circle member."
    >
      <Text style={styles.text}>
        Your Circle of Trust is empty. Add someone now.
      </Text>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: COLORS.danger,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
  },
  text: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: '600',
    textAlign: 'center',
  },
})
