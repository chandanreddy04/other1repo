import React from 'react'
import {
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  View,
  StyleSheet,
} from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { COLORS, SPACING } from '../constants'

interface AuthScreenWrapperProps {
  children: React.ReactNode
  withKeyboard?: boolean
  centered?: boolean
  // When true, content scrolls instead of being clipped, and the keyboard can
  // be collapsed by scrolling or tapping empty space — so screens taller than
  // the area above the keyboard (e.g. login with the SMS-consent block) stay
  // fully reachable while autoFocus keeps the keyboard up.
  scrollable?: boolean
}

export function AuthScreenWrapper({
  children,
  withKeyboard = false,
  centered = true,
  scrollable = false,
}: AuthScreenWrapperProps) {
  const content = scrollable ? (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={[
        styles.scrollContent,
        centered && styles.centered,
        !centered && styles.topAligned,
      ]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
      showsVerticalScrollIndicator={false}
    >
      {children}
    </ScrollView>
  ) : (
    <View
      style={[
        styles.contentWrapper,
        centered && styles.centered,
        !centered && styles.topAligned,
      ]}
    >
      {children}
    </View>
  )

  return (
    <SafeAreaView style={styles.container}>
      <LinearGradient colors={['#FAFBFC', '#F4F6F7']} style={styles.gradient}>
        {withKeyboard ? (
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={styles.flex}
          >
            {content}
          </KeyboardAvoidingView>
        ) : (
          content
        )}
      </LinearGradient>
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
  flex: {
    flex: 1,
  },
  contentWrapper: {
    flex: 1,
    paddingHorizontal: SPACING.xl,
  },
  scrollContent: {
    flexGrow: 1,
    paddingHorizontal: SPACING.xl,
    paddingVertical: SPACING.xl,
  },
  centered: {
    justifyContent: 'center',
  },
  topAligned: {
    paddingTop: SPACING.xl,
  },
})
