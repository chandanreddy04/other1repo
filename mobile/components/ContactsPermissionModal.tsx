import React from 'react'
import { View, Text, StyleSheet, Modal, TouchableOpacity } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../constants'
import { Button } from './ui'

interface ContactsPermissionModalProps {
  visible: boolean
  onRequestPermission: () => void
  onSkip: () => void
  onClose: () => void
  isLoading?: boolean
  description?: string
  items?: string[]
}

const DEFAULT_DESCRIPTION = 'Let us access your contacts to build your Circle of Trust.'
const DEFAULT_ITEMS = [
  'Receive an invite to join your Circle of Trust',
  'Only be contacted if you send an SOS or your timer expires',
]

export const ContactsPermissionModal: React.FC<
  ContactsPermissionModalProps
> = ({
  visible,
  onRequestPermission,
  onSkip: _onSkip,
  onClose,
  isLoading = false,
  description = DEFAULT_DESCRIPTION,
  items = DEFAULT_ITEMS,
}) => {
  return (
    <Modal
      visible={visible}
      animationType="fade"
      transparent
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        <View style={styles.container}>
          {/* Close button */}
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Ionicons name="close" size={24} color={COLORS.text} />
          </TouchableOpacity>

          {/* Content */}
          <View style={styles.content}>
            <Text style={styles.title}>Allow Contacts Access</Text>
            <Text style={styles.description}>{description}</Text>
            <Text style={styles.privacyTitle}>Your selected contact will:</Text>
            {items.map((item, i) => (
              <View key={i} style={styles.privacyItem}>
                <Ionicons
                  name="checkmark-circle"
                  size={20}
                  color={COLORS.primary}
                  style={styles.privacyIcon}
                />
                <Text style={styles.privacyText}>{item}</Text>
              </View>
            ))}
          </View>

          {/* Actions */}
          <View style={styles.actions}>
            <Button
              title={isLoading ? 'Requesting...' : 'Allow'}
              onPress={onRequestPermission}
              disabled={isLoading}
              loading={isLoading}
              variant="primary"
              size="medium"
              fullWidth
            />
          </View>
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: SPACING.lg,
  },

  container: {
    width: '100%',
    maxWidth: 340,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    backgroundColor: COLORS.white,
    ...SHADOWS.lg,
    position: 'relative',
  },

  closeButton: {
    position: 'absolute',
    top: SPACING.md,
    right: SPACING.md,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: COLORS.glass.blur,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1,
  },

  content: {
    marginBottom: SPACING.lg,
    marginTop: SPACING.lg,
  },

  title: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
    marginBottom: SPACING.md,
    textAlign: 'center',
  },

  description: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    lineHeight: TYPOGRAPHY.lineHeight.relaxed * TYPOGRAPHY.fontSize.base,
    marginBottom: SPACING.sm,
  },

  privacyTitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    marginTop: SPACING.md,
    marginBottom: SPACING.sm,
  },

  privacyItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: SPACING.sm,
  },

  privacyIcon: {
    marginTop: 7, // Push icon down to align with text
    marginRight: SPACING.sm,
  },

  privacyText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    lineHeight: TYPOGRAPHY.lineHeight.normal * TYPOGRAPHY.fontSize.base,
  },

  actions: {
    width: '100%',
  },
})
