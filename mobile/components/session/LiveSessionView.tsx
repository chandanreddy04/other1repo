/**
 * Live-mode view for the merged session screen — what the old dedicated
 * live-check-in screen used to render: LIVE_STATUS_COPY heading, countdown →
 * overdue count-up, ±30m adjust, permission panel, overdue warning card,
 * sticky "I'm Safe", destination/battery rows, the live trail map, outfit photo.
 *
 * Presentational + action-callback only — the screen owns data loading,
 * the store subscription, and the escalation poll.
 *
 * Related: app/sessions/[id].tsx, components/session/EndedSessionView.tsx.
 */
import {
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { ModalHeader } from '../ModalHeader'
import { SessionAdjustRow } from '../SessionAdjustRow'
import { SessionTrailMap } from '../SessionTrailMap'
import { PermissionRequirements } from '../PermissionRequirements'
import { SessionClockCard } from './SessionClockCard'
import {
  SessionDetailsBlock,
  SessionDetailsCard,
  SessionInfoRow,
} from './SessionDetailsCard'
import { OutfitPhotoCard } from './OutfitPhotoCard'
import type { ExtendedCircleOfTrustMember } from '../../store/useCircleStore'
import type { RequirementItem } from '../../utils/permissionUi'
import type { TrailFix } from '../../hooks/useLocationTrail'
import { CHECKIN_CONFIG, COLORS } from '../../constants'
import {
  getBatteryColor,
  getBatteryIcon,
  hasBatteryReading,
} from '../../utils/battery'
import { formatHms, formatTime } from '../../utils/dateFormatting'
import { getSessionDeadline } from '../../utils/sessionTiming'
import { LIVE_STATUS_COPY } from '../../services/liveStatus'
import type { Session } from '../../types'

export interface LiveSessionViewProps {
  session: Session
  nowTick: number
  actionLoading: boolean
  onComplete: () => void
  onExtend: (minutes: number) => void
  onBack: () => void
  circleOfTrust: ExtendedCircleOfTrustMember[]
  circleLoaded: boolean
  permissionItems: RequirementItem[]
  onPermissionsChanged: () => void
  trailFixes: TrailFix[]
  trailLoading: boolean
}

export function LiveSessionView({
  session,
  nowTick,
  actionLoading,
  onComplete,
  onExtend,
  onBack,
  circleOfTrust,
  circleLoaded,
  permissionItems,
  onPermissionsChanged,
  trailFixes,
  trailLoading,
}: LiveSessionViewProps) {
  // Server truth only: the client clock saying "time's up" does NOT mean
  // the circle knows — dispatch happens after a grace window, server-side.
  const circleNotified = session.status === 'alerted'
  const notifyingCircle = session.status === 'missed'
  const alertAcknowledged = session.alert_acknowledged ?? false
  const circleUnreachable = session.circle_unreachable ?? false
  const isSOSSession = session.session_type === 'sos'
  // Empty is only meaningful after a real load — never on the initial []
  // (e.g. a cold deep-link into this screen before the fetch resolves).
  const circleEmpty =
    circleLoaded && !circleOfTrust.some(m => m.status === 'active')
  const emptyCircleCopy =
    circleEmpty && session.status === 'active'
      ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.PRE_ALERT
      : circleEmpty && session.status === 'missed'
        ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.POST_DEADLINE
        : null
  const sessionDeadline = getSessionDeadline(session)
  const deadlineMs = sessionDeadline?.getTime() ?? 0
  const msRemaining = deadlineMs - nowTick
  const isOverdue = msRemaining <= 0
  const graceRemainingMin = Math.max(
    0,
    Math.ceil(
      (deadlineMs + CHECKIN_CONFIG.ALERT_GRACE_MINUTES * 60 * 1000 - nowTick) /
        60000
    )
  )
  const canReduce30 =
    msRemaining > (30 + CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES) * 60000
  const overdueHeading =
    circleNotified && alertAcknowledged
      ? LIVE_STATUS_COPY.acknowledged.title
      : circleNotified
        ? LIVE_STATUS_COPY.alerted.title
        : circleUnreachable
          ? LIVE_STATUS_COPY.unreachable.title
          : notifyingCircle
            ? LIVE_STATUS_COPY.missed.title
            : LIVE_STATUS_COPY.overdue.title

  return (
    <SafeAreaView style={styles.container}>
      <ModalHeader title="Session" onBack={onBack} />
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {isOverdue ? (
          <SessionClockCard
            borderColor={COLORS.danger}
            tinted
            icon="warning"
            iconColor={COLORS.danger}
            heading={overdueHeading}
            headingColor={COLORS.danger}
            bigText={`+${formatHms(-msRemaining)}`}
            bigTextColor={COLORS.danger}
            smallText={
              !isSOSSession && sessionDeadline
                ? `ETA ${formatTime(sessionDeadline)}`
                : undefined
            }
          >
            {!isSOSSession &&
              !circleNotified &&
              !notifyingCircle &&
              !circleUnreachable && (
                <SessionAdjustRow
                  onAdjust={onExtend}
                  canReduce={false}
                  hideReduce
                  disabled={actionLoading}
                  testID="grace-extend"
                />
              )}
          </SessionClockCard>
        ) : (
          <SessionClockCard
            borderColor={COLORS.primary}
            bigText={formatHms(msRemaining)}
            smallText={
              !isSOSSession && sessionDeadline
                ? `ETA ${formatTime(sessionDeadline)}`
                : undefined
            }
          >
            {!isSOSSession && !circleNotified && !notifyingCircle && (
              <SessionAdjustRow
                onAdjust={onExtend}
                canReduce={canReduce30}
                disabled={actionLoading}
                testID="session-adjust"
              />
            )}
          </SessionClockCard>
        )}

        <PermissionRequirements
          items={permissionItems}
          onChanged={onPermissionsChanged}
          testID="live-session-permission-requirements"
        />

        <SessionDetailsCard
          subtitle={
            emptyCircleCopy ??
            (isOverdue || isSOSSession
              ? 'Sharing with your Circle'
              : 'Shared with your Circle if you miss check-in')
          }
          subtitleDanger={!!emptyCircleCopy}
        >
          <SessionInfoRow
            icon="navigate-outline"
            label="Destination"
            value={session.location_name || session.destination || 'Unknown'}
          />

          {/* Battery is always captured (no permission, no toggle) — the row
              always shows, with an honest placeholder until the first
              reading lands. */}
          <SessionInfoRow
            icon={getBatteryIcon(
              session.last_battery_level,
              session.last_battery_state
            )}
            iconColor={getBatteryColor(session.last_battery_level)}
            label="Battery"
            value={
              hasBatteryReading(session.last_battery_level)
                ? `${Math.round(session.last_battery_level * 100)}%${
                    session.last_battery_state === 'charging'
                      ? ' (Charging)'
                      : ''
                  }`
                : 'No reading yet'
            }
          />

          {session.location_sharing_enabled && (
            <SessionDetailsBlock label="Location">
              <SessionTrailMap
                fixes={trailFixes}
                loading={trailLoading}
                testID="session-trail-map"
              />
            </SessionDetailsBlock>
          )}

          {session.outfit_photo_url && (
            <OutfitPhotoCard photoUrl={session.outfit_photo_url} />
          )}
        </SessionDetailsCard>

        {isOverdue && (
          <View style={styles.warningCard}>
            <Ionicons name="alert-circle" size={24} color={COLORS.danger} />
            <Text style={styles.warningText}>
              {circleNotified && alertAcknowledged
                ? LIVE_STATUS_COPY.acknowledged.subtitle
                : circleNotified
                  ? LIVE_STATUS_COPY.alerted.subtitle
                  : circleUnreachable && circleEmpty
                    ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.POST_DEADLINE
                    : circleUnreachable
                      ? LIVE_STATUS_COPY.unreachable.subtitle
                      : notifyingCircle
                        ? LIVE_STATUS_COPY.missed.subtitle
                        : circleEmpty
                          ? CHECKIN_CONFIG.EMPTY_CIRCLE_COPY.PRE_ALERT
                          : graceRemainingMin > 0
                            ? `Check in now, or your Circle will be alerted in about ${graceRemainingMin} min.`
                            : 'Check in now — your Circle is about to be alerted.'}
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Sticky footer: marking safe is the screen's one essential action —
          reachable without scrolling, at any content length. */}
      <View style={styles.footer}>
        <TouchableOpacity
          style={[styles.completeButton, actionLoading && styles.buttonDisabled]}
          onPress={onComplete}
          disabled={actionLoading}
        >
          <Text style={styles.completeButtonText}>
            {actionLoading ? 'Processing…' : "I'm Safe"}
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: 20,
  },
  footer: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 12,
    backgroundColor: COLORS.white,
    borderTopWidth: 1,
    borderTopColor: COLORS.lightGray,
  },
  completeButton: {
    backgroundColor: COLORS.primary,
    padding: 18,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  completeButtonText: {
    color: COLORS.white,
    fontSize: 18,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  warningCard: {
    backgroundColor: '#FFF5F5',
    padding: 15,
    borderRadius: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginTop: 20,
    borderWidth: 1,
    borderColor: COLORS.danger,
  },
  warningText: {
    flex: 1,
    color: COLORS.danger,
    fontSize: 14,
  },
})
