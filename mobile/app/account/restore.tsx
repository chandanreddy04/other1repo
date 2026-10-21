/**
 * Welcome Back — soft-delete grace recovery screen.
 *
 * Shown when verify-otp returns `deletion_pending: true` (the user signed
 * back in during the 30-day grace). The mobile app routes here instead
 * of `/(tabs)` with the access_token still in storage; only the restore
 * endpoint accepts it. From here the user can:
 *
 *   - Restore the account → POST /users/me/restore.
 *     - On 200, navigate into the app.
 *     - On 410 Gone (grace already expired by the time we land — rare
 *       but possible if mobile sat on the deletion_pending response
 *       past midnight), tell the user to sign up fresh.
 *
 *   - Sign out → useAuthStore.logout(). Deletion timer continues.
 *
 * See docs/account-deletion-plan.md "Welcome back / recovery during
 * grace" for the source copy.
 */
import { Stack, useLocalSearchParams, useRouter } from 'expo-router'
import { useState } from 'react'
import {
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, RADIUS, SPACING } from '../../constants'
import api from '../../services/api'
import { notify } from '../../services/errorReporting'
import { useAuthStore } from '../../store/useAuthStore'
import { useCircleStore } from '../../store/useCircleStore'
import { useGroupPlanStore } from '../../store/useGroupPlanStore'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import toast from '../../utils/toast'

interface ApiErrorLike {
  statusCode?: number
}

function isPastGraceError(err: unknown): boolean {
  return (err as ApiErrorLike)?.statusCode === 410
}

export default function WelcomeBackScreen() {
  const router = useRouter()
  const { scheduled_deletion_at } = useLocalSearchParams<{
    scheduled_deletion_at?: string
  }>()

  const [submitting, setSubmitting] = useState(false)

  // Guard against a malformed param (server change, deep-link tampering,
  // empty string). new Date('garbage') returns Invalid Date which would
  // surface as the literal text "Invalid Date" in the SMS copy below.
  const parsedDate = scheduled_deletion_at
    ? new Date(scheduled_deletion_at)
    : null
  const scheduledDate =
    parsedDate && !isNaN(parsedDate.getTime()) ? parsedDate : null
  const formattedDate = scheduledDate
    ? scheduledDate.toLocaleDateString(undefined, {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      })
    : null
  const daysRemaining = scheduledDate
    ? Math.max(
        0,
        Math.ceil(
          (scheduledDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24)
        )
      )
    : null

  const handleRestore = async () => {
    setSubmitting(true)
    try {
      const restoredUser = await api.restoreAccount()
      // Wipe any Zustand state left over from a prior session on this
      // device (the soft-delete that started the grace happened on a
      // different device, or the app cold-started past checkAuth). Each
      // tab's own fetch will repopulate from the now-restored backend.
      useSubscriptionStore.getState().reset()
      useGroupPlanStore.getState().reset()
      useCircleStore.getState().reset()
      useAuthStore.getState().setUser(restoredUser)
      router.replace('/(tabs)')
      toast.success('Welcome back — your account is restored.')
    } catch (error) {
      setSubmitting(false)
      if (isPastGraceError(error)) {
        // Grace expired between the deletion_pending OTP and now.
        // Wipe every store and drop the stale token before routing to
        // fresh signup — the user is starting over with a new user_id.
        useSubscriptionStore.getState().reset()
        useGroupPlanStore.getState().reset()
        useCircleStore.getState().reset()
        await useAuthStore.getState().logout()
        toast.info(
          'Your grace window has expired. Sign up to start a new account.'
        )
        router.replace('/(auth)/login')
        return
      }
      notify(
        error instanceof Error ? error : new Error(String(error)),
        'restore-account'
      )
      toast.error(
        error instanceof Error ? error.message : 'Could not restore account'
      )
    }
  }

  const handleSignOut = async () => {
    setSubmitting(true)
    try {
      await useAuthStore.getState().logout()
      router.replace('/(auth)/login')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      {/* Hide the back button — the user must commit to Restore or Sign
          out. Backing out to a stale screen would land them with tokens
          that 403 against every endpoint except /me/restore. */}
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.iconWrap}>
          <Ionicons name="heart-outline" size={64} color={COLORS.primary} />
        </View>
        <Text style={styles.title}>Welcome back.</Text>
        {formattedDate ? (
          <Text style={styles.body}>
            Your account is scheduled for permanent deletion on{' '}
            <Text style={styles.dateEmphasis}>{formattedDate}</Text>
            {daysRemaining != null && daysRemaining > 0
              ? ` (in ${daysRemaining} day${daysRemaining === 1 ? '' : 's'}).`
              : '.'}{' '}
            After that, your photos, sessions, and personal info will be
            permanently erased.
          </Text>
        ) : (
          <Text style={styles.body}>
            Your account is scheduled for permanent deletion. After that,
            your photos, sessions, and personal info will be permanently
            erased.
          </Text>
        )}

        <TouchableOpacity
          style={[styles.primaryButton, submitting && styles.disabledButton]}
          onPress={handleRestore}
          disabled={submitting}
          activeOpacity={0.85}
        >
          <Text style={styles.primaryButtonText}>
            {submitting ? 'Working…' : 'Restore my account'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.secondaryButton, submitting && styles.disabledButton]}
          onPress={handleSignOut}
          disabled={submitting}
          activeOpacity={0.85}
        >
          <Text style={styles.secondaryButtonText}>Sign out</Text>
        </TouchableOpacity>

        <Text style={styles.footnote}>
          Signing out will let the deletion proceed as scheduled.
        </Text>
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  scrollContent: {
    padding: SPACING.xl,
    paddingTop: SPACING['2xl'],
    flexGrow: 1,
  },
  iconWrap: {
    alignItems: 'center',
    marginBottom: SPACING.lg,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.lg,
  },
  body: {
    fontSize: 16,
    color: COLORS.text,
    lineHeight: 24,
    marginBottom: SPACING['2xl'],
    textAlign: 'center',
  },
  dateEmphasis: {
    fontWeight: '700',
    color: COLORS.danger,
  },
  primaryButton: {
    backgroundColor: COLORS.primary,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
    marginBottom: SPACING.md,
  },
  primaryButtonText: {
    color: COLORS.white,
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    backgroundColor: COLORS.white,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.lightGray,
    marginBottom: SPACING.md,
  },
  secondaryButtonText: {
    color: COLORS.text,
    fontSize: 16,
    fontWeight: '600',
  },
  disabledButton: {
    opacity: 0.5,
  },
  footnote: {
    fontSize: 13,
    color: COLORS.textLight,
    textAlign: 'center',
    fontStyle: 'italic',
  },
})
