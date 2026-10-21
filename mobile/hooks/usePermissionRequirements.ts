/**
 * Live, point-of-use permission sufficiency for a set of permissions a surface
 * depends on. Re-reads the OS status whenever the screen regains focus and
 * whenever the app foregrounds — because the user can change any permission in
 * Settings at any time, and the instant they do (mid-session included) the
 * surface must reflect it without a restart.
 *
 * Returns the live `statuses`, the subset that are `gaps` (not sufficient at the
 * required level), and a `refresh` to re-check on demand (e.g. right after the
 * inline panel requests a permission).
 *
 * Related: services/permissions.ts (the checks), components/
 * PermissionRequirements.tsx (renders the gaps).
 */

import { useCallback, useEffect, useState } from 'react'
import { AppState } from 'react-native'
import { useFocusEffect } from 'expo-router'
import {
  getPermissionStatuses,
  type PermissionKey,
  type PermissionStatus,
} from '../services/permissions'

export interface PermissionRequirements {
  statuses: PermissionStatus[]
  /** Statuses that are not sufficient at the required level. */
  gaps: PermissionStatus[]
  refresh: () => Promise<void>
}

export function usePermissionRequirements(
  keys: PermissionKey[]
): PermissionRequirements {
  const [statuses, setStatuses] = useState<PermissionStatus[]>([])
  // Callers pass a fresh array literal each render; key on the joined value so
  // `refresh`'s identity is stable across renders with the same permissions.
  const keyId = keys.join(',')

  const refresh = useCallback(async () => {
    try {
      setStatuses(
        await getPermissionStatuses(keyId.split(',') as PermissionKey[])
      )
    } catch {
      // benign: Native permission modules unavailable (e.g. a stripped build) — surface
      // nothing; verifyNativeModules() reports that separately.
    }
  }, [keyId])

  // Re-check when the screen regains focus (returning from onboarding) and when
  // the app foregrounds (returning from system Settings).
  useFocusEffect(
    useCallback(() => {
      void refresh()
    }, [refresh])
  )
  useEffect(() => {
    const sub = AppState.addEventListener('change', s => {
      if (s === 'active') void refresh()
    })
    return () => sub.remove()
  }, [refresh])

  const gaps = statuses.filter(s => !s.sufficient)
  return { statuses, gaps, refresh }
}
