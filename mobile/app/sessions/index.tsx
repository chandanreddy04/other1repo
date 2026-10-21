/**
 * Sessions — a scannable list of the owner's sessions, live and past.
 *
 * Each row shows the title, when the session ended ("Ended <date> · <time>"
 * from getSessionEnd — mark-safe or admin-cancel time; ongoing sessions show
 * "Started …" instead), and a one-word data state ("Data deletion pending" /
 * "Data deleted", from isDataHeld). Every row — live or ended — opens the
 * same resource at /sessions/{id}, which renders the right mode itself
 * (owner decision, Commit 12: no special-casing a live row here).
 *
 * Related: app/sessions/[id].tsx, utils/retention.ts.
 */

import { useEffect } from 'react'
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  SafeAreaView,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, RADIUS, SPACING, TYPOGRAPHY } from '../../constants'
import { useSessionStore } from '../../store/useSessionStore'
import { ModalHeader } from '../../components/ModalHeader'
import { formatDate, formatTime } from '../../utils/dateFormatting'
import { getSessionEnd, isDataHeld } from '../../utils/retention'
import type { Session } from '../../types'

export default function SessionsScreen() {
  const router = useRouter()
  const sessions = useSessionStore(state => state.sessions)
  const loadSessions = useSessionStore(state => state.loadSessions)

  useEffect(() => {
    void loadSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const renderItem = ({ item }: { item: Session }) => {
    // A genuine end time exists only for COMPLETED (mark-safe) and CANCELLED
    // (admin close) sessions; ACTIVE / unresolved MISSED / ALERTED are still
    // ongoing, so we anchor those to the start instead of claiming "Ended".
    const end = getSessionEnd(item)

    return (
      <TouchableOpacity
        style={styles.card}
        activeOpacity={0.85}
        onPress={() => router.push(`/sessions/${item.id}`)}
      >
        <Text style={styles.destination} numberOfLines={1}>
          {item.session_type === 'sos'
            ? 'Emergency SOS'
            : item.destination || 'Check-in'}
        </Text>
        <Text style={styles.meta}>
          {end
            ? `Ended ${formatDate(end)} · ${formatTime(end)}`
            : `Started ${formatDate(item.created_at)} · ${formatTime(item.created_at)}`}
        </Text>
        {end && (
          <Text style={styles.dataState}>
            {isDataHeld(item) ? 'Data deletion pending' : 'Data deleted'}
          </Text>
        )}
      </TouchableOpacity>
    )
  }

  return (
    <>
      <SafeAreaView style={styles.container}>
        <ModalHeader title="Session History" onBack={() => router.back()} />
        <FlatList
          data={sessions}
          keyExtractor={item => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="time-outline" size={64} color={COLORS.primary} />
              <Text style={styles.emptyTitle}>No sessions yet</Text>
              <Text style={styles.emptyText}>
                Your past check-ins and SOS sessions will show up here.
              </Text>
            </View>
          }
        />
      </SafeAreaView>
    </>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  listContent: {
    padding: SPACING.lg,
    gap: SPACING.md,
  },
  card: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
  },
  destination: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  meta: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    marginTop: 2,
  },
  dataState: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    marginTop: SPACING.xs,
  },
  emptyState: {
    alignItems: 'center',
    paddingTop: SPACING['3xl'],
    gap: SPACING.sm,
  },
  emptyTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  emptyText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    textAlign: 'center',
  },
})
