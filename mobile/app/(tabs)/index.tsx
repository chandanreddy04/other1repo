import { useState, useEffect } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  ScrollView,
  SafeAreaView,
  RefreshControl,
  Alert,
  Linking,
  TouchableOpacity,
} from 'react-native'
import { useRouter, useLocalSearchParams } from 'expo-router'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { useAuthStore } from '../../store/useAuthStore'
import { useSessionStore } from '../../store/useSessionStore'
import { useCircleStore } from '../../store/useCircleStore'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import { Button, Card } from '../../components/ui'
import { SessionAdjustRow } from '../../components/SessionAdjustRow'
import { TrustCircleIcon } from '../../components/icons/TrustCircleIcon'
import { ShareReferralButton } from '../../components/ShareReferralButton'
import { PermissionsHome } from '../../components/PermissionsHome'
import {
  CHECKIN_CONFIG,
  COLORS,
  TYPOGRAPHY,
  SPACING,
  RADIUS,
} from '../../constants'
import { SAFETY_TIPS } from '../../constants/safetyTips'
import { formatTime, formatHms } from '../../utils/dateFormatting'
import { getSessionDeadline } from '../../utils/sessionTiming'
import { clearPendingSOS, isTerminalSOSError } from '../../services/sosQueue'
import liveStatusService, {
  homePillStatusTitle,
  liveStatusContent,
} from '../../services/liveStatus'
import api from '../../services/api'
import toast from '../../utils/toast'
import { notify, report } from '../../services/errorReporting'

export default function HomeScreen() {
  const router = useRouter()
  const params = useLocalSearchParams()
  const user = useAuthStore(state => state.user)
  const activeSession = useSessionStore(state => state.activeSession)
  const loadActiveSession = useSessionStore(state => state.loadActiveSession)
  const sendSOS = useSessionStore(state => state.sendSOS)
  const completeSession = useSessionStore(state => state.completeSession)
  const extendSession = useSessionStore(state => state.extendSession)
  const flushCheckinQueue = useSessionStore(state => state.flushCheckinQueue)
  const flushSOSQueue = useSessionStore(state => state.flushSOSQueue)
  const circleOfTrust = useCircleStore(state => state.circleOfTrust)
  const circleLoaded = useCircleStore(state => state.circleLoaded)
  const loadCircleOfTrust = useCircleStore(state => state.loadCircleOfTrust)
  const checkSubscription = useSubscriptionStore(
    state => state.checkSubscription
  )
  const subscriptionStatus = useSubscriptionStore(state => state.status)
  const [refreshing, setRefreshing] = useState(false)
  const [isAlarmState, setIsAlarmState] = useState(false)
  // Client-provable SOS delivery state for the alarm card. 'sending' = the
  // request hasn't resolved; 'queued' = retryable failure, sosQueue is
  // retrying. Cleared once the server-confirmed session exists — from there
  // the card renders server truth (activeSession.status via liveStatusContent),
  // never a client claim that the circle was reached.
  const [sosDelivery, setSosDelivery] = useState<'sending' | 'queued' | null>(
    null
  )
  // Drives the live ETA countdown on the session card. Ticks every
  // second so the number visibly counts down inside the final urgent stretch.
  const [nowTick, setNowTick] = useState(() => Date.now())
  const [safetyTip] = useState(
    () => SAFETY_TIPS[Math.floor(Math.random() * SAFETY_TIPS.length)]
  )

  useEffect(() => {
    // Flush anything queued while offline — fire-and-forget. Check-ins (a
    // failed "I'm safe") and, critically, a panic SOS that couldn't be sent
    // keep retrying in the background instead of asking the user to re-press.
    flushCheckinQueue().catch(err => notify(err, 'home.flush-checkin-queue'))
    flushSOSQueue().catch(err => notify(err, 'home.flush-sos-queue'))
    // Load both active session and Circle of Trust
    Promise.all([
      loadActiveSession().catch(error => {
        // If the profile is incomplete, redirect to the mandatory name step
        if (error.statusCode === 428 || error.requiresProfile) {
          router.replace({
            pathname: '/account/profile',
            params: { required: '1' },
          })
        }
      }),
      loadCircleOfTrust(),
      checkSubscription(),
    ])

    // Check if emergency was activated from SOS button
    if (params.emergencyActivated) {
      // Show the alarm UI instantly (the red framing — "you did it, don't
      // second-guess"), but the badge says "Sending…" until the server
      // confirms: the card must never claim the circle was reached before
      // the request even left the device.
      setIsAlarmState(true)
      setSosDelivery('sending')
      sendSOS()
        .then(() => setSosDelivery(null))
        .catch(err => {
          report(err, 'home.sos') // never skipped, even for a 4xx refusal
          if (isTerminalSOSError(err)) {
            // The server refused (e.g. no active circle members) — retrying
            // cannot help, so the alarm UI must come down and the user must
            // hear it straight. A reassuring screen here would be a lie.
            setIsAlarmState(false)
            setSosDelivery(null)
            Alert.alert(
              "SOS couldn't be sent",
              `${
                err instanceof Error && err.message
                  ? err.message
                  : 'We could not alert your Circle'
              }. ` + 'If this is an emergency, call 911 now.',
              [
                {
                  text: 'Call 911',
                  style: 'destructive',
                  onPress: () => Linking.openURL('tel:911'),
                },
                { text: 'OK' },
              ]
            )
            return
          }
          // Retryable (network/server hiccup): the alert is queued and
          // retries on an interval, on app foreground, and via an OS
          // background task — don't ask the user to re-press. The card
          // shows a persistent "still trying" banner (not just a toast).
          setSosDelivery('queued')
        })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.emergencyActivated])

  // Tick the countdown clock once a second while a session is active.
  useEffect(() => {
    if (!activeSession) return
    const id = setInterval(() => setNowTick(Date.now()), 1000)
    return () => clearInterval(id)
  }, [activeSession])

  // A queued SOS that lands via the background flush sets activeSession —
  // the card then renders server truth, so the delivery state is done.
  useEffect(() => {
    if (activeSession && sosDelivery === 'queued') setSosDelivery(null)
  }, [activeSession, sosDelivery])

  // Two ONE-SHOT server-truth refreshes (not a poll): at the deadline, and
  // just after the grace window (when the worker's MISSED→ALERTED promotion
  // typically lands). The store otherwise only refreshes on mount/pull, so
  // without these the pill would say "Overdue" forever while the circle is
  // being alerted. Each refresh also updates the lock screen. O4's push
  // refresh is the fast path; these are the no-push fallback.
  useEffect(() => {
    if (!activeSession) return
    const sessionId = activeSession.id
    const deadline = getSessionDeadline(activeSession)?.getTime()
    if (!deadline) return
    let cancelled = false

    const refresh = async () => {
      try {
        const session = await api.getSession(sessionId)
        if (cancelled) return
        useSessionStore.setState({ activeSession: session })
        void liveStatusService.update(session)
      } catch {
        // benign: Best-effort — pull-to-refresh, the push refresh, and the
        // session screen's own escalation poll all remain available.
      }
    }

    const timers: ReturnType<typeof setTimeout>[] = []
    const schedule = (at: number) => {
      const delay = at - Date.now()
      if (delay > 0) timers.push(setTimeout(() => void refresh(), delay))
    }
    schedule(deadline + 1000)
    schedule(deadline + (CHECKIN_CONFIG.ALERT_GRACE_MINUTES * 60 + 90) * 1000)
    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
    // Re-arm only when the session or its deadline changes (extend), not on
    // every store refresh of the same session object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.id, activeSession?.expected_return_time])

  const onRefresh = async () => {
    setRefreshing(true)
    await Promise.all([loadActiveSession(), loadCircleOfTrust()])
    setRefreshing(false)
  }

  // "I'm Safe" from the alarm card. Three cases:
  // 1. The SOS reached the server (activeSession set) → complete it. The
  //    alarm UI only comes down on success — a server-rejected mark-safe must
  //    keep the emergency framing up, because the circle's alerts are still
  //    live (dismissing silently was a real bug).
  // 2. The SOS is still queued offline → cancel the pending queue so it can't
  //    fire later, after the user already said they're fine (zombie SOS).
  // 3. The queue flushed mid-tap (rare race) → the session exists after a
  //    re-check; fall through to completing it.
  const handleAlarmImSafe = async () => {
    if (!activeSession) {
      await clearPendingSOS()
      // An in-flight flush may have just landed the SOS server-side —
      // re-check before claiming nothing was sent.
      await loadActiveSession().catch(() => {
        // benign: best-effort re-check; the store reports load failures
      })
      if (!useSessionStore.getState().activeSession) {
        setIsAlarmState(false)
        setSosDelivery(null)
        toast.success('Cancelled — nothing was sent')
        return
      }
    }
    try {
      await completeSession()
      setIsAlarmState(false)
      setSosDelivery(null)
      toast.success('Marked safe')
    } catch (err) {
      notify(err, 'home.mark-safe')
      toast.error("Couldn't mark you safe — try again")
    }
  }

  // Live countdown to the session deadline. Urgent (red) inside the final
  // 5 minutes and once overdue — mirrors the alert grace window.
  const sessionDeadline = activeSession
    ? getSessionDeadline(activeSession)
    : null
  const sessionRemainingMs = sessionDeadline
    ? sessionDeadline.getTime() - nowTick
    : 0
  // Server truth replaces the countdown once the session escalates
  // ("Notifying your circle…" — shared table); the clock only ever states
  // the clock fact, never a notified claim the server hasn't confirmed.
  const pillStatusTitle = activeSession
    ? homePillStatusTitle(activeSession)
    : null
  const countdownUrgent =
    pillStatusTitle != null || sessionRemainingMs <= 5 * 60 * 1000
  // Clock fact: the deadline passed (grace/escalation window). Drives the
  // count-up, the red framing and the missed title on the Home card.
  const homeOverdue = sessionDeadline != null && sessionRemainingMs <= 0
  // Server truth, not the navigation param — the SOS card must survive a
  // relaunch mid-incident (the param-only version fell back to the check-in
  // card and mislabeled an SOS "Check-in time missed").
  const isSOSSession = activeSession?.session_type === 'sos'
  // -30m must leave at least the minimum session lead on the clock.
  const canReduce30 =
    sessionRemainingMs >
    (30 + CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES) * 60 * 1000

  const handleAdjust = (minutes: number) => {
    extendSession(minutes)
      .then(() =>
        toast.success(
          minutes > 0
            ? `Extended by ${minutes} minutes`
            : `Reduced by ${Math.abs(minutes)} minutes`
        )
      )
      .catch(err => {
        notify(err, 'home.adjust-session-time')
        toast.error("Couldn't adjust the time — try again")
      })
  }

  // The circle emptied mid-session (STOP cascade) — retract the sharing/
  // alerting promise, tense following the alert window. ALERTED is excluded:
  // alerts DID go out before the circle emptied, so neither line is true.
  // Empty is only meaningful after a real load (never the initial []).
  const circleEmpty =
    circleLoaded && !circleOfTrust.some(m => m.status === 'active')
  const emptyCircleCopy =
    circleEmpty && activeSession?.status === 'missed'
      ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.POST_DEADLINE
      : circleEmpty && activeSession?.status === 'active'
        ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.PRE_ALERT
        : null

  return (
    <SafeAreaView style={styles.container}>
      <LinearGradient colors={['#FAFBFC', '#F4F6F7']} style={styles.gradient}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          {/* Header Section */}
          <View style={styles.header}>
            <Text style={styles.greeting}>
              Hi, {user?.full_name?.split(' ')[0] || 'Friend'}!
            </Text>
            <ShareReferralButton />
          </View>

          {/* Persistent permissions card — stays until all needed perms granted */}
          <PermissionsHome />

          {/* Main Session Card with 3 states */}
          <Card
            variant="default"
            elevation="md"
            style={[styles.mainCard, isAlarmState && styles.alarmCard]}
            borderColor={
              isAlarmState || homeOverdue || isSOSSession
                ? COLORS.danger
                : undefined
            }
            borderWidth={
              isAlarmState || homeOverdue || isSOSSession ? 2 : undefined
            }
          >
            {isAlarmState && !activeSession ? (
              // SOS DELIVERY PHASE — the press happened but the server hasn't
              // confirmed a session yet, so there's nothing to show a status
              // or clock ABOUT: status says what's provable ("Sending…" /
              // "Not sent yet"), the clock sits frozen at zero, and the
              // queued banner appears only while offline retries run.
              <>
                <View style={styles.cardHeader}>
                  <Text
                    style={[styles.cardTitle, styles.cardTitleFlex]}
                    numberOfLines={1}
                  >
                    Emergency SOS
                  </Text>
                </View>

                <Text style={styles.homeStatusTitle}>
                  {sosDelivery === 'queued' ? 'Not sent yet' : 'Sending…'}
                </Text>
                <Text
                  style={[styles.homeCountdown, styles.homeCountdownUrgent]}
                >
                  +00:00:00
                </Text>

                {sosDelivery === 'queued' && (
                  <View style={styles.sosQueuedBanner}>
                    <Ionicons
                      name="cloud-offline"
                      size={18}
                      color={COLORS.danger}
                    />
                    <Text style={styles.sosQueuedText}>
                      Still trying to reach your Circle — no connection. Call
                      911 if this is an emergency.
                    </Text>
                  </View>
                )}

                <View style={styles.captureSection}>
                  <Text style={styles.captureLabel}>
                    Sharing with your Circle
                  </Text>
                  <View style={styles.captureChips}>
                    <View style={styles.captureChip}>
                      <Ionicons
                        name="location"
                        size={16}
                        color={COLORS.primary}
                      />
                    </View>
                    <View style={styles.captureChip}>
                      <Ionicons
                        name="battery-half"
                        size={16}
                        color={COLORS.primary}
                      />
                    </View>
                    <View style={styles.captureChip}>
                      <Ionicons
                        name="camera"
                        size={16}
                        color={COLORS.primary}
                      />
                    </View>
                  </View>
                </View>

                <View style={styles.sessionActions}>
                  <Button
                    title="I'm Safe"
                    onPress={() => {
                      void handleAlarmImSafe()
                    }}
                    variant="primary"
                    fullWidth
                    size="large"
                  />
                </View>
              </>
            ) : activeSession ? (
              // UNIFIED SESSION CARD — one template for check-in and SOS;
              // rendering is driven by SERVER TRUTH (session_type/status), so
              // it survives relaunch mid-incident. Whole card taps through to
              // the full session detail screen (live mode). Visible
              // differences between the red states all trace to real
              // differences in the world: an SOS has no ETA/grace/adjusters;
              // a check-in has no delivery phase.
              <TouchableOpacity
                activeOpacity={0.85}
                onPress={() => router.push(`/sessions/${activeSession.id}`)}
              >
                <View style={styles.cardHeader}>
                  <Text
                    style={[styles.cardTitle, styles.cardTitleFlex]}
                    numberOfLines={1}
                  >
                    {isSOSSession
                      ? 'Emergency SOS'
                      : homeOverdue
                        ? 'Check-in time missed'
                        : 'Active Session'}
                  </Text>
                </View>

                {/* Status line: server-truth escalation news (shared table),
                    beneath the title. Absent until there is news. */}
                {activeSession.status !== 'active' && (
                  <Text style={styles.homeStatusTitle}>
                    {liveStatusContent(activeSession).title}
                  </Text>
                )}

                {/* The clock is ALWAYS present: counting down, or counting UP
                    in red once past the deadline (SOS counts up from the
                    press — its deadline IS the press). */}
                <Text
                  style={[
                    styles.homeCountdown,
                    countdownUrgent && styles.homeCountdownUrgent,
                  ]}
                >
                  {homeOverdue
                    ? `+${formatHms(Math.abs(sessionRemainingMs))}`
                    : formatHms(sessionRemainingMs)}
                </Text>
                {!isSOSSession && (
                  <Text style={styles.etaText}>
                    ETA{' '}
                    {formatTime(
                      activeSession.expected_arrival_time ||
                        activeSession.expected_return_time
                    )}
                  </Text>
                )}
                {!isSOSSession && activeSession.status === 'active' && (
                  <View style={styles.homeAdjustWrap}>
                    <SessionAdjustRow
                      onAdjust={handleAdjust}
                      canReduce={canReduce30}
                      testID="home-session-adjust"
                    />
                  </View>
                )}

                {/* What we're sharing with the circle while the session runs —
                    or the honest retraction when the circle emptied. */}
                <View style={styles.captureSection}>
                  {emptyCircleCopy ? (
                    <Text style={styles.emptyCircleText}>
                      {emptyCircleCopy}
                    </Text>
                  ) : (
                    <>
                      <Text style={styles.captureLabel}>
                        {homeOverdue || isSOSSession
                          ? 'Sharing with your Circle'
                          : 'Monitoring'}
                      </Text>
                      <View style={styles.captureChips}>
                        {(isSOSSession
                          ? activeSession.last_known_latitude != null
                          : activeSession.location_sharing_enabled) && (
                          <View style={styles.captureChip}>
                            <Ionicons
                              name="location"
                              size={16}
                              color={COLORS.primary}
                            />
                          </View>
                        )}
                        <View style={styles.captureChip}>
                          <Ionicons
                            name="battery-half"
                            size={16}
                            color={COLORS.primary}
                          />
                        </View>
                      </View>
                    </>
                  )}
                </View>

                <View style={styles.sessionActions}>
                  <Button
                    title="I'm Safe"
                    onPress={() => {
                      void handleAlarmImSafe()
                    }}
                    variant="primary"
                    size="large"
                    fullWidth
                  />
                </View>
              </TouchableOpacity>
            ) : !circleOfTrust ||
              circleOfTrust.filter(m => m.status === 'active').length === 0 ? (
              // NO CIRCLE OF TRUST STATE
              <>
                <View style={styles.emptyStateIcon}>
                  <View style={styles.iconCircleBackground}>
                    <TrustCircleIcon
                      size={32}
                      color={COLORS.primary}
                      focused={false}
                    />
                  </View>
                </View>

                <Text style={styles.emptyTitle}>
                  Build your Circle of Trust
                </Text>
                <Text style={styles.emptySubtitle}>
                  Add friends and family who'll be notified if your sessions
                  expire
                </Text>

                <Button
                  title="Set Up Circle"
                  onPress={() => router.push('/(tabs)/circle')}
                  variant="primary"
                  fullWidth
                  size="large"
                  icon="add-circle"
                  iconPosition="left"
                />
              </>
            ) : (
              // START SESSION STATE (has Circle of Trust members)
              <>
                <View style={styles.emptyStateIcon}>
                  <LinearGradient
                    colors={COLORS.gradients.primary}
                    style={styles.iconGradient}
                  >
                    <Ionicons name="navigate" size={32} color={COLORS.white} />
                  </LinearGradient>
                </View>

                <Text style={styles.emptyTitle}>
                  Ready for your next journey?
                </Text>
                <Text style={styles.emptySubtitle}>
                  Start a session to let your loved ones know you're safe
                </Text>

                <Button
                  title="Start Session"
                  onPress={() => {
                    if (subscriptionStatus && !subscriptionStatus.has_access) {
                      router.push('/plans')
                    } else {
                      router.push('/sessions/new')
                    }
                  }}
                  variant="primary"
                  fullWidth
                  size="large"
                  emoji="📍"
                  iconPosition="left"
                />
              </>
            )}
          </Card>

          {/* Safety Tips - Separate Card */}
          <Card variant="glass" style={styles.tipsCard}>
            <View style={styles.tipsHeader}>
              <Ionicons name="bulb" size={20} color={COLORS.warning} />
              <Text style={styles.tipsTitle}>Safety Tip</Text>
            </View>
            <Text style={styles.tipsText}>{safetyTip}</Text>
          </Card>
        </ScrollView>
      </LinearGradient>

      {/* Session creation now uses full page navigation */}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  gradient: {
    flex: 1,
  },
  scrollContent: {
    paddingTop: SPACING.xl,
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING['2xl'],
  },

  // Header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: SPACING.xl,
  },
  greeting: {
    fontSize: TYPOGRAPHY.fontSize['3xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },

  // Main Card
  mainCard: {
    marginBottom: SPACING.lg,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.md,
  },
  cardTitle: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  // Let the title take the remaining row width (and truncate) so the live
  // badge always stays inside the card instead of pushing off the edge.
  cardTitleFlex: {
    flex: 1,
  },
  // Compact "live" chip beside the title — a pulsing dot + label, sized so it
  // never crowds the title into an ellipsis on narrow screens.
  // Big live countdown; red inside the final 5 minutes / once overdue.
  homeCountdown: {
    fontSize: 36,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
    fontVariant: ['tabular-nums'],
  },
  homeCountdownUrgent: {
    color: COLORS.danger,
  },
  // Server-truth escalation title replaces the countdown once the session
  // escalates (shared LIVE_STATUS_COPY table via homePillStatusTitle).
  homeStatusTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.danger,
    textAlign: 'center',
    marginVertical: SPACING.md,
  },
  etaText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    textAlign: 'center',
    marginTop: 2,
  },
  homeAdjustWrap: {
    marginTop: SPACING.sm,
    marginBottom: SPACING.md,
  },
  captureSection: {
    marginBottom: SPACING.lg,
  },
  captureLabel: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    marginBottom: SPACING.sm,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  captureChips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: SPACING.sm,
  },
  captureChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 6,
    borderRadius: RADIUS.full,
    backgroundColor: COLORS.glass.teal,
  },
  // "I'm Safe" is the full-width primary action; "Extend Time" sits below it,
  // content-sized and centered so it never dominates the card.
  sessionActions: {
    gap: SPACING.sm,
    alignItems: 'center',
  },
  // Empty State
  emptyStateIcon: {
    alignItems: 'center',
    marginBottom: SPACING.lg,
  },
  iconGradient: {
    width: 80,
    height: 80,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconCircleBackground: {
    width: 80,
    height: 80,
    borderRadius: RADIUS.full,
    backgroundColor: `${COLORS.primary}15`,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: `${COLORS.primary}30`,
  },
  emptyTitle: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.sm,
  },
  emptySubtitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    marginBottom: SPACING.xl,
    paddingHorizontal: SPACING.md,
  },

  // Tips Card
  tipsCard: {
    marginBottom: SPACING.xl,
    backgroundColor: COLORS.glass.white,
    borderWidth: 1,
    borderColor: COLORS.glass.blur,
  },
  tipsHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.sm,
  },
  tipsTitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  tipsText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    lineHeight: 20,
  },

  // Alarm State - matching design-refined.html alert card
  alarmCard: {
    borderLeftWidth: 4,
    borderLeftColor: COLORS.danger, // Red accent for alarm/danger
    borderWidth: 1,
    borderColor: `${COLORS.primary}33`, // 20% opacity of primary color
  },
  sosQueuedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    backgroundColor: COLORS.dangerLight,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
  },
  sosQueuedText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.danger,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
  },
  emptyCircleText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.danger,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
  },
})
