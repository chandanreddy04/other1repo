import { SMS_CONSENT_COPY, APP_INFO } from './config'

// Twilio A2P 10DLC requires the consent disclosure to spell out specific
// elements. This guards the mobile source-of-truth copy so a future edit
// can't silently drop a required element (the login checkbox renders these
// verbatim, and the web partial mirrors them). See docs/twilio-a2p-consent.md.
describe('SMS_CONSENT_COPY — Twilio A2P required elements', () => {
  it('promise states we never sell the number and never spam', () => {
    const promise = SMS_CONSENT_COPY.promise.toLowerCase()
    expect(promise).toContain('never sell')
    expect(promise).toContain('spam')
  })

  it('agreement describes message types, frequency and data rates', () => {
    const agreement = SMS_CONSENT_COPY.agreement.toLowerCase()
    // message types
    expect(agreement).toContain('sign-in codes')
    expect(agreement).toContain('alerts')
    // frequency disclosure
    expect(agreement).toContain('frequency varies')
    // message & data rates disclaimer
    expect(agreement).toContain('data rates may apply')
  })

  it('help line gives HELP and STOP instructions', () => {
    const help = SMS_CONSENT_COPY.help
    expect(help).toContain('HELP')
    expect(help).toContain('STOP')
  })
})

// Store links back the App Store / Play Store URLs. No current consumer —
// mobile/services/sms.ts (the only past reader) was dead code, removed
// 2026-09-27 — but the format is guarded here for whenever one is added.
// A name-slug App Store URL without /id<number> doesn't resolve, and the
// Play link must carry the real package — guard both.
describe('APP_INFO store links', () => {
  it('App Store URL uses the real app id (not a non-resolving name slug)', () => {
    expect(APP_INFO.APP_STORE_URL).toBe('https://apps.apple.com/app/id6787024225')
  })

  it('Play Store URL uses the real package', () => {
    expect(APP_INFO.PLAY_STORE_URL).toBe(
      'https://play.google.com/store/apps/details?id=com.madeithome.app'
    )
  })
})
