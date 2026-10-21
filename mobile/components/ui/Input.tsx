import React, { useState } from 'react'
import {
  View,
  TextInput,
  Text,
  StyleSheet,
  TextInputProps,
  TouchableOpacity,
  StyleProp,
  ViewStyle,
  TextStyle,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, TYPOGRAPHY, SPACING } from '../../constants'

interface InputProps extends TextInputProps {
  label?: string
  error?: string
  helper?: string
  icon?: keyof typeof Ionicons.glyphMap
  rightIcon?: keyof typeof Ionicons.glyphMap
  onRightIconPress?: () => void
  containerStyle?: StyleProp<ViewStyle>
  inputStyle?: StyleProp<TextStyle>
  variant?: 'default' | 'success' | 'error' | 'warning'
  showPasswordToggle?: boolean
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  helper,
  icon,
  rightIcon,
  onRightIconPress,
  containerStyle,
  inputStyle,
  variant = 'default',
  showPasswordToggle = false,
  secureTextEntry,
  ...rest
}) => {
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const [focused, setFocused] = useState(false)

  const currentVariant = error ? 'error' : variant
  const borderColor =
    currentVariant === 'error'
      ? COLORS.danger
      : currentVariant === 'success'
        ? COLORS.success
        : currentVariant === 'warning'
          ? COLORS.warning
          : focused
            ? COLORS.secondary
            : COLORS.primary

  const iconColor =
    currentVariant === 'error'
      ? COLORS.danger
      : currentVariant === 'success'
        ? COLORS.success
        : currentVariant === 'warning'
          ? COLORS.warning
          : COLORS.primary

  const actualSecureTextEntry = showPasswordToggle
    ? !isPasswordVisible
    : secureTextEntry

  const handlePasswordToggle = () => {
    setIsPasswordVisible(!isPasswordVisible)
  }

  return (
    <View style={[styles.container, containerStyle]}>
      {label && <Text style={styles.label}>{label}</Text>}

      <View
        style={[
          styles.inputContainer,
          { borderColor },
          focused && styles.inputContainerFocused,
          currentVariant === 'error' && styles.inputContainerError,
        ]}
      >
        {icon && (
          <Ionicons
            name={icon}
            size={20}
            color={iconColor}
            style={styles.leftIcon}
          />
        )}

        <TextInput
          style={[
            styles.input,
            icon && styles.inputWithLeftIcon,
            (rightIcon || showPasswordToggle) && styles.inputWithRightIcon,
            inputStyle,
          ]}
          placeholderTextColor="#BDC3C7"
          secureTextEntry={actualSecureTextEntry}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          {...rest}
        />

        {showPasswordToggle && secureTextEntry && (
          <TouchableOpacity
            onPress={handlePasswordToggle}
            style={styles.rightIconButton}
          >
            <Ionicons
              name={isPasswordVisible ? 'eye-off' : 'eye'}
              size={20}
              color={COLORS.neutral[500]}
            />
          </TouchableOpacity>
        )}

        {rightIcon && !showPasswordToggle && (
          <TouchableOpacity
            onPress={onRightIconPress}
            style={styles.rightIconButton}
            disabled={!onRightIconPress}
          >
            <Ionicons name={rightIcon} size={20} color={iconColor} />
          </TouchableOpacity>
        )}
      </View>

      {error && (
        <View style={styles.messageContainer}>
          <Ionicons name="alert-circle" size={14} color={COLORS.danger} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {helper && !error && <Text style={styles.helperText}>{helper}</Text>}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    marginBottom: SPACING.md,
  },
  label: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.neutral[700],
    marginBottom: SPACING.xs,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.white,
    borderWidth: 3,
    borderRadius: 50,
    minHeight: 56,
  },
  inputContainerFocused: {
    transform: [{ scale: 1.02 }],
    shadowColor: COLORS.primary,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 4,
  },
  inputContainerError: {
    backgroundColor: '#FFFEF5',
  },
  input: {
    flex: 1,
    paddingHorizontal: 24,
    paddingVertical: 16,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: '500',
    color: COLORS.text,
  },
  inputWithLeftIcon: {
    paddingLeft: SPACING.xs,
  },
  inputWithRightIcon: {
    paddingRight: SPACING.xs,
  },
  leftIcon: {
    marginLeft: SPACING.md,
  },
  rightIconButton: {
    padding: SPACING.sm,
    marginRight: SPACING.xs,
  },
  messageContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: SPACING.xs,
    gap: SPACING.xs,
  },
  errorText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.danger,
  },
  helperText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.neutral[500],
    marginTop: SPACING.xs,
  },
})
