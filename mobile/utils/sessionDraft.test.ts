import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  saveSessionDraft,
  consumeSessionDraft,
  hasSessionDraft,
} from './sessionDraft'

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

const DRAFT = {
  destination: 'Central Park',
  locationSharing: true,
  returnTimeIso: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
  outfitPhoto: { uri: 'file:///cache/outfit.jpg', mimeType: 'image/jpeg' },
}

describe('sessionDraft — all-or-nothing restore', () => {
  beforeEach(async () => {
    await AsyncStorage.clear()
  })

  it('round-trips EVERYTHING (incl. exact time + photo) and consumes once', async () => {
    await saveSessionDraft(DRAFT)
    expect(await hasSessionDraft()).toBe(true)

    const draft = await consumeSessionDraft()
    expect(draft).toMatchObject(DRAFT)
    // Consumed — a second read must not resurface it.
    expect(await consumeSessionDraft()).toBeNull()
    expect(await hasSessionDraft()).toBe(false)
  })

  it('discards the whole draft after 30 minutes', async () => {
    await AsyncStorage.setItem(
      '@MadeItHome:sessionDraft',
      JSON.stringify({ ...DRAFT, ts: Date.now() - 31 * 60 * 1000 })
    )
    expect(await hasSessionDraft()).toBe(false)
    expect(await consumeSessionDraft()).toBeNull()
  })

  it('discards the whole draft once the chosen deadline has passed', async () => {
    // Saved 5 minutes ago (fresh by TTL) but the deadline is behind us —
    // restoring it would create a session that's instantly overdue.
    await AsyncStorage.setItem(
      '@MadeItHome:sessionDraft',
      JSON.stringify({
        ...DRAFT,
        returnTimeIso: new Date(Date.now() - 60 * 1000).toISOString(),
        ts: Date.now() - 5 * 60 * 1000,
      })
    )
    expect(await hasSessionDraft()).toBe(false)
    expect(await consumeSessionDraft()).toBeNull()
  })

  it('discards old-format drafts missing the return time (no partials)', async () => {
    await AsyncStorage.setItem(
      '@MadeItHome:sessionDraft',
      JSON.stringify({
        destination: 'Central Park',
        locationSharing: true,
        ts: Date.now(),
      })
    )
    expect(await hasSessionDraft()).toBe(false)
    expect(await consumeSessionDraft()).toBeNull()
  })

  it('round-trips a photo-less draft (outfitPhoto null)', async () => {
    await saveSessionDraft({ ...DRAFT, outfitPhoto: null })
    const draft = await consumeSessionDraft()
    expect(draft?.outfitPhoto).toBeNull()
    expect(draft?.returnTimeIso).toBe(DRAFT.returnTimeIso)
  })

  it('tolerates corrupt storage', async () => {
    await AsyncStorage.setItem('@MadeItHome:sessionDraft', '{not json')
    expect(await hasSessionDraft()).toBe(false)
    expect(await consumeSessionDraft()).toBeNull()
  })
})
