/**
 * Shared "clock card" shell for app/sessions/[id].tsx — one card with an
 * optional icon + heading, an optional big tabular-nums number, an optional
 * small caption, and an optional adjust-row slot below. Live mode uses it
 * for the countdown/overdue state; ended mode uses it for the outcome +
 * retention countdown. One shell means the two modes can't drift in shape,
 * only in the copy/colors/children they pass.
 *
 * Related: app/sessions/[id].tsx, components/SessionAdjustRow.tsx.
 */
import type { ReactNode } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../../constants'

interface SessionClockCardProps {
  /** Card border color — brand primary (counting down), danger (overdue),
   *  or neutral gray (ended, past-tense). */
  borderColor: string
  /** Tinted danger background, like the live screen's overdue card. */
  tinted?: boolean
  icon?: keyof typeof Ionicons.glyphMap
  iconColor?: string
  heading?: string
  headingColor?: string
  bigText?: string
  bigTextColor?: string
  smallText?: string
  /** Adjust-row slot (±30m live extend, ±7d retention adjust). */
  children?: ReactNode
  testID?: string
}

export function SessionClockCard({
  borderColor,
  tinted = false,
  icon,
  iconColor = COLORS.text,
  heading,
  headingColor = COLORS.text,
  bigText,
  bigTextColor = COLORS.text,
  smallText,
  children,
  testID,
}: SessionClockCardProps) {
  return (
    <View
      style={[
        styles.card,
        { borderColor, backgroundColor: tinted ? '#FFF5F5' : COLORS.white },
      ]}
      testID={testID}
    >
      {icon && <Ionicons name={icon} size={40} color={iconColor} />}
      {heading && (
        <Text style={[styles.heading, { color: headingColor }]}>
          {heading}
        </Text>
      )}
      {bigText && (
        <Text style={[styles.bigText, { color: bigTextColor }]}>
          {bigText}
        </Text>
      )}
      {smallText && <Text style={styles.smallText}>{smallText}</Text>}
      {children && <View style={styles.childrenWrap}>{children}</View>}
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    padding: 30,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 20,
    borderWidth: 2,
  },
  heading: {
    fontSize: 24,
    fontWeight: 'bold',
    marginTop: 10,
    textAlign: 'center',
  },
  bigText: {
    fontSize: 40,
    fontWeight: 'bold',
    fontVariant: ['tabular-nums'],
    marginTop: 6,
  },
  smallText: {
    fontSize: 14,
    color: COLORS.textLight,
    marginTop: 2,
  },
  childrenWrap: {
    marginTop: 12,
  },
})
