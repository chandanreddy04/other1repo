/**
 * Pure presentation logic for the inline permission panel — no React/native
 * imports, so it's directly unit-testable (the repo tests logic, not renders).
 * components/PermissionRequirements.tsx consumes these; the session surfaces use
 * `sessionRequirementItems` to turn live gaps into styled rows.
 */

import type { PermissionState, PermissionStatus } from '../services/permissions'

export type RequirementSeverity = 'warning' | 'info'

export interface RequirementItem {
  status: PermissionStatus
  severity: RequirementSeverity
}

/**
 * Turn the live session gaps into styled panel rows, preserving order. Every
 * session permission (Location, Notifications) is loud (warning) — they're
 * load-bearing for a safety session. The quiet `info` severity is reserved for
 * nice-to-have nudges (the contacts surface).
 */
export function sessionRequirementItems(
  gaps: PermissionStatus[]
): RequirementItem[] {
  return gaps.map(status => ({ status, severity: 'warning' }))
}

/**
 * The inline CTA for a gap: only a never-asked permission can be granted from
 * inside the app (the OS will prompt); every other non-granted state
 * (insufficient level, denied/revoked) can only be fixed in system Settings.
 */
export function requirementCta(state: PermissionState): 'allow' | 'settings' {
  return state === 'undetermined' ? 'allow' : 'settings'
}
