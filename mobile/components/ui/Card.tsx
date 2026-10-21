import React from 'react'
import {
  View,
  StyleSheet,
  ViewStyle,
  TouchableOpacity,
  StyleProp,
} from 'react-native'
import { COLORS, SPACING, SHADOWS } from '../../constants'

type CardElevation = 'none' | 'sm' | 'md' | 'lg' | 'xl'
type CardVariant = 'default' | 'glass' | 'bordered'

interface CardProps {
  children: React.ReactNode
  elevation?: CardElevation
  variant?: CardVariant
  padding?: 'none' | 'sm' | 'md' | 'lg'
  margin?: 'none' | 'sm' | 'md' | 'lg'
  onPress?: () => void
  style?: StyleProp<ViewStyle>
  backgroundColor?: string
  borderColor?: string
  borderWidth?: number
}

export const Card: React.FC<CardProps> = ({
  children,
  elevation = 'md',
  variant = 'default',
  padding = 'lg',
  margin = 'none',
  onPress,
  style,
  backgroundColor,
  borderColor,
  borderWidth,
}) => {
  const getBackgroundColor = () => {
    if (backgroundColor) return backgroundColor
    if (variant === 'glass') return 'rgba(255, 255, 255, 0.9)'
    return COLORS.white
  }

  const getBorderColor = () => {
    if (borderColor) return borderColor
    if (variant === 'glass') return 'rgba(255, 255, 255, 0.3)'
    // All cards have the teal border by default per design
    return 'rgba(20, 184, 166, 0.2)'
  }

  const getBorderWidth = () => {
    if (borderWidth !== undefined) return borderWidth
    // All cards have 1px border per design
    return 1
  }

  const getCardShadow = () => {
    if (elevation === 'none') return {}
    if (elevation === 'md') {
      // Match design-refined.html exactly
      return {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.08,
        shadowRadius: 20,
        elevation: 3,
      }
    }
    return SHADOWS[elevation]
  }

  const cardStyles = [
    styles.base,
    elevation !== 'none' && getCardShadow(),
    styles[`padding_${padding}`],
    styles[`margin_${margin}`],
    variant === 'glass' && styles.glass,
    {
      backgroundColor: getBackgroundColor(),
      borderColor: getBorderColor(),
      borderWidth: getBorderWidth(),
    },
    style,
  ]

  if (onPress) {
    return (
      <TouchableOpacity
        style={cardStyles}
        onPress={onPress}
        activeOpacity={0.98}
      >
        {children}
      </TouchableOpacity>
    )
  }

  return <View style={cardStyles}>{children}</View>
}

const styles = StyleSheet.create({
  base: {
    borderRadius: 24,
    overflow: 'hidden',
  },

  glass: {
    // Glass morphism effect with translucent background
    opacity: 0.95,
  },

  // Padding variants - matching design specs
  padding_none: {
    padding: 0,
  },
  padding_sm: {
    padding: SPACING.sm,
  },
  padding_md: {
    padding: SPACING.md,
  },
  padding_lg: {
    padding: 24, // Match design-refined.html
  },

  // Margin variants
  margin_none: {
    margin: 0,
  },
  margin_sm: {
    marginVertical: SPACING.sm / 2,
    marginHorizontal: SPACING.sm,
  },
  margin_md: {
    marginVertical: SPACING.md / 2,
    marginHorizontal: SPACING.md,
  },
  margin_lg: {
    marginVertical: SPACING.lg / 2,
    marginHorizontal: SPACING.lg,
  },
})
