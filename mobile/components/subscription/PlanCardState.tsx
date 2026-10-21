/**
 * /subscription `individual`, `sponsored` and `day_pass` states — one plan
 * card plus, by `planCardMode(status)`, native cancel/reactivate + the Stripe
 * portal (`manage`), a "See plans" CTA (`upgrade`), or a status-only note
 * (`provided`). Related: app/subscription.tsx, utils/subscriptionDisplay.ts.
 */
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../../constants'
import type { SubscriptionStatus } from '../../store/useSubscriptionStore'
import { SettingRow } from '../SettingRow'
import {
  getPlanLabel,
  getSubscriptionStatusLine,
  planCardMode,
} from '../../utils/subscriptionDisplay'
import { useSubscriptionActions } from '../../hooks/useSubscriptionActions'
import { subscriptionStyles as styles } from './styles'

/** Honest copy for the `upgrade` mode — nothing to manage, a plan to buy. */
function upgradeNote(status: SubscriptionStatus | null): string {
  if (status?.plan_type === 'day_pass') {
    return 'Your day pass covers you for 24 hours. Want protection every night? Pick a plan.'
  }
  if (status?.reason === 'free_trial') {
    return "You're on the free trial. Pick a plan to keep checking in after it."
  }
  return "This free access doesn't renew. Pick a plan to stay covered after it ends."
}

export function PlanCardState({
  status,
}: {
  status: SubscriptionStatus | null
}) {
  const router = useRouter()
  const { busy, openingPortal, setRenew, openPortal } = useSubscriptionActions()
  const mode = planCardMode(status)
  const willCancel = status?.cancel_at_period_end === true

  const handleCancel = () => {
    const endDate = status?.expires_at
      ? new Date(status.expires_at).toLocaleDateString()
      : null
    Alert.alert(
      'Cancel subscription?',
      endDate
        ? `Your plan stays active until ${endDate}, then won't renew.`
        : "Your plan stays active until the end of the current period, then won't renew.",
      [
        { text: 'Keep plan', style: 'cancel' },
        {
          text: 'Cancel plan',
          style: 'destructive',
          onPress: () => setRenew(false, 'Your plan will not renew'),
        },
      ]
    )
  }

  return (
    <>
      <View style={styles.planCard}>
        <Ionicons name="card" size={28} color={COLORS.primary} />
        <Text style={styles.planLabel}>{getPlanLabel(status) ?? 'Plan'}</Text>
        <Text style={styles.planStatus}>
          {getSubscriptionStatusLine(status)}
        </Text>
      </View>

      {mode === 'manage' ? (
        <>
          {willCancel ? (
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() => setRenew(true, 'Your plan will keep renewing')}
              disabled={busy}
              activeOpacity={0.9}
            >
              {busy ? (
                <ActivityIndicator color={COLORS.white} />
              ) : (
                <Text style={styles.primaryButtonText}>Reactivate plan</Text>
              )}
            </TouchableOpacity>
          ) : null}

          <View style={styles.section}>
            <SettingRow
              icon="swap-horizontal-outline"
              label="Change plan or payment method"
              showArrow
              disabled={openingPortal}
              onPress={openPortal}
            />
          </View>

          {!willCancel ? (
            <TouchableOpacity
              style={styles.cancelButton}
              onPress={handleCancel}
              disabled={busy}
              activeOpacity={0.7}
            >
              {busy ? (
                <ActivityIndicator color={COLORS.danger} />
              ) : (
                <Text style={styles.cancelButtonText}>Cancel subscription</Text>
              )}
            </TouchableOpacity>
          ) : null}
        </>
      ) : mode === 'upgrade' ? (
        <>
          <Text style={[styles.statusOnlyNote, styles.upgradeNote]}>
            {upgradeNote(status)}
          </Text>
          <TouchableOpacity
            style={styles.primaryButton}
            onPress={() => router.push('/plans')}
            activeOpacity={0.9}
          >
            <Text style={styles.primaryButtonText}>See plans</Text>
          </TouchableOpacity>
        </>
      ) : (
        // Gift / comp / admin-granted: nothing for the recipient to manage.
        <Text style={styles.statusOnlyNote}>
          This subscription was provided for you — there's nothing to manage
          here. Enjoy the peace of mind.
        </Text>
      )}
    </>
  )
}
