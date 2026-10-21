import { useEffect, useRef, useState } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  SafeAreaView,
  ActivityIndicator,
  TouchableOpacity,
} from 'react-native'
import { useRouter, usePathname } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, TYPOGRAPHY, RADIUS } from '../constants'
import { useAuthStore } from '../store/useAuthStore'
import { setPendingRoute } from '../utils/authRedirect'

interface DeepLinkAcceptScreenProps {
  // The accept action (e.g. join group plan, accept circle invite).
  // Runs exactly once, after auth is confirmed.
  accept: () => Promise<void>
  loadingText: string
  successTitle: string
  successBody: string
  errorTitle: string
  primaryActionLabel: string
  onPrimaryAction: () => void
}

/**
 * Shared scaffold for short-link deep-link accept screens (group-plan
 * join, circle-of-trust invite). Handles the auth gate, the one-shot
 * accept call, and the loading / error / success states.
 *
 * Auth gate: the screen MUST wait for the auth store to finish hydrating
 * (`isLoading`) before deciding. Redirecting on `!user` while the store
 * is still loading would bounce an already-signed-in user to login on a
 * cold start (the universal link launches the app from killed state) and
 * lose the invite. Only once `isLoading` is false and there's still no
 * user do we send them to login.
 */
export function DeepLinkAcceptScreen({
  accept,
  loadingText,
  successTitle,
  successBody,
  errorTitle,
  primaryActionLabel,
  onPrimaryAction,
}: DeepLinkAcceptScreenProps) {
  const router = useRouter()
  const pathname = usePathname()
  const user = useAuthStore(state => state.user)
  const authLoading = useAuthStore(state => state.isLoading)
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const attempted = useRef(false)

  useEffect(() => {
    // Wait for the auth store to hydrate before deciding anything.
    if (authLoading) return
    if (!user) {
      // Stash where we were headed so the auth flow returns us here
      // instead of dumping us on the home tab. Fire-and-forget: the local
      // write completes long before the user finishes signing in, and a
      // failed write must not block the redirect.
      void setPendingRoute(pathname)
      router.replace('/(auth)/login')
      return
    }
    if (attempted.current) return
    attempted.current = true
    setAccepting(true)
    accept()
      .then(() => setDone(true))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Something went wrong')
      })
      .finally(() => setAccepting(false))
    // `accept`/`router` are stable-by-construction and re-entry is guarded
    // by `attempted`; we intentionally key only off auth state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user])

  if (authLoading || accepting) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={COLORS.primary} />
          <Text style={styles.statusText}>{loadingText}</Text>
        </View>
      </SafeAreaView>
    )
  }

  if (error) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <Ionicons
            name="close-circle-outline"
            size={64}
            color={COLORS.danger}
          />
          <Text style={styles.titleText}>{errorTitle}</Text>
          <Text style={styles.statusText}>{error}</Text>
          <TouchableOpacity
            style={styles.button}
            onPress={() => router.replace('/(tabs)')}
          >
            <Text style={styles.buttonText}>Go Home</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    )
  }

  if (done) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <Ionicons name="checkmark-circle" size={64} color={COLORS.primary} />
          <Text style={styles.titleText}>{successTitle}</Text>
          <Text style={styles.statusText}>{successBody}</Text>
          <TouchableOpacity style={styles.button} onPress={onPrimaryAction}>
            <Text style={styles.buttonText}>{primaryActionLabel}</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    )
  }

  return null
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: SPACING.xl,
    gap: SPACING.md,
  },
  titleText: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  statusText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center' as const,
  },
  button: {
    backgroundColor: COLORS.primary,
    paddingHorizontal: SPACING.xl,
    paddingVertical: 14,
    borderRadius: RADIUS.full,
    marginTop: SPACING.md,
  },
  buttonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
})
