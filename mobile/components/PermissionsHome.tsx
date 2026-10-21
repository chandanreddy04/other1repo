/**
 * Permissions Home — a persistent Home-screen card that stays visible until
 * every OS permission Made It Home's safety features depend on is granted,
 * then disappears. Tapping it (re)opens the permissions onboarding so the user
 * can grant whatever is still missing. Re-checks whenever Home regains focus
 * or the app foregrounds, so returning from onboarding or Settings updates it
 * live (no restart).
 *
 * Tracks: notifications (check-in reminders + circle alerts) and location (so
 * the circle can find you during a session/SOS).
 *
 * Supersedes the older per-permission "chips" — one card, one fix path
 * (onboarding). Related: app/(tabs)/index.tsx
 * (render site), app/(auth)/onboarding.tsx (the fix flow).
 */

import { useCallback, useEffect, useState } from 'react'
import {
  AppState,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { useFocusEffect, useRouter } from 'expo-router'
import * as Notifications from 'expo-notifications'
import * as Location from 'expo-location'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, RADIUS, SPACING, TYPOGRAPHY } from '../constants'
import {
  describeGaps,
  permissionGaps,
  type PermKey,
} from '../utils/permissionGaps'

export function PermissionsHome() {
  const router = useRouter()
  const [gaps, setGaps] = useState<PermKey[]>([])

  const check = useCallback(async () => {
    try {
      const [notif, loc] = await Promise.all([
        Notifications.getPermissionsAsync(),
        Location.getForegroundPermissionsAsync(),
      ])
      setGaps(
        permissionGaps({
          notifications: notif.status,
          location: loc.status,
        })
      )
    } catch {
      // benign: Permission modules unavailable (e.g. a stripped build) — show nothing;
      // the native-module health probe reports that separately.
    }
  }, [])

  // Re-check when Home regains focus (returning from the onboarding flow) and
  // when the app foregrounds (returning from system Settings).
  useFocusEffect(
    useCallback(() => {
      void check()
    }, [check])
  )
  useEffect(() => {
    const sub = AppState.addEventListener('change', s => {
      if (s === 'active') void check()
    })
    return () => sub.remove()
  }, [check])

  if (gaps.length === 0) return null

  return (
    <TouchableOpacity
      style={styles.card}
      activeOpacity={0.8}
      onPress={() =>
        router.push({
          pathname: '/(auth)/onboarding',
          params: { steps: gaps.join(',') },
        })
      }
      accessibilityRole="button"
      accessibilityLabel={`${gaps.length} permission${
        gaps.length === 1 ? '' : 's'
      } still needed. Tap to finish setup.`}
    >
      <View style={styles.iconWrap}>
        <Ionicons name="shield-half" size={22} color={COLORS.warningDark} />
      </View>
      <View style={styles.body}>
        <Text style={styles.title}>Finish your safety setup</Text>
        <Text style={styles.subtitle}>{describeGaps(gaps)}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={COLORS.warningDark} />
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
    marginBottom: SPACING.md,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: RADIUS.full,
    backgroundColor: COLORS.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: {
    flex: 1,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as never,
    color: COLORS.text,
    marginBottom: 2,
  },
  subtitle: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    lineHeight: 18,
  },
})
