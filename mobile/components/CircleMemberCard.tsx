import React from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  Alert,
  Linking,
} from 'react-native'
import type { AlertButton } from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../constants'
import { getInitial } from '../utils/initials'
import { getCircleMemberDisplayName } from '../utils/circleMemberName'
import { ExtendedCircleOfTrustMember } from '../store/useCircleStore'
import { useAppConfig } from '../store/useAppConfigStore'
import { formatPhoneNumber } from '../utils/validation'

interface CircleMemberCardProps {
  member: ExtendedCircleOfTrustMember
  onRemove: (memberId: string) => void
  onNudge?: (member: ExtendedCircleOfTrustMember) => void
}

export const CircleMemberCard: React.FC<CircleMemberCardProps> = ({
  member,
  onRemove,
  onNudge,
}) => {
  const smsNumber = useAppConfig().smsNumber
  const name = getCircleMemberDisplayName(member)
  const handleRemove = () => {
    Alert.alert(
      'Remove from Circle',
      `Are you sure you want to remove ${name} from your Circle of Trust?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => onRemove(member.id),
        },
      ]
    )
  }

  const handleOptedOutTap = () => {
    // Cross-platform action sheet via Alert.alert. The "Text them"
    // path is only useful when SMS_NUMBER is set — without it, the
    // owner can't tell the contact what to text START to, so we skip
    // that button entirely rather than ship a broken prefill.
    const phone = member.contact_phone_number ?? member.contact_phone
    const canText = Boolean(smsNumber && phone)
    const body = smsNumber
      ? `${name} asked us to stop texting them. Until they reply START to ${smsNumber}, we can't reach them as your Circle member.`
      : `${name} asked us to stop texting them, so we can't reach them as your Circle member.`

    const buttons: AlertButton[] = []
    if (canText) {
      buttons.push({
        text: `Text ${name}`,
        onPress: () => {
          const prefill = `Hey, can you text START to ${smsNumber}? I'd like to keep you in my Circle of Trust on Made It Home.`
          Linking.openURL(
            `sms:${phone}?body=${encodeURIComponent(prefill)}`
          )
        },
      })
    }
    buttons.push({
      text: 'Remove from your list',
      style: 'destructive',
      onPress: () => {
        Alert.alert(
          `Remove ${name}?`,
          "You'll need to add them again if they opt back in.",
          [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Remove',
              style: 'destructive',
              onPress: () => onRemove(member.id),
            },
          ]
        )
      },
    })
    buttons.push({ text: 'Cancel', style: 'cancel' })

    Alert.alert(`${name} opted out`, body, buttons)
  }

  const getStatusIcon = (): {
    name: keyof typeof Ionicons.glyphMap
    color: string
  } => {
    switch (member.status) {
      case 'active':
        return { name: 'checkmark-circle', color: COLORS.accent.green }
      case 'pending':
        return { name: 'time', color: COLORS.accent.orange }
      case 'blocked':
        return { name: 'close-circle', color: COLORS.danger }
      case 'opted_out':
        return { name: 'ban', color: COLORS.textLight }
      default:
        return { name: 'help-circle', color: COLORS.textLight }
    }
  }

  const statusIcon = getStatusIcon()

  // Format phone number for display if available
  const formattedPhone = member.contact_phone_number
    ? formatPhoneNumber(member.contact_phone_number)
    : null

  const displayInfo =
    formattedPhone || member.contact_email || 'No contact info'

  const isOptedOut = member.status === 'opted_out'

  const statusLabel =
    member.status === 'pending'
      ? 'Invited'
      : member.status === 'opted_out'
        ? 'Opted out of our texts'
        : member.status.charAt(0).toUpperCase() + member.status.slice(1)

  const body = (
    <View style={[styles.container, isOptedOut && styles.containerFaded]}>
        <View style={styles.content}>
        {/* Header */}
        <View style={styles.header}>
          {/* Avatar */}
          <View style={styles.avatarContainer}>
            {member.phone_contact?.image?.uri ? (
              <Image
                source={{ uri: member.phone_contact.image.uri }}
                style={styles.avatar}
              />
            ) : (
              <LinearGradient
                colors={[COLORS.primaryLight, COLORS.primary]}
                style={styles.avatarFallback}
              >
                <Text style={styles.avatarText}>
                  {getInitial(name)}
                </Text>
              </LinearGradient>
            )}

          </View>

          {/* Contact Info */}
          <View style={styles.contactInfo}>
            <Text style={styles.contactName} numberOfLines={1}>
              {name}
            </Text>
            <Text style={styles.contactDetail} numberOfLines={1}>
              {displayInfo}
            </Text>
            <View style={styles.statusRow}>
              <Ionicons
                name={statusIcon.name}
                size={14}
                color={statusIcon.color}
              />
              <Text style={[styles.status, { color: statusIcon.color }]}>
                {statusLabel}
              </Text>
            </View>
            {isOptedOut ? (
              <Text style={styles.optedOutCaption}>
                They can reply START to {smsNumber || 'our number'} to
                be eligible to be a Circle member again.
              </Text>
            ) : null}
          </View>

          {/* Delete button — hidden for opted-out (tap row instead) */}
          {!isOptedOut ? (
            <TouchableOpacity style={styles.deleteButton} onPress={handleRemove}>
              <Ionicons name="trash-outline" size={20} color={COLORS.danger} />
            </TouchableOpacity>
          ) : null}
        </View>

        {/* Action Buttons for Pending Members */}
        {member.status === 'pending' && onNudge && (
          <View style={styles.pendingActions}>
            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => onNudge(member)}
            >
              <Ionicons
                name="notifications-outline"
                size={16}
                color={COLORS.primary}
              />
              <Text style={styles.actionText}>Remind</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
      </View>
  )

  return isOptedOut ? (
    <TouchableOpacity onPress={handleOptedOutTap} activeOpacity={0.7}>
      {body}
    </TouchableOpacity>
  ) : (
    body
  )
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: SPACING.lg,
    marginVertical: SPACING.sm,
    backgroundColor: COLORS.white,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: 'rgba(20, 184, 166, 0.2)',
    ...SHADOWS.md,
  },
  containerFaded: {
    opacity: 0.55,
    borderColor: COLORS.lightGray,
  },
  optedOutCaption: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    marginTop: SPACING.xs,
    lineHeight: 16,
  },

  content: {
    padding: SPACING.lg,
  },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
  },

  avatarContainer: {
    position: 'relative',
    marginRight: SPACING.md,
  },

  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
  },

  avatarFallback: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },

  avatarText: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.white,
  },

  contactInfo: {
    flex: 1,
  },

  contactName: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
    marginBottom: 4,
  },

  contactDetail: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    marginBottom: 4,
  },

  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.xs,
  },

  status: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
  },

  deleteButton: {
    padding: SPACING.sm,
  },

  pendingActions: {
    flexDirection: 'row',
    marginTop: SPACING.md,
    paddingTop: SPACING.md,
    borderTopWidth: 1,
    borderTopColor: COLORS.neutral[100],
    gap: SPACING.md,
  },

  actionButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.xs,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.glass.teal,
  },

  actionText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.primary,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
  },
})
