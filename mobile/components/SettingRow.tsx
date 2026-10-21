import React from 'react'
import { View, Text, Switch, TouchableOpacity, StyleSheet } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING } from '../constants'

interface SettingRowProps {
  label: string
  description?: string
  icon?: keyof typeof Ionicons.glyphMap
  // Toggle mode (when toggle=true)
  toggle?: boolean
  value?: boolean | string // boolean for switch, string for display
  onToggle?: (value: boolean) => void
  disabled?: boolean
  // Navigation mode
  onPress?: () => void
  showArrow?: boolean
  // Visual emphasis for destructive actions (e.g. "Delete account").
  // Tints the icon + label red so the row reads as dangerous in a
  // list of otherwise neutral settings.
  tint?: 'default' | 'danger'
}

export function SettingRow({
  label,
  description,
  icon,
  toggle = false,
  value,
  onToggle,
  disabled = false,
  onPress,
  showArrow = false,
  tint = 'default',
}: SettingRowProps) {
  const iconColor = tint === 'danger' ? COLORS.danger : COLORS.primary
  const labelColor = tint === 'danger' ? COLORS.danger : COLORS.text
  const content = (
    <View style={styles.settingRow}>
      <View style={styles.settingContent}>
        {icon && (
          <View style={styles.iconContainer}>
            <Ionicons name={icon} size={24} color={iconColor} />
          </View>
        )}
        <View style={styles.textContainer}>
          <Text style={[styles.settingLabel, { color: labelColor }]}>
            {label}
          </Text>
          {description && (
            <Text style={styles.settingDescription}>{description}</Text>
          )}
        </View>
      </View>
      {toggle ? (
        <Switch
          value={Boolean(value)}
          onValueChange={onToggle}
          trackColor={{ false: COLORS.gray, true: COLORS.primary }}
          thumbColor={COLORS.white}
          disabled={disabled}
        />
      ) : (
        <View style={styles.settingRight}>
          {typeof value === 'string' && (
            <Text style={styles.settingValue}>{value}</Text>
          )}
          {showArrow && (
            <Ionicons name="chevron-forward" size={20} color={COLORS.gray} />
          )}
        </View>
      )}
    </View>
  )

  if (onPress && !toggle) {
    return (
      <TouchableOpacity onPress={onPress} disabled={disabled}>
        {content}
      </TouchableOpacity>
    )
  }

  return content
}

const styles = StyleSheet.create({
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    borderTopWidth: 1,
    borderTopColor: COLORS.lightGray,
  },
  settingContent: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: SPACING.md,
  },
  iconContainer: {
    marginRight: SPACING.md,
  },
  textContainer: {
    flex: 1,
  },
  settingLabel: {
    fontSize: 16,
    color: COLORS.text,
    fontWeight: '500',
    marginBottom: 2,
  },
  settingDescription: {
    fontSize: 13,
    color: COLORS.textLight,
    lineHeight: 18,
  },
  settingRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  settingValue: {
    fontSize: 14,
    color: COLORS.textLight,
  },
})
