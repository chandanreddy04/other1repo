/**
 * Session — ONE screen for the resource, live or ended (owner decision,
 * Commit 12: the live check-in and the past session summary are the SAME
 * resource in different states, not two screens). Mode comes from
 * `sessionScreenMode(session.status)` (utils/sessionMode.ts):
 *   - 'live' (active/missed/alerted): LiveSessionView — the countdown /
 *     overdue chrome the old dedicated live-check-in screen used to render.
 *   - 'ended' (completed/cancelled): EndedSessionView — the outcome +
 *     retention chrome the old dedicated past-session screen used to render.
 *
 * Data source + live escalation poll live in `hooks/useSessionScreen.ts`
 * (by-id fetch, store precedence, the T-2min server-truth poll, the flip to
 * ended mode when a live session ends while open). This screen owns the
 * actions (I'm Safe, extend, retention adjust) and the per-second clock.
 *
 * Related: app/sessions/index.tsx, app/sessions/active.tsx,
 *          hooks/useSessionScreen.ts,
 *          utils/sessionMode.ts, utils/retention.ts,
 *          components/session/LiveSessionView.tsx,
 *          components/session/EndedSessionView.tsx.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  Share,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router'
import { ModalHeader } from '../../components/ModalHeader'
import { LiveSessionView } from '../../components/session/LiveSessionView'
import { EndedSessionView } from '../../components/session/EndedSessionView'
import { useLocationTrail } from '../../hooks/useLocationTrail'
import { useSessionScreen } from '../../hooks/useSessionScreen'
import { usePermissionRequirements } from '../../hooks/usePermissionRequirements'
import { sessionRequirementItems } from '../../utils/permissionUi'
import sessionGather from '../../services/sessionGather'
import { useSessionStore } from '../../store/useSessionStore'
import { useCircleStore } from '../../store/useCircleStore'
import { useAuthStore } from '../../store/useAuthStore'
import { useAppConfig } from '../../store/useAppConfigStore'
import api from '../../services/api'
import { notify } from '../../services/errorReporting'
import toast from '../../utils/toast'
import {
  shouldShowReferralPrompt,
  recordReferralPrompt,
} from '../../utils/referralPrompt'
import { CHECKIN_CONFIG, COLORS } from '../../constants'
import { isDataHeld } from '../../utils/retention'

export default function SessionScreen() {
  const router = useRouter()
  const { id } = useLocalSearchParams<{ id: string }>()

  const completeSession = useSessionStore(state => state.completeSession)
  const extendSession = useSessionStore(state => state.extendSession)
  const referralCode = useAuthStore(state => state.user?.share_code)
  const appConfig = useAppConfig()

  const circleOfTrust = useCircleStore(state => state.circleOfTrust)
  const circleLoaded = useCircleStore(state => state.circleLoaded)
  const loadCircleOfTrust = useCircleStore(state => state.loadCircleOfTrust)

  const { session, mode, loading, loadError, reload, applySessionUpdate } =
    useSessionScreen(id)

  const [actionLoading, setActionLoading] = useState(false)
  const [adjustingRetention, setAdjustingRetention] = useState(false)
  // Per-second clock tick driving the countdown/count-up — same derivation
  // as the Home card so the two clocks can never disagree.
  const [nowTick, setNowTick] = useState(() => Date.now())

  const isLive = mode === 'live'
  useEffect(() => {
    if (!isLive) return
    const interval = setInterval(() => setNowTick(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [isLive])

  // Live mode only: fresh circle read (retracts the "your contacts will be
  // alerted" promise if the circle emptied mid-session).
  useEffect(() => {
    if (!isLive) return
    loadCircleOfTrust().catch(() => {
      // benign: the contacts store reports and keeps the last circle
    })
  }, [isLive, loadCircleOfTrust])

  // Foreground gather: capture a fresh reading whenever this screen is
  // focused in live mode, so battery stays current even when location
  // sharing is off (no location task feeding it).
  useFocusEffect(
    useCallback(() => {
      if (isLive) void sessionGather.gatherNow()
    }, [isLive])
  )

  const dataHeld = session != null && mode === 'ended' && isDataHeld(session)
  // A trail is only fetched for a session that actually shares location —
  // live (always) or ended while its data is still held (never once purged).
  const trailSessionId =
    session?.location_sharing_enabled && (isLive || dataHeld)
      ? session.id
      : null
  const { fixes: trailFixes, loading: trailLoading } = useLocationTrail(
    trailSessionId,
    { refresh: isLive }
  )

  const { gaps: permissionGaps, refresh: refreshPermissions } =
    usePermissionRequirements(['location', 'notifications'])
  const permissionItems = sessionRequirementItems(permissionGaps)

  const handleComplete = () => {
    if (!session) return
    Alert.alert(
      'Mark yourself safe?',
      'Are you sure you want to mark yourself as safe?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: "Yes, I'm Safe",
          onPress: async () => {
            setActionLoading(true)
            try {
              await completeSession(session.id)
              toast.info(
                `Your session data will be automatically deleted in ${CHECKIN_CONFIG.SESSION_DATA_RETENTION_DAYS} days`
              )
              const shouldPrompt = await shouldShowReferralPrompt()
              if (shouldPrompt && referralCode) {
                await recordReferralPrompt()
                Alert.alert(
                  'Share Made It Home',
                  'Know someone who could use a safety companion? Share your referral and give them a free month.',
                  [
                    {
                      text: 'Not Now',
                      style: 'cancel',
                      onPress: () => router.replace('/(tabs)'),
                    },
                    {
                      text: 'Share',
                      onPress: async () => {
                        await Share.share({
                          message: `Stay safe with Made It Home! Register here for a free month: ${appConfig.shortDomain}/r/${referralCode}`,
                        })
                        router.replace('/(tabs)')
                      },
                    },
                  ]
                )
              } else {
                router.replace('/(tabs)')
              }
            } catch (error) {
              notify(
                error instanceof Error ? error : new Error(String(error)),
                'complete-session'
              )
              toast.error(
                error instanceof Error
                  ? error.message
                  : 'Failed to mark yourself safe'
              )
            } finally {
              setActionLoading(false)
            }
          },
        },
      ]
    )
  }

  // One tap, no confirm dialog — a user running late needs the fastest
  // possible extend (owner decision, docs/flow-review.md §4.3 C3).
  const handleExtend = async (minutes: number) => {
    if (!session) return
    setActionLoading(true)
    try {
      await extendSession(minutes, session.id)
      toast.success(
        minutes > 0
          ? `Extended by ${minutes} minutes`
          : `Reduced by ${Math.abs(minutes)} minutes`
      )
    } catch (error) {
      notify(
        error instanceof Error ? error : new Error(String(error)),
        'extend-session'
      )
      toast.error(
        error instanceof Error ? error.message : 'Failed to extend session'
      )
    } finally {
      setActionLoading(false)
    }
  }

  const handleAdjustRetention = async (days: number) => {
    if (!session) return
    setAdjustingRetention(true)
    try {
      const updated = await api.adjustSessionRetention(session.id, days)
      applySessionUpdate(updated)
      toast.success(
        days > 0 ? 'Kept for 7 more days' : 'Deletion moved 7 days earlier'
      )
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to adjust retention'
      )
    } finally {
      setAdjustingRetention(false)
    }
  }

  if (!session || !mode) {
    return (
      <SafeAreaView style={styles.container}>
        <ModalHeader title="Session" onBack={() => router.back()} />
        <View style={styles.centered}>
          {loading ? (
            <ActivityIndicator size="large" color={COLORS.primary} />
          ) : loadError === 'failed' ? (
            <>
              <Text style={styles.emptyText}>
                Couldn't load this session
              </Text>
              <TouchableOpacity
                style={styles.retryButton}
                onPress={() => void reload()}
                testID="session-retry"
              >
                <Text style={styles.retryButtonText}>Try again</Text>
              </TouchableOpacity>
            </>
          ) : (
            <Text style={styles.emptyText}>Session not found</Text>
          )}
        </View>
      </SafeAreaView>
    )
  }

  if (mode === 'live') {
    return (
      <LiveSessionView
        session={session}
        nowTick={nowTick}
        actionLoading={actionLoading}
        onComplete={handleComplete}
        onExtend={handleExtend}
        onBack={() => router.back()}
        circleOfTrust={circleOfTrust}
        circleLoaded={circleLoaded}
        permissionItems={permissionItems}
        onPermissionsChanged={refreshPermissions}
        trailFixes={trailFixes}
        trailLoading={trailLoading}
      />
    )
  }

  return (
    <EndedSessionView
      session={session}
      dataHeld={dataHeld}
      adjusting={adjustingRetention}
      onAdjustRetention={handleAdjustRetention}
      onBack={() => router.back()}
      trailFixes={trailFixes}
      trailLoading={trailLoading}
    />
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 18,
    color: COLORS.textLight,
  },
  retryButton: {
    marginTop: 20,
    backgroundColor: COLORS.primary,
    paddingHorizontal: 30,
    paddingVertical: 15,
    borderRadius: 999,
  },
  retryButtonText: {
    color: COLORS.white,
    fontSize: 16,
    fontWeight: '600',
  },
})
