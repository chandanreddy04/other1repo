import React from 'react'
import { View, Text, StyleSheet, TouchableOpacity, Image } from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../constants'
import { getInitial } from '../utils/initials'
import { PhoneContact } from '../services/contacts'
import { formatPhoneNumber } from '../utils/validation'

interface ContactListItemProps {
  contact: PhoneContact
  onPress: () => void
  avatarSize?: number
  showEmail?: boolean
  showImage?: boolean
}

export const ContactListItem: React.FC<ContactListItemProps> = ({
  contact,
  onPress,
  avatarSize = 48,
  showEmail = false,
  showImage = true,
}) => {
  const primaryPhone = contact.phoneNumbers[0]
  const primaryEmail = contact.emails[0]
  const formattedPhone = primaryPhone ? formatPhoneNumber(primaryPhone) : null
  const avatarRadius = avatarSize / 2

  return (
    <TouchableOpacity
      style={styles.contactItem}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <View style={styles.contactContent}>
        {/* Avatar */}
        <View style={styles.avatarContainer}>
          {showImage && contact.image?.uri ? (
            <Image
              source={{ uri: contact.image.uri }}
              style={[
                styles.avatarImage,
                {
                  width: avatarSize,
                  height: avatarSize,
                  borderRadius: avatarRadius,
                },
              ]}
            />
          ) : (
            <LinearGradient
              colors={[COLORS.primaryLight, COLORS.primary]}
              style={[
                styles.avatarFallback,
                {
                  width: avatarSize,
                  height: avatarSize,
                  borderRadius: avatarRadius,
                },
              ]}
            >
              <Text
                style={[
                  styles.avatarText,
                  avatarSize < 48 && styles.avatarTextSmall,
                ]}
              >
                {getInitial(contact.name)}
              </Text>
            </LinearGradient>
          )}
        </View>

        {/* Contact Info */}
        <View style={styles.contactInfo}>
          <Text style={styles.contactName} numberOfLines={1}>
            {contact.name}
          </Text>
          {formattedPhone && (
            <Text style={styles.contactPhone} numberOfLines={1}>
              {formattedPhone}
            </Text>
          )}
          {showEmail && primaryEmail && (
            <Text style={styles.contactEmail} numberOfLines={1}>
              {primaryEmail}
            </Text>
          )}
        </View>

        {/* Chevron */}
        <View style={styles.chevronContainer}>
          <Ionicons name="chevron-forward" size={20} color={COLORS.textLight} />
        </View>
      </View>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  contactItem: {
    backgroundColor: COLORS.white,
    marginHorizontal: SPACING.lg,
    marginVertical: SPACING.xs,
    borderRadius: RADIUS.lg,
    ...SHADOWS.sm,
  },

  contactContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
  },

  avatarContainer: {
    marginRight: SPACING.md,
  },

  avatarImage: {
    // width, height, borderRadius set dynamically
  },

  avatarFallback: {
    justifyContent: 'center',
    alignItems: 'center',
    // width, height, borderRadius set dynamically
  },

  avatarText: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.white,
  },

  avatarTextSmall: {
    fontSize: TYPOGRAPHY.fontSize.base,
  },

  contactInfo: {
    flex: 1,
  },

  contactName: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
    marginBottom: SPACING.xs,
  },

  contactPhone: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.primary,
    marginBottom: SPACING.xs,
  },

  contactEmail: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },

  chevronContainer: {
    marginLeft: SPACING.sm,
  },
})
