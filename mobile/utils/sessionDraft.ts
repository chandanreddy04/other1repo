/**
 * Session draft — preserves what the user was setting up when the paywall
 * interrupted them (flow-review D3).
 *
 * Checkout happens in an external browser; by the time the user returns,
 * the /sessions/new screen has unmounted and its state is gone. The 402
 * handler stashes the form here, /plans's confirming step routes back to
 * /sessions/new when a draft exists, and the screen prefills from it.
 *
 * ALL-OR-NOTHING (owner decision 2026-07-18): the draft restores everything
 * — destination, toggles, the EXACT chosen return time, and the outfit
 * photo — unless the chosen deadline has passed or more than DRAFT_TTL_MS
 * elapsed since the user diverted away, in which case the whole draft is
 * discarded and the form starts fresh. Partial restores confused more than
 * they helped (a silently reset return time = wrong deadline).
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import { CHECKIN_CONFIG } from '../constants'

const DRAFT_KEY = '@MadeItHome:sessionDraft'
const DRAFT_TTL_MS = 30 * 60 * 1000 // 30 minutes — plenty for a checkout

export interface DraftPhoto {
  uri: string
  mimeType?: string
  fileName?: string
}

export interface SessionDraft {
  destination: string
  locationSharing: boolean
  /** The user's exact chosen deadline — restored verbatim, never recomputed. */
  returnTimeIso: string
  outfitPhoto: DraftPhoto | null
  ts: number
}

/** All-or-nothing validity: fresh AND the chosen deadline is still ahead. */
function isDraftValid(
  draft: Partial<SessionDraft>,
  now: number = Date.now()
): draft is SessionDraft {
  if (
    typeof draft.destination !== 'string' ||
    typeof draft.returnTimeIso !== 'string' ||
    typeof draft.ts !== 'number'
  ) {
    return false
  }
  if (now - draft.ts > DRAFT_TTL_MS) return false
  const deadline = new Date(draft.returnTimeIso).getTime()
  // Restoring SETS the time, so the minimum-lead floor applies here too.
  return (
    Number.isFinite(deadline) &&
    deadline >= now + CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES * 60_000
  )
}

export async function saveSessionDraft(
  draft: Omit<SessionDraft, 'ts'>
): Promise<void> {
  try {
    await AsyncStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ ...draft, ts: Date.now() })
    )
  } catch {
    // benign: Best-effort — losing the draft must never break the paywall redirect.
  }
}

/** Read a valid draft (consuming it), or null. */
export async function consumeSessionDraft(): Promise<SessionDraft | null> {
  try {
    const raw = await AsyncStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    await AsyncStorage.removeItem(DRAFT_KEY)
    const draft = JSON.parse(raw) as Partial<SessionDraft>
    return isDraftValid(draft) ? draft : null
  } catch {
    // benign: an unreadable draft starts a fresh form
    return null
  }
}

/** Non-destructive validity check (used by /plans confirming for routing) — must
 * always agree with consumeSessionDraft. */
export async function hasSessionDraft(): Promise<boolean> {
  try {
    const raw = await AsyncStorage.getItem(DRAFT_KEY)
    if (!raw) return false
    return isDraftValid(JSON.parse(raw) as Partial<SessionDraft>)
  } catch {
    // benign: an unreadable draft starts a fresh form
    return false
  }
}
