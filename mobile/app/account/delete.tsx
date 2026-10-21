/**
 * Account deletion confirmation flow.
 *
 * Two-stage screen that drives the user-visible side of the Phase 2/3
 * backend orchestration:
 *
 *   stage 'intro'   — personalized impact summary, "I understand, continue"
 *   stage 'confirm' — typed gate (must literally type "delete"), then
 *                     a native destructive Alert.alert before any API call
 *
 * On final confirm:
 *   - DELETE /users/me
 *   - reset every relevant Zustand store (so a stale cached profile or
 *     subscription doesn't survive the nav reset)
 *   - router.replace into the auth flow
 *   - toast that mentions the 30-day grace
 *
 * See docs/account-deletion-plan.md for the full state machine and copy.
 */
import { useState } from 'react'
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { Stack, useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS } from '../../constants'
import { useAuthStore } from '../../store/useAuthStore'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import { useGroupPlanStore } from '../../store/useGroupPlanStore'
import { useSessionStore } from '../../store/useSessionStore'
import { useCircleStore } from '../../store/useCircleStore'
import api from '../../services/api'
import { notify } from '../../services/errorReporting'
import { settingsScreenOptions } from '../../utils/screenOptions'
import toast from '../../utils/toast'

const CONFIRM_PHRASE = 'delete'

export default function DeleteAccountScreen() {
  const router = useRouter()
  const user = useAuthStore(state => state.user)
  const subStatus = useSubscriptionStore(state => state.status)
  const groupPlan = useGroupPlanStore(state => state.plan)
  const activeSession = useSessionStore(state => state.activeSession)

  const [stage, setStage] = useState<'intro' | 'confirm'>('intro')
  const [typed, setTyped] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const isOwner =
    groupPlan?.members?.some(m => m.user_id === user?.id && m.role === 'owner')

  const periodEndStr = subStatus?.expires_at
    ? new Date(subStatus.expires_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : null

  const handleFinalDelete = () => {
    Alert.alert(
      'Permanently delete your account?',
      'You can sign back in within 30 days to restore.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            setSubmitting(true)
            try {
              await api.deleteAccount()
              // Wipe every store's cached state so a navigation race
              // can't surface a stale subscription banner / circle list
              // after the user is back at the auth screen.
              useSubscriptionStore.getState().reset()
              useGroupPlanStore.getState().reset()
              useCircleStore.getState().reset()
              await useAuthStore.getState().logout()
              router.replace('/(auth)/login')
              toast.success(
                'Account deletion scheduled — sign back in within 30 days to restore.'
              )
            } catch (error) {
              setSubmitting(false)
              notify(
                error instanceof Error ? error : new Error(String(error)),
                'delete-account'
              )
              toast.error(
                error instanceof Error
                  ? error.message
                  : 'Could not delete account'
              )
            }
          },
        },
      ]
    )
  }

  return (
    <SafeAreaView style={styles.container}>
      <Stack.Screen options={settingsScreenOptions('Delete Account', router)} />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {stage === 'intro' ? (
            <>
              <View style={styles.iconWrap}>
                <Ionicons
                  name="warning-outline"
                  size={56}
                  color={COLORS.danger}
                />
              </View>
              <Text style={styles.title}>Delete your account?</Text>
              <Text style={styles.body}>
                You&apos;re about to permanently delete your Made It Home
                account. Here&apos;s what happens:
              </Text>

              {subStatus?.has_access &&
                subStatus.reason === 'subscription' &&
                periodEndStr && (
                  <Item
                    icon="card-outline"
                    title={`Your ${formatPlanName(subStatus.plan_type)} ends ${periodEndStr}.`}
                    detail={
                      isOwner
                        ? 'Members keep access until then. No refund — annual plans are non-refundable.'
                        : 'No refund — annual plans are non-refundable.'
                    }
                  />
                )}

              {activeSession && (
                <Item
                  icon="walk-outline"
                  title="Your active check-in will keep running."
                  detail="If you don't check in, your Circle will be alerted normally. SOS will still work."
                />
              )}

              <Item
                icon="trash-outline"
                title="Your photos, sessions, alerts, and Circle of Trust will be deleted within 30 days."
              />
              <Item
                icon="time-outline"
                title="You have 30 days to sign back in if you change your mind."
                detail="After that, this is permanent."
              />

              <TouchableOpacity
                style={styles.primaryButton}
                onPress={() => setStage('confirm')}
                activeOpacity={0.85}
              >
                <Text style={styles.primaryButtonText}>
                  I understand, continue
                </Text>
              </TouchableOpacity>
            </>
          ) : (
            <>
              <View style={styles.iconWrap}>
                <Ionicons
                  name="alert-circle-outline"
                  size={56}
                  color={COLORS.danger}
                />
              </View>
              <Text style={styles.title}>Final confirmation</Text>
              <Text style={styles.body}>
                Type <Text style={styles.confirmPhrase}>delete</Text> below to
                confirm.
              </Text>

              <TextInput
                value={typed}
                onChangeText={setTyped}
                style={styles.confirmInput}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="delete"
                placeholderTextColor={COLORS.textLight}
                editable={!submitting}
                accessibilityLabel="Type delete to confirm account deletion"
              />

              <TouchableOpacity
                style={[
                  styles.dangerButton,
                  (typed.trim().toLowerCase() !== CONFIRM_PHRASE ||
                    submitting) &&
                    styles.dangerButtonDisabled,
                ]}
                onPress={handleFinalDelete}
                disabled={
                  typed.trim().toLowerCase() !== CONFIRM_PHRASE || submitting
                }
                activeOpacity={0.85}
              >
                <Text style={styles.dangerButtonText}>
                  {submitting ? 'Deleting…' : 'Delete my account'}
                </Text>
              </TouchableOpacity>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

function Item({
  icon,
  title,
  detail,
}: {
  icon: React.ComponentProps<typeof Ionicons>['name']
  title: string
  detail?: string
}) {
  return (
    <View style={styles.item}>
      <Ionicons name={icon} size={22} color={COLORS.text} style={styles.itemIcon} />
      <View style={{ flex: 1 }}>
        <Text style={styles.itemTitle}>{title}</Text>
        {detail && <Text style={styles.itemDetail}>{detail}</Text>}
      </View>
    </View>
  )
}

function formatPlanName(planType: string | null | undefined): string {
  if (!planType) return 'plan'
  const map: Record<string, string> = {
    monthly: 'Monthly plan',
    annual: 'Annual plan',
    group_monthly: 'Group Monthly plan',
    group_annual: 'Group Annual plan',
  }
  return map[planType] ?? 'plan'
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  scrollContent: {
    padding: SPACING.xl,
    paddingBottom: SPACING['2xl'],
  },
  iconWrap: {
    alignItems: 'center',
    marginBottom: SPACING.md,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.md,
  },
  body: {
    fontSize: 16,
    color: COLORS.text,
    lineHeight: 22,
    marginBottom: SPACING.lg,
  },
  confirmPhrase: {
    fontWeight: '700',
    color: COLORS.danger,
  },
  item: {
    flexDirection: 'row',
    backgroundColor: COLORS.white,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.lightGray,
    marginBottom: SPACING.md,
  },
  itemIcon: {
    marginRight: SPACING.md,
    marginTop: 2,
  },
  itemTitle: {
    fontSize: 15,
    color: COLORS.text,
    fontWeight: '600',
    marginBottom: 2,
  },
  itemDetail: {
    fontSize: 14,
    color: COLORS.textLight,
    lineHeight: 20,
  },
  primaryButton: {
    backgroundColor: COLORS.primary,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
    marginTop: SPACING.lg,
  },
  primaryButtonText: {
    color: COLORS.white,
    fontSize: 16,
    fontWeight: '600',
  },
  confirmInput: {
    backgroundColor: COLORS.white,
    borderWidth: 2,
    borderColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.md,
    fontSize: 16,
    color: COLORS.text,
    marginBottom: SPACING.lg,
  },
  dangerButton: {
    backgroundColor: COLORS.danger,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
  },
  dangerButtonDisabled: {
    opacity: 0.4,
  },
  dangerButtonText: {
    color: COLORS.white,
    fontSize: 16,
    fontWeight: '600',
  },
})
