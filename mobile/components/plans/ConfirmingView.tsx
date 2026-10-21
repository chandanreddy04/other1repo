/**
 * /plans `confirming` step — polls + re-checks on foreground (AppState) until
 * access unlocks, then resumes the interrupted session draft (or goes home).
 * Its no-access state has a "Back to plans" escape. Related: app/plans.tsx.
 */
import { useEffect, useRef, useState } from 'react'
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  AppState,
  AppStateStatus,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../../constants'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import { hasSessionDraft } from '../../utils/sessionDraft'
import toast from '../../utils/toast'
import { plansStyles as styles } from './styles'

const MAX_POLLS = 10
const POLL_INTERVAL_MS = 1000

export function ConfirmingView({
  onBackToPlans,
}: {
  onBackToPlans: () => void
}) {
  const router = useRouter()
  const { checkSubscription, status } = useSubscriptionStore()
  const [checking, setChecking] = useState(true)
  const pollCount = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const resumeAfterAccess = async () => {
    setChecking(false)
    toast.success('Subscription activated!')
    // Resume the session /plans interrupted, if any (D3).
    const draft = await hasSessionDraft()
    setTimeout(() => router.replace(draft ? '/sessions/new' : '/(tabs)'), 1500)
  }

  useEffect(() => {
    const poll = async () => {
      await checkSubscription()
      const current = useSubscriptionStore.getState().status
      if (current?.has_access) {
        await resumeAfterAccess()
        return
      }
      pollCount.current += 1
      if (pollCount.current < MAX_POLLS) {
        timerRef.current = setTimeout(poll, POLL_INTERVAL_MS)
      } else {
        setChecking(false)
      }
    }
    poll()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const handleAppState = (nextState: AppStateStatus) => {
      if (nextState === 'active') {
        pollCount.current = 0
        setChecking(true)
        checkSubscription().then(async () => {
          const current = useSubscriptionStore.getState().status
          if (current?.has_access) {
            await resumeAfterAccess()
          }
        })
      }
    }
    const sub = AppState.addEventListener('change', handleAppState)
    return () => sub.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const hasAccess = status?.has_access

  return (
    <View style={styles.confirmingContent}>
      {checking ? (
        <>
          <ActivityIndicator size="large" color={COLORS.primary} />
          <Text style={styles.message}>Confirming your subscription...</Text>
        </>
      ) : hasAccess ? (
        <>
          <View style={styles.iconCircle}>
            <Ionicons
              name="checkmark-circle"
              size={64}
              color={COLORS.primary}
            />
          </View>
          <Text style={styles.confirmingTitle}>You're all set!</Text>
          <Text style={styles.confirmingSubtitle}>
            Your subscription is now active.
          </Text>
        </>
      ) : (
        <>
          <Ionicons name="time-outline" size={64} color={COLORS.textLight} />
          <Text style={styles.confirmingTitle}>Almost there</Text>
          <Text style={styles.confirmingSubtitle}>
            If you completed checkout, your access may take a moment to activate
            — we'll unlock it automatically. If you didn't finish, you can head
            back and try again.
          </Text>
          <TouchableOpacity
            style={styles.backButton}
            onPress={onBackToPlans}
            activeOpacity={0.8}
          >
            <Text style={styles.backButtonText}>Back to plans</Text>
          </TouchableOpacity>
        </>
      )}
    </View>
  )
}
