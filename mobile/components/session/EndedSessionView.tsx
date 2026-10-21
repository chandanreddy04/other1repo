/**
 * Ended-mode view for the merged session screen — what the old dedicated
 * past-session screen used to render: outcome heading, retention countdown
 * with ±7d, planned return, a static map while data is held, read-only
 * photo, purged state.
 *
 * Presentational + action-callback only — the screen owns data loading and
 * the retention-adjust API call.
 *
 * Related: app/sessions/[id].tsx, components/session/LiveSessionView.tsx,
 *          utils/retention.ts.
 */
import { useState } from 'react'
import { SafeAreaView, ScrollView, StyleSheet } from 'react-native'
import { ModalHeader } from '../ModalHeader'
import { SessionAdjustRow } from '../SessionAdjustRow'
import { SessionTrailMap } from '../SessionTrailMap'
import { SessionClockCard } from './SessionClockCard'
import {
  SessionDetailsBlock,
  SessionDetailsCard,
  SessionInfoRow,
} from './SessionDetailsCard'
import { OutfitPhotoCard } from './OutfitPhotoCard'
import type { TrailFix } from '../../hooks/useLocationTrail'
import { COLORS } from '../../constants'
import {
  getBatteryColor,
  getBatteryIcon,
  hasBatteryReading,
} from '../../utils/battery'
import { formatDate, formatTime } from '../../utils/dateFormatting'
import {
  canReduceRetention,
  formatDaysHours,
  getDisplayedDeletionDate,
} from '../../utils/retention'
import type { Session } from '../../types'

export interface EndedSessionViewProps {
  session: Session
  /** Data still exists server-side (utils/retention.isDataHeld) — the
   *  screen computes this once, shared with the useLocationTrail call. */
  dataHeld: boolean
  adjusting: boolean
  onAdjustRetention: (days: number) => void
  onBack: () => void
  trailFixes: TrailFix[]
  trailLoading: boolean
}

export function EndedSessionView({
  session,
  dataHeld,
  adjusting,
  onAdjustRetention,
  onBack,
  trailFixes,
  trailLoading,
}: EndedSessionViewProps) {
  const completed = session.status === 'completed'
  const deletionDate = getDisplayedDeletionDate(session)
  // A past-session countdown doesn't need a per-second tick like the live
  // clock — evaluated once per mount, inside the lazy initializer (not the
  // render body itself) so it stays a pure render.
  const [now] = useState(() => Date.now())
  const deletionMs = deletionDate ? deletionDate.getTime() - now : 0
  const canReduce = canReduceRetention(session)

  return (
    <SafeAreaView style={styles.container}>
      <ModalHeader title="Session" onBack={onBack} />
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <SessionClockCard
          borderColor={COLORS.lightGray}
          icon={completed ? 'checkmark-circle' : 'close-circle-outline'}
          iconColor={completed ? COLORS.accent.green : COLORS.textLight}
          heading={
            completed
              ? `Marked safe${
                  session.actual_return_time
                    ? ` at ${formatTime(session.actual_return_time)}`
                    : ''
                }`
              : 'Session Closed'
          }
          headingColor={completed ? COLORS.text : COLORS.textLight}
          bigText={
            dataHeld && deletionDate ? formatDaysHours(deletionMs) : undefined
          }
          smallText={
            deletionDate ? `Data deleted ${formatDate(deletionDate)}` : undefined
          }
        >
          {dataHeld && deletionDate && (
            <SessionAdjustRow
              onAdjust={onAdjustRetention}
              canReduce={canReduce}
              disabled={adjusting}
              step={7}
              unit="d"
              testID="retention-adjust"
            />
          )}
        </SessionClockCard>

        {/* What was gathered — past tense, from server truth. */}
        <SessionDetailsCard
          subtitle={
            session.was_alerted
              ? 'Was shared with your Circle'
              : 'Nothing was shared with your Circle'
          }
        >
          <SessionInfoRow
            icon="navigate-outline"
            label="Destination"
            value={session.location_name || session.destination || 'Unknown'}
          />

          <SessionInfoRow
            icon="time-outline"
            label="Planned return"
            value={`${formatDate(session.expected_return_time)} at ${formatTime(session.expected_return_time)}`}
          />

          {/* Battery derives from the trail rows — gone once purged, so the
              row only renders while a reading exists (no placeholder: there
              is nothing pending in the past tense). */}
          {hasBatteryReading(session.last_battery_level) && (
            <SessionInfoRow
              icon={getBatteryIcon(
                session.last_battery_level,
                session.last_battery_state
              )}
              iconColor={getBatteryColor(session.last_battery_level)}
              label="Last battery reading"
              value={`${Math.round(session.last_battery_level * 100)}%`}
            />
          )}

          {dataHeld && session.location_sharing_enabled && (
            <SessionDetailsBlock label="Location">
              <SessionTrailMap
                fixes={trailFixes}
                loading={trailLoading}
                live={false}
                testID="summary-trail-map"
              />
            </SessionDetailsBlock>
          )}

          {dataHeld && session.outfit_photo_url && (
            <OutfitPhotoCard photoUrl={session.outfit_photo_url} />
          )}
        </SessionDetailsCard>
      </ScrollView>
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
})
