import React from 'react'
import {
  TouchableOpacity,
  Text,
  StyleSheet,
  ViewStyle,
  TextStyle,
  ActivityIndicator,
  View,
} from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, TYPOGRAPHY, SPACING } from '../../constants'

type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'success'
  | 'danger'
  | 'ghost'
  | 'glass'
type ButtonSize = 'small' | 'medium' | 'large'

interface ButtonProps {
  onPress: () => void
  title: string
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: keyof typeof Ionicons.glyphMap
  iconPosition?: 'left' | 'right'
  disabled?: boolean
  loading?: boolean
  fullWidth?: boolean
  style?: ViewStyle
  textStyle?: TextStyle
  emoji?: string
}

export const Button: React.FC<ButtonProps> = ({
  onPress,
  title,
  variant = 'primary',
  size = 'medium',
  icon,
  iconPosition = 'left',
  disabled = false,
  loading = false,
  fullWidth = false,
  style,
  textStyle,
  emoji,
}) => {
  const getGradientColors = () => {
    switch (variant) {
      case 'primary':
        return COLORS.gradients.primary
      case 'secondary':
        return COLORS.gradients.secondary
      case 'success':
        return COLORS.gradients.success
      case 'danger':
        return COLORS.gradients.danger
      case 'glass':
        return COLORS.gradients.glass
      default:
        return [COLORS.white, COLORS.white] as const
    }
  }

  const buttonStyles = [
    styles.base,
    styles[size],
    fullWidth && styles.fullWidth,
    (disabled || loading) && styles.disabled,
    variant === 'ghost' && styles.ghost,
    style,
  ]

  const textStyles = [
    styles.text,
    styles[`text_${size}`],
    variant === 'ghost' && styles.ghostText,
    variant === 'danger' && styles.dangerText,
    textStyle,
  ]

  const iconSize = size === 'small' ? 16 : size === 'large' ? 22 : 18
  const iconColor =
    variant === 'ghost'
      ? COLORS.primary
      : variant === 'danger'
        ? COLORS.text
        : COLORS.white

  const renderContent = () => {
    if (loading) {
      return (
        <ActivityIndicator
          size="small"
          color={
            variant === 'ghost'
              ? COLORS.primary
              : variant === 'danger'
                ? COLORS.text
                : COLORS.white
          }
        />
      )
    }

    return (
      <View style={styles.contentContainer}>
        {emoji && iconPosition === 'left' && (
          <Text style={[styles.emoji, styles[`emoji_${size}`]]}>{emoji}</Text>
        )}
        {icon && iconPosition === 'left' && (
          <Ionicons
            name={icon}
            size={iconSize}
            color={iconColor}
            style={styles.iconLeft}
          />
        )}
        <Text style={textStyles}>{title}</Text>
        {icon && iconPosition === 'right' && (
          <Ionicons
            name={icon}
            size={iconSize}
            color={iconColor}
            style={styles.iconRight}
          />
        )}
        {emoji && iconPosition === 'right' && (
          <Text style={[styles.emoji, styles[`emoji_${size}`]]}>{emoji}</Text>
        )}
      </View>
    )
  }

  if (variant === 'ghost') {
    return (
      <TouchableOpacity
        style={buttonStyles}
        onPress={onPress}
        disabled={disabled || loading}
        activeOpacity={0.7}
      >
        {renderContent()}
      </TouchableOpacity>
    )
  }

  return (
    <TouchableOpacity
      style={buttonStyles}
      onPress={onPress}
      disabled={disabled || loading}
      activeOpacity={0.95}
    >
      <LinearGradient
        colors={getGradientColors()}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[
          styles.gradient,
          styles[`gradient_${size}`],
          variant === 'primary' && styles.primaryShadow,
          variant === 'secondary' && styles.secondaryShadow,
          variant === 'success' && styles.successShadow,
          variant === 'danger' && styles.dangerShadow,
        ]}
      >
        {renderContent()}
      </LinearGradient>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  base: {
    borderRadius: 100,
    overflow: 'hidden',
  },

  contentContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },

  gradient: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },

  // Size variations
  small: {
    minHeight: 36,
  },
  medium: {
    minHeight: 48,
  },
  large: {
    minHeight: 56,
  },

  gradient_small: {
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  gradient_medium: {
    paddingHorizontal: 36,
    paddingVertical: 16,
  },
  gradient_large: {
    paddingHorizontal: 40,
    paddingVertical: 18,
  },

  // Ghost variant
  ghost: {
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: COLORS.primary,
    paddingHorizontal: 36,
    paddingVertical: 16,
  },

  ghostText: {
    color: COLORS.primary,
  },

  // States
  disabled: {
    opacity: 0.5,
  },

  fullWidth: {
    width: '100%',
  },

  // Text styles
  text: {
    fontWeight: '700',
    color: COLORS.white,
    letterSpacing: 0.5,
  },

  text_small: {
    fontSize: TYPOGRAPHY.fontSize.sm,
  },
  text_medium: {
    fontSize: TYPOGRAPHY.fontSize.base,
  },
  text_large: {
    fontSize: TYPOGRAPHY.fontSize.lg,
  },

  dangerText: {
    color: COLORS.text,
  },

  iconLeft: {
    marginRight: SPACING.sm,
  },
  iconRight: {
    marginLeft: SPACING.sm,
  },

  emoji: {
    marginHorizontal: SPACING.xs,
  },
  emoji_small: {
    fontSize: 16,
  },
  emoji_medium: {
    fontSize: 18,
  },
  emoji_large: {
    fontSize: 22,
  },

  // Shadow styles for gradient buttons
  primaryShadow: {
    shadowColor: COLORS.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 15,
    elevation: 8,
  },
  secondaryShadow: {
    shadowColor: COLORS.secondary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 15,
    elevation: 8,
  },
  successShadow: {
    shadowColor: COLORS.success,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 15,
    elevation: 8,
  },
  dangerShadow: {
    shadowColor: COLORS.danger,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 15,
    elevation: 8,
  },
})
