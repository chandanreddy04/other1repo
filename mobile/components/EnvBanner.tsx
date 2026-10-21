import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { COLORS } from '../constants'
import { APP_ENV } from '../constants/config'
import { sendSmokeTest } from '../services/errorReporting'
import toast from '../utils/toast'

/**
 * Persistent top banner shown on every screen in non-production builds, so it's
 * always obvious (including in screenshots) that this isn't the real app.
 *
 * Rendered as an overlay (position: absolute) that only its own "test error
 * reporting"
 * link can receive taps (`box-none`), so it never shifts screen layout or
 * intercepts taps meant for the screen below. Renders nothing in production.
 *
 * The link sends a deliberate error-reporting test event and toasts the delivery
 * result — the dev/staging way to prove reporting works before a release
 * (run with EXPO_PUBLIC_APP_ENV=staging + MOBILE_BUGSNAG_API_KEY for a local
 * check). See services/errorReporting.ts sendSmokeTest.
 */
export function EnvBanner() {
  const insets = useSafeAreaInsets()

  if (APP_ENV === 'production') return null

  const label = APP_ENV === 'staging' ? 'STAGING APP' : 'DEVELOPMENT'

  const runSmokeTest = async () => {
    const result = await sendSmokeTest()
    if (result.ok) toast.success(`Error-reporting test event ${result.detail}`)
    else toast.error(`Error-reporting test failed: ${result.detail}`)
  }

  return (
    <View
      pointerEvents="box-none"
      style={[styles.container, { paddingTop: insets.top }]}
    >
      <View style={styles.row} pointerEvents="box-none">
        <Text style={styles.label}>{label}</Text>
        <Pressable
          onPress={runSmokeTest}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Send an error-reporting test event"
        >
          <Text style={styles.link}>· test error reporting</Text>
        </Pressable>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 9999,
    backgroundColor: COLORS.warning,
    alignItems: 'center',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  label: {
    color: COLORS.text,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    paddingVertical: 3,
  },
  link: {
    color: COLORS.text,
    fontSize: 11,
    fontWeight: '600',
    textDecorationLine: 'underline',
    paddingVertical: 3,
  },
})

export default EnvBanner
