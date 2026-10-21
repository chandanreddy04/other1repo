/**
 * Shared "Session Details" card shell for app/sessions/[id].tsx — a title,
 * a server-truth subtitle (present vs past tense by mode), and whatever
 * info rows / map / photo the caller composes as children. One shell keeps
 * the live and ended modes from drifting in layout.
 *
 * Related: app/sessions/[id].tsx, components/session/OutfitPhotoCard.tsx.
 */
import type { ReactNode } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../../constants'

interface SessionDetailsCardProps {
  subtitle: string
  /** Retracted-sharing-promise copy (empty circle) renders in danger red. */
  subtitleDanger?: boolean
  children: ReactNode
}

export function SessionDetailsCard({
  subtitle,
  subtitleDanger = false,
  children,
}: SessionDetailsCardProps) {
  return (
    <View style={styles.detailsCard}>
      <Text style={styles.sectionTitle}>Session Details</Text>
      <Text
        style={[styles.sectionSubtitle, subtitleDanger && styles.subtitleDanger]}
      >
        {subtitle}
      </Text>
      {children}
    </View>
  )
}

interface SessionInfoRowProps {
  icon: keyof typeof Ionicons.glyphMap
  iconColor?: string
  label: string
  value: string
}

/** One "icon + label + value" row — destination, battery, planned return. */
export function SessionInfoRow({
  icon,
  iconColor = COLORS.primary,
  label,
  value,
}: SessionInfoRowProps) {
  return (
    <View style={styles.infoRow}>
      <Ionicons name={icon} size={20} color={iconColor} />
      <View style={styles.infoRowText}>
        <Text style={styles.infoLabel}>{label}</Text>
        <Text style={styles.infoValue}>{value}</Text>
      </View>
    </View>
  )
}

/** A labeled block below the info rows — location map, outfit photo. */
export function SessionDetailsBlock({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <View style={styles.detailsBlock}>
      <Text style={styles.infoLabel}>{label}</Text>
      {children}
    </View>
  )
}

const styles = StyleSheet.create({
  detailsCard: {
    backgroundColor: COLORS.white,
    padding: 20,
    borderRadius: 12,
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: COLORS.text,
    marginBottom: 10,
  },
  sectionSubtitle: {
    fontSize: 14,
    color: COLORS.textLight,
    marginTop: -4,
    marginBottom: 8,
  },
  subtitleDanger: {
    color: COLORS.danger,
    fontWeight: '500',
  },
  detailsBlock: {
    paddingVertical: 8,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingVertical: 8,
  },
  infoRowText: {
    flex: 1,
  },
  infoLabel: {
    fontSize: 14,
    color: COLORS.textLight,
    marginBottom: 2,
  },
  infoValue: {
    fontSize: 16,
    color: COLORS.text,
    fontWeight: '500',
  },
})
