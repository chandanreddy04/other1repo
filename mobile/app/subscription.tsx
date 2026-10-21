import { useCallback } from 'react'
import {
  View,
  Text,
  SafeAreaView,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native'
import { useFocusEffect, useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../constants'
import { useRequireAuth } from '../hooks/useRequireAuth'
import { useSubscriptionStore } from '../store/useSubscriptionStore'
import { subscriptionState } from '../utils/subscriptionDisplay'
import { PlanCardState } from '../components/subscription/PlanCardState'
import { GroupState } from '../components/subscription/GroupState'
import { subscriptionStyles as styles } from '../components/subscription/styles'

// One subscription page (2026-09-23 owner decision), merging the old
// individual-management and group-plan screens into ONE page whose body is
// driven entirely by `subscriptionState(status)`:
//   none         — CTA → /plans
//   individual   — plan card; self-paid recurring gets cancel/reactivate +
//                  "Change plan or payment method" (portal); trial/promo/
//                  referral credit get a "See plans" CTA; other granted
//                  sources a "provided for you" note (`planCardMode`)
//   group_owner  — members list, invite link share, regenerate; billing
//                  (cancel/reactivate + portal) only when self-paid recurring
//   group_member — "<owner>'s plan", members list + Leave
//   sponsored    — status-only "provided for you" note (gift/comp)
//   day_pass     — plan card + "See plans" CTA
// Views live in components/subscription/.
export default function SubscriptionScreen() {
  const router = useRouter()
  // The Stripe portal return URL (/subscription) can cold-open this screen
  // signed out — gate it and replay the route after login.
  const authed = useRequireAuth()
  const status = useSubscriptionStore(state => state.status)
  const checkSubscription = useSubscriptionStore(
    state => state.checkSubscription
  )
  const statusLoading = useSubscriptionStore(state => state.isLoading)
  const state = subscriptionState(status)

  // Refresh on focus so the screen reflects changes made in the Stripe portal
  // (plan switch / payment update) after the user returns from the browser.
  useFocusEffect(
    useCallback(() => {
      if (authed) checkSubscription()
    }, [authed, checkSubscription])
  )

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()}>
          <Ionicons name="arrow-back" size={24} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Subscription</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        showsVerticalScrollIndicator={false}
      >
        {!authed || (status === null && statusLoading) ? (
          // Signed-out cold open (redirecting to login), or first load:
          // don't flash the "no active plan" state before the status arrives.
          <View style={styles.centered}>
            <ActivityIndicator size="large" color={COLORS.primary} />
          </View>
        ) : state === 'none' ? (
          <NoneState />
        ) : state === 'group_owner' || state === 'group_member' ? (
          <GroupState state={state} status={status} />
        ) : (
          <PlanCardState status={status} />
        )}
      </ScrollView>
    </SafeAreaView>
  )
}

// ---------------------------------------------------------------------------
// none — no active plan.
// ---------------------------------------------------------------------------

function NoneState() {
  const router = useRouter()
  return (
    <View style={styles.centered}>
      <Ionicons name="shield-outline" size={48} color={COLORS.textLight} />
      <Text style={styles.emptyText}>You don't have an active plan</Text>
      <TouchableOpacity
        style={styles.primaryButton}
        onPress={() => router.push('/plans')}
        activeOpacity={0.9}
      >
        <Text style={styles.primaryButtonText}>Choose a plan</Text>
      </TouchableOpacity>
    </View>
  )
}
