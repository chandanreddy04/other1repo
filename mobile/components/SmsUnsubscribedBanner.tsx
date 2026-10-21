import React, { useEffect } from 'react'
import { Text, TouchableOpacity, StyleSheet, Platform } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import { useAuthStore } from '../store/useAuthStore'
import { useAppConfig } from '../store/useAppConfigStore'
import { COLORS, SPACING, TYPOGRAPHY } from '../constants'
import { leaveBreadcrumb } from '../services/errorReporting'

/**
 * Yellow warning banner shown at the top of every tab when the current
 * user's own phone has texted STOP to our Twilio number.
 *
 * The user hasn't unsubscribed from "the app" exactly — they keep push
 * and active sessions — but they've shut off OTP for their next
 * sign-in and lost every SMS-channel surface (sub-lapse warnings,
 * sponsor magic links, alerts that fall back from push). After
 * SMS_UNSUBSCRIBE_GRACE_DAYS the worker auto-cancels their Stripe
 * subscription if they haven't responded. The banner is the
 * persistent reminder until they act.
 *
 * Visually distinct from CircleEmptyBanner (red): this state is the
 * user's own choice, not a broken safety net, so we use the warmer
 * "yellow / heads-up" register.
 */
export function useShouldShowSmsUnsubscribedBanner(): boolean {
  const user = useAuthStore(s => s.user)
  return user?.sms_unsubscribed === true
}

export const SmsUnsubscribedBanner: React.FC = () => {
  const router = useRouter()
  const visible = useShouldShowSmsUnsubscribedBanner()
  const insets = useSafeAreaInsets()
  const support = useAppConfig().smsNumber

  useEffect(() => {
    if (!visible) return
    leaveBreadcrumb('SmsUnsubscribedBanner rendered', {
      platform: Platform.OS,
      platformVersion: String(Platform.Version),
      insetsTop: insets.top,
    })
  }, [visible, insets.top])

  if (!visible) return null
  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => router.push('/(tabs)/account')}
      activeOpacity={0.85}
      accessibilityRole="button"
      accessibilityLabel="You've unsubscribed from Made It Home texts. Tap to manage."
    >
      <Text style={styles.text}>
        You unsubscribed from texts.{' '}
        {support
          ? `Reply START to ${support} to re-enable, or tap to manage.`
          : 'Tap to manage or re-enable.'}
      </Text>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: COLORS.accent.orange,
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
