import React from 'react'
import { View, Text, StyleSheet } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, TYPOGRAPHY, SPACING, RADIUS, SHADOWS } from '../../constants'
import { BaseToastProps } from 'react-native-toast-message'

const TOAST_TYPES = {
  success: {
    icon: 'checkmark-circle' as const,
    color: COLORS.accent.green,
    backgroundColor: '#F0FDF4',
    borderColor: '#BBF7D0',
  },
  error: {
    icon: 'alert-circle' as const,
    color: COLORS.danger,
    backgroundColor: '#FEF2F2',
    borderColor: '#FECACA',
  },
  info: {
    icon: 'information-circle' as const,
    color: COLORS.accent.blue,
    backgroundColor: '#EFF6FF',
    borderColor: '#BFDBFE',
  },
}

function ToastBody({
  text1,
  text2,
  type,
}: BaseToastProps & { type: keyof typeof TOAST_TYPES }) {
  const config = TOAST_TYPES[type]

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: config.backgroundColor,
          borderColor: config.borderColor,
        },
      ]}
    >
      <Ionicons name={config.icon} size={22} color={config.color} />
      <View style={styles.textContainer}>
        {text1 ? (
          <Text style={styles.title} numberOfLines={2}>
            {text1}
          </Text>
        ) : null}
        {text2 ? (
          <Text style={styles.detail} numberOfLines={2}>
            {text2}
          </Text>
        ) : null}
      </View>
    </View>
  )
}

export const toastConfig = {
  success: (props: BaseToastProps) => <ToastBody {...props} type="success" />,
  error: (props: BaseToastProps) => <ToastBody {...props} type="error" />,
  info: (props: BaseToastProps) => <ToastBody {...props} type="info" />,
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginHorizontal: SPACING.lg,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm + 2,
    borderRadius: RADIUS.full,
    borderWidth: 1,
    ...SHADOWS.md,
  },
  textContainer: {
    flex: 1,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  detail: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    marginTop: 1,
  },
})
