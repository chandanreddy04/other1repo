/**
 * Inline, non-blocking permission guidance. Given the permission gaps a surface
 * cares about, it renders — per gap — WHAT we need, WHY, a "Learn more" link
 * that resurfaces the full onboarding explanation for that permission, and a
 * state-aware call to action:
 *   - `undetermined` → "Allow" (requests via the central module, then refreshes)
 *   - `insufficient` / `denied` → "Open Settings" (deep-links to system Settings)
 *
 * Presentational: the parent decides which items to show (session surfaces pass
 * their `usePermissionRequirements` gaps; the contacts surface passes its own
 * addable-contact-derived item) and supplies `onChanged` so it can re-check
 * after a request. Severity controls prominence — `warning` (location,
 * notifications) is loud; `info` (the contacts nudge when the circle already
 * has members) is quiet but still visible.
 *
 * This never blocks the surface's primary action; it only informs and offers a
 * one-tap path to fix. Related: services/permissions.ts, app/(auth)/onboarding.tsx.
 */

import { useState } from 'react'
import { Linking, StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, RADIUS, SPACING, TYPOGRAPHY } from '../constants'
import {
  PERMISSION_INFO,
  requestPermission,
  type PermissionStatus,
} from '../services/permissions'
import notificationService from '../services/notifications'
import {
  requirementCta,
  type RequirementItem,
  type RequirementSeverity,
} from '../utils/permissionUi'

interface PermissionRequirementsProps {
  items: RequirementItem[]
  /** Called after a permission is requested so the parent can re-check. */
  onChanged?: () => void
  testID?: string
}

const SEVERITY_STYLE: Record<
  RequirementSeverity,
  { bg: string; accent: string; icon: 'warning' | 'information-circle' }
> = {
  warning: {
    bg: COLORS.warningLight,
    accent: COLORS.warningDark,
    icon: 'warning',
  },
  info: {
    bg: COLORS.neutral[100],
    accent: COLORS.accent.blue,
    icon: 'information-circle',
  },
}

export function PermissionRequirements({
  items,
  onChanged,
  testID,
}: PermissionRequirementsProps) {
  const router = useRouter()
  const [busyKey, setBusyKey] = useState<string | null>(null)

  if (items.length === 0) return null

  const handleAllow = async (status: PermissionStatus) => {
    setBusyKey(status.key)
    try {
      const result = await requestPermission(status.key)
      // Granting notifications must also register + persist the push token, or
      // the backend can't reach this device until the next cold start.
      if (status.key === 'notifications' && result.sufficient) {
        await notificationService.registerAndSaveToken()
      }
    } finally {
      setBusyKey(null)
      onChanged?.()
    }
  }

  const handleSettings = () => {
    void Linking.openSettings()
  }

  const learnMore = (step: string) => {
    router.push({ pathname: '/(auth)/onboarding', params: { steps: step } })
  }

  return (
    <View style={styles.wrap} testID={testID}>
      {items.map(({ status, severity }) => {
        const info = PERMISSION_INFO[status.key]
        const style = SEVERITY_STYLE[severity]
        const canAllow = requirementCta(status.state) === 'allow'
        return (
          <View
            key={status.key}
            style={[styles.row, { backgroundColor: style.bg }]}
            testID={`permission-row-${status.key}`}
          >
            <Ionicons
              name={style.icon}
              size={20}
              color={style.accent}
              style={styles.rowIcon}
            />
            <View style={styles.body}>
              <Text style={styles.what}>{info.what}</Text>
              <Text style={styles.why}>{info.why}</Text>
              <View style={styles.actions}>
                <TouchableOpacity
                  onPress={() => learnMore(info.onboardingStep)}
                  accessibilityRole="button"
                  accessibilityLabel={`Learn more about ${info.label} access`}
                >
                  <Text style={styles.learnMore}>Learn more</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.cta, { backgroundColor: style.accent }]}
                  disabled={busyKey === status.key}
                  onPress={() =>
                    canAllow ? handleAllow(status) : handleSettings()
                  }
                  accessibilityRole="button"
                  accessibilityLabel={
                    canAllow
                      ? `Allow ${info.label} access`
                      : `Open Settings to enable ${info.label}`
                  }
                >
                  <Text style={styles.ctaText}>
                    {canAllow ? 'Allow' : 'Open Settings'}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        )
      })}
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: {
    gap: SPACING.sm,
    marginBottom: SPACING.md,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: SPACING.sm,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
  },
  rowIcon: {
    marginTop: 2,
  },
  body: {
    flex: 1,
  },
  what: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as never,
    color: COLORS.text,
    marginBottom: 2,
  },
  why: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    lineHeight: 18,
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: SPACING.sm,
  },
  learnMore: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as never,
    color: COLORS.primary,
  },
  cta: {
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.xs + 2,
    borderRadius: RADIUS.full,
  },
  ctaText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as never,
    color: COLORS.white,
  },
})
