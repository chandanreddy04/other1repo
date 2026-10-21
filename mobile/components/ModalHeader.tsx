import React from 'react'
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, TYPOGRAPHY } from '../constants'

interface ModalHeaderProps {
  title: string
  onBack: () => void
  rightAction?: React.ReactNode
  /** Dismiss style: an X on the top RIGHT instead of a back arrow on the
   * left — for screens that overlay a flow rather than sit inside one. */
  close?: boolean
}

export function ModalHeader({
  title,
  onBack,
  rightAction,
  close = false,
}: ModalHeaderProps) {
  if (close) {
    return (
      <View style={styles.container}>
        <View style={styles.spacer} />
        <Text style={styles.title}>{title}</Text>
        <TouchableOpacity style={styles.backButton} onPress={onBack}>
          <Ionicons name="close" size={26} color={COLORS.text} />
        </TouchableOpacity>
      </View>
    )
  }
  return (
    <View style={styles.container}>
      <TouchableOpacity style={styles.backButton} onPress={onBack}>
        <Ionicons name="arrow-back" size={24} color={COLORS.text} />
      </TouchableOpacity>
      <Text style={styles.title}>{title}</Text>
      {rightAction || <View style={styles.spacer} />}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    backgroundColor: COLORS.white,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },
  backButton: {
    padding: SPACING.xs,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  spacer: {
    width: 32,
  },
})
