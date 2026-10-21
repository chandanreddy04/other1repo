import React from 'react'
import { View, Text, StyleSheet, ViewStyle } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, TYPOGRAPHY, SPACING, RADIUS } from '../../constants'

type IoniconsName = keyof typeof Ionicons.glyphMap

type StatusType =
  | 'safe'
  | 'active'
  | 'warning'
  | 'danger'
  | 'overdue'
  | 'completed'
  | 'cancelled'
type StatusSize = 'small' | 'medium' | 'large'

interface StatusIndicatorProps {
  status: StatusType
  label?: string
  size?: StatusSize
  showIcon?: boolean
  showBadge?: boolean
  pulse?: boolean
  style?: ViewStyle
}

const statusConfig: Record<
  StatusType,
  {
    color: string
    backgroundColor: string
    borderColor: string
    icon: IoniconsName
    label: string
  }
> = {
  safe: {
    color: '#0D9488',
    backgroundColor: 'rgba(20, 184, 166, 0.15)',
    borderColor: '#14B8A6',
    icon: 'checkmark-circle',
    label: 'Safe',
  },
  active: {
    color: '#0D9488',
    backgroundColor: 'rgba(20, 184, 166, 0.15)',
    borderColor: '#14B8A6',
    icon: 'radio-button-on',
    label: 'Active',
  },
  warning: {
    color: COLORS.text,
    backgroundColor: COLORS.warning,
    borderColor: COLORS.warningDark,
    icon: 'warning',
    label: 'Warning',
  },
  danger: {
    color: COLORS.text,
    backgroundColor: COLORS.danger,
    borderColor: COLORS.dangerDark,
    icon: 'alert-circle',
    label: 'Alert',
  },
  overdue: {
    color: COLORS.text,
    backgroundColor: COLORS.danger,
    borderColor: COLORS.dangerDark,
    icon: 'time',
    label: 'Overdue',
  },
  completed: {
    color: '#0D9488',
    backgroundColor: 'rgba(78, 205, 196, 0.15)',
    borderColor: '#4ECDC4',
    icon: 'checkmark',
    label: 'Completed',
  },
  cancelled: {
    color: COLORS.white,
    backgroundColor: COLORS.neutral[400],
    borderColor: COLORS.neutral[500],
    icon: 'close-circle',
    label: 'Cancelled',
  },
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({
  status,
  label,
  size = 'medium',
  showIcon = true,
  showBadge = false,
  pulse = false,
  style,
}) => {
  const config = statusConfig[status]
  const displayLabel = label || config.label

  const iconSize = size === 'small' ? 16 : size === 'large' ? 24 : 20
  const fontSize =
    size === 'small'
      ? TYPOGRAPHY.fontSize.xs
      : size === 'large'
        ? TYPOGRAPHY.fontSize.base
        : TYPOGRAPHY.fontSize.sm

  if (showBadge) {
    return (
      <View
        style={[
          styles.badge,
          {
            backgroundColor: config.backgroundColor,
            borderColor: config.borderColor,
            borderWidth: 2,
          },
          style,
        ]}
      >
        {showIcon && (
          <Ionicons name={config.icon} size={iconSize} color={config.color} />
        )}
        <Text style={[styles.badgeText, { color: config.color, fontSize }]}>
          {displayLabel}
        </Text>
        {pulse && status === 'active' && (
          <View style={[styles.pulse, { backgroundColor: config.color }]} />
        )}
      </View>
    )
  }

  return (
    <View style={[styles.container, style]}>
      <View
        style={[
          styles.dot,
          styles[`dot_${size}`],
          { backgroundColor: config.color },
        ]}
      >
        {pulse &&
          (status === 'active' ||
            status === 'warning' ||
            status === 'danger') && (
            <View
              style={[styles.pulseDot, { backgroundColor: config.color }]}
            />
          )}
      </View>
      {displayLabel && (
        <Text style={[styles.label, { fontSize, color: config.color }]}>
          {displayLabel}
        </Text>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    // Keep the badge compact so it fits beside a title without pushing off
    // the edge of its row (24 was wide enough to overflow the home card).
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 50,
    gap: 8,
    flexShrink: 0,
  },
  badgeText: {
    fontWeight: '700',
    fontSize: 14,
  },
  dot: {
    borderRadius: RADIUS.full,
    position: 'relative',
  },
  dot_small: {
    width: 8,
    height: 8,
  },
  dot_medium: {
    width: 10,
    height: 10,
  },
  dot_large: {
    width: 12,
    height: 12,
  },
  label: {
    fontWeight: TYPOGRAPHY.fontWeight.medium,
  },
  pulse: {
    position: 'absolute',
    top: -2,
    right: -2,
    width: 8,
    height: 8,
    borderRadius: RADIUS.full,
    opacity: 0.8,
  },
  pulseDot: {
    position: 'absolute',
    top: -5,
    left: -5,
    right: -5,
    bottom: -5,
    borderRadius: RADIUS.full,
    opacity: 0.3,
  },
})
