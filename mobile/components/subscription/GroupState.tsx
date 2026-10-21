/**
 * /subscription `group_owner` and `group_member` states — members list;
 * owner: remove member, share / regenerate the invite link, and (self-paid
 * recurring only) native cancel/reactivate + Stripe portal; member: Leave.
 * Related: app/subscription.tsx, store/useGroupPlanStore.ts.
 */
import { useEffect } from 'react'
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Share,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { notify } from '../../services/errorReporting'
import { COLORS } from '../../constants'
import {
  useSubscriptionStore,
  type SubscriptionStatus,
} from '../../store/useSubscriptionStore'
import { useGroupPlanStore } from '../../store/useGroupPlanStore'
import { useAppConfig } from '../../store/useAppConfigStore'
import { isSelfPaidRecurring } from '../../utils/subscriptionDisplay'
import { useSubscriptionActions } from '../../hooks/useSubscriptionActions'
import toast from '../../utils/toast'
import { subscriptionStyles as styles } from './styles'

export function GroupState({
  state,
  status,
}: {
  state: 'group_owner' | 'group_member'
  status: SubscriptionStatus | null
}) {
  const appConfig = useAppConfig()
  const checkSubscription = useSubscriptionStore(s => s.checkSubscription)
  const {
    plan,
    isLoading,
    fetchGroupPlan,
    leavePlan,
    removeMember,
    regenerateInvite,
  } = useGroupPlanStore()
  const {
    busy: billingBusy,
    openingPortal,
    setRenew,
    openPortal,
  } = useSubscriptionActions()

  useEffect(() => {
    fetchGroupPlan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const willCancel = status?.cancel_at_period_end === true

  const handleShareInvite = () => {
    if (!plan) return
    Share.share({
      message: `Join my Group Plan on Made It Home: ${appConfig.shortDomain}/g/${plan.invite_code}`,
    })
  }

  const handleRegenerateInvite = () => {
    if (!plan) return
    Alert.alert(
      'Regenerate Link',
      'This will invalidate the current invite link. Anyone who has it will no longer be able to join.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Regenerate',
          style: 'destructive',
          onPress: async () => {
            try {
              await regenerateInvite(plan.id)
            } catch (error) {
              notify(
                error instanceof Error ? error : new Error(String(error)),
                'subscription.regenerate-invite'
              )
              toast.error(
                error instanceof Error
                  ? error.message
                  : 'Failed to regenerate link'
              )
            }
          },
        },
      ]
    )
  }

  const handleRemoveMember = (memberId: string, memberName: string | null) => {
    if (!plan) return
    Alert.alert(
      'Remove Member',
      `Remove ${memberName || 'this member'} from your group plan?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: async () => {
            try {
              await removeMember(plan.id, memberId)
            } catch (error) {
              notify(
                error instanceof Error ? error : new Error(String(error)),
                'subscription.remove-member'
              )
              toast.error(
                error instanceof Error
                  ? error.message
                  : 'Failed to remove member'
              )
            }
          },
        },
      ]
    )
  }

  const handleCancelPlan = () => {
    const endDate = status?.expires_at
      ? new Date(status.expires_at).toLocaleDateString()
      : null
    Alert.alert(
      'Cancel group plan?',
      endDate
        ? `Your plan stays active until ${endDate}. After that your members lose access (they get a short grace period).`
        : 'Your plan stays active until the end of the current period. After that your members lose access (they get a short grace period).',
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

  const handleLeavePlan = () => {
    if (!plan) return
    Alert.alert(
      'Leave Group Plan',
      "You'll need your own subscription after leaving.",
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Leave',
          style: 'destructive',
          onPress: async () => {
            try {
              await leavePlan(plan.id)
              await checkSubscription()
              // No navigation — status flips to 'none' and this same screen
              // re-renders that state.
            } catch (error) {
              notify(
                error instanceof Error ? error : new Error(String(error)),
                'subscription.leave-plan'
              )
              toast.error(
                error instanceof Error ? error.message : 'Failed to leave plan'
              )
            }
          },
        },
      ]
    )
  }

  if (isLoading && !plan) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={COLORS.primary} />
      </View>
    )
  }

  if (!plan) {
    return (
      <View style={styles.centered}>
        <Ionicons name="people-outline" size={48} color={COLORS.textLight} />
        <Text style={styles.emptyText}>No group plan</Text>
      </View>
    )
  }

  const isOwner = state === 'group_owner'
  // Only the owner's own self-paid recurring group sub is cancelable in-app
  // (admin/promotion/referral-granted group subs → PATCH would 404).
  const canManageBilling = isOwner && isSelfPaidRecurring(status)
  const activeMembers = plan.members?.filter(m => m.role !== undefined) || []

  return (
    <>
      <View style={styles.planInfo}>
        <Text style={styles.planOwner}>
          {isOwner ? 'Your group plan' : `${plan.owner_name}'s plan`}
        </Text>
        <Text style={styles.memberCount}>
          {plan.member_count}/{plan.max_members} members
        </Text>
      </View>

      <Text style={styles.sectionLabel}>Members</Text>
      <View style={styles.membersList}>
        {activeMembers.map(member => (
          <View key={member.id} style={styles.memberRow}>
            <View style={styles.memberInfo}>
              <Ionicons
                name="person-circle-outline"
                size={36}
                color={COLORS.primary}
              />
              <View style={styles.memberText}>
                <Text style={styles.memberName}>
                  {member.full_name || 'Member'}
                  {member.role === 'owner' && (
                    <Text style={styles.ownerBadge}> (Owner)</Text>
                  )}
                </Text>
                <Text style={styles.memberDate}>
                  Joined {new Date(member.joined_at).toLocaleDateString()}
                </Text>
              </View>
            </View>
            {isOwner && member.role !== 'owner' && (
              <TouchableOpacity
                onPress={() => handleRemoveMember(member.id, member.full_name)}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                <Ionicons
                  name="close-circle-outline"
                  size={24}
                  color={COLORS.danger}
                />
              </TouchableOpacity>
            )}
          </View>
        ))}
      </View>

      {isOwner && (
        <>
          <View style={styles.ownerActions}>
            <TouchableOpacity
              style={styles.shareButton}
              onPress={handleShareInvite}
            >
              <Ionicons name="share-outline" size={20} color={COLORS.white} />
              <Text style={styles.shareButtonText}>Share Invite Link</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.regenerateButton}
              onPress={handleRegenerateInvite}
            >
              <Text style={styles.regenerateText}>Regenerate invite link</Text>
            </TouchableOpacity>
          </View>

          {/* Owner billing: cancel/reactivate natively; change-plan and
              payment method stay on the hosted Stripe portal. */}
          {canManageBilling && (
            <View style={styles.ownerActions}>
              <TouchableOpacity
                style={styles.regenerateButton}
                onPress={openPortal}
                disabled={openingPortal}
              >
                {openingPortal ? (
                  <ActivityIndicator color={COLORS.primary} />
                ) : (
                  <Text style={styles.regenerateText}>
                    Change plan or payment method
                  </Text>
                )}
              </TouchableOpacity>

              {willCancel ? (
                <TouchableOpacity
                  style={styles.regenerateButton}
                  onPress={() => setRenew(true, 'Your plan will keep renewing')}
                  disabled={billingBusy}
                >
                  {billingBusy ? (
                    <ActivityIndicator color={COLORS.primary} />
                  ) : (
                    <Text style={styles.regenerateText}>Reactivate plan</Text>
                  )}
                </TouchableOpacity>
              ) : (
                <TouchableOpacity
                  style={styles.leaveButton}
                  onPress={handleCancelPlan}
                  disabled={billingBusy}
                >
                  <Ionicons
                    name="close-circle-outline"
                    size={20}
                    color={COLORS.danger}
                  />
                  <Text style={styles.leaveButtonText}>Cancel plan</Text>
                </TouchableOpacity>
              )}
            </View>
          )}
        </>
      )}

      {!isOwner && (
        <TouchableOpacity style={styles.leaveButton} onPress={handleLeavePlan}>
          <Ionicons name="exit-outline" size={20} color={COLORS.danger} />
          <Text style={styles.leaveButtonText}>Leave Group Plan</Text>
        </TouchableOpacity>
      )}
    </>
  )
}
