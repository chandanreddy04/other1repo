import React from 'react'
import {
  SafeAreaView,
  ScrollView,
  View,
  Text,
  StyleSheet,
  RefreshControlProps,
  ViewStyle,
  KeyboardAvoidingView,
  Platform,
} from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { COLORS, SPACING, TYPOGRAPHY } from '../constants'

interface ScreenWrapperProps {
  title?: string
  subtitle?: string
  children: React.ReactNode
  showGradient?: boolean
  refreshControl?: React.ReactElement<RefreshControlProps>
  scrollEnabled?: boolean
  centerContent?: boolean
  style?: ViewStyle
  contentStyle?: ViewStyle
  headerComponent?: React.ReactNode
  showKeyboardAvoidingView?: boolean
  keyboardVerticalOffset?: number
  safeAreaEdges?: Array<'top' | 'bottom' | 'left' | 'right'>
}

export const ScreenWrapper: React.FC<ScreenWrapperProps> = ({
  title,
  subtitle,
  children,
  showGradient = true,
  refreshControl,
  scrollEnabled = true,
  centerContent = false,
  style,
  contentStyle,
  headerComponent,
  showKeyboardAvoidingView = false,
  keyboardVerticalOffset = 0,
  safeAreaEdges = ['top', 'bottom'],
}) => {
  const content = (
    <>
      {(title || headerComponent) && (
        <View style={styles.header}>
          {headerComponent || (
            <>
              {title && <Text style={styles.title}>{title}</Text>}
              {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
            </>
          )}
        </View>
      )}
      <View style={[centerContent && styles.centered, contentStyle]}>
        {children}
      </View>
    </>
  )

  const scrollView = scrollEnabled ? (
    <ScrollView
      contentContainerStyle={[
        styles.scrollContent,
        centerContent && styles.centeredScroll,
      ]}
      refreshControl={refreshControl}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
    >
      {content}
    </ScrollView>
  ) : (
    <View style={[styles.container, centerContent && styles.centeredContainer]}>
      {content}
    </View>
  )

  const gradientContent = showGradient ? (
    <LinearGradient colors={['#FAFBFC', '#F4F6F7']} style={styles.gradient}>
      {scrollView}
    </LinearGradient>
  ) : (
    scrollView
  )

  const keyboardAwareContent = showKeyboardAvoidingView ? (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.container}
      keyboardVerticalOffset={keyboardVerticalOffset}
    >
      {gradientContent}
    </KeyboardAvoidingView>
  ) : (
    gradientContent
  )

  // Build safe area edges style
  const safeAreaStyle: ViewStyle = {
    flex: 1,
    backgroundColor: COLORS.background,
    paddingTop: safeAreaEdges.includes('top') ? 0 : undefined,
    paddingBottom: safeAreaEdges.includes('bottom') ? 0 : undefined,
  }

  return (
    <SafeAreaView style={[safeAreaStyle, style]}>
      {keyboardAwareContent}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  gradient: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: SPACING['2xl'],
    flexGrow: 1,
  },
  centeredScroll: {
    justifyContent: 'center',
    flexGrow: 1,
  },
  header: {
    alignItems: 'center',
    marginBottom: SPACING.xl,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.lg,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['3xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    marginTop: SPACING.xs,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
  },
  centeredContainer: {
    justifyContent: 'center',
    alignItems: 'center',
  },
})

export default ScreenWrapper
