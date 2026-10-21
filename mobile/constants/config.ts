/**
 * Application configuration constants
 * Centralizes all configuration values for easy management
 */

/**
 * Build-time environment. Set per EAS build profile via EXPO_PUBLIC_APP_ENV
 * (Expo inlines EXPO_PUBLIC_* at build time); falls back to __DEV__ for local
 * `expo start`. This is how a TestFlight build can target the staging backend
 * while the App Store build targets production — same app, different origin.
 */
export const APP_ENV: 'development' | 'staging' | 'production' =
  (process.env.EXPO_PUBLIC_APP_ENV as
    | 'development'
    | 'staging'
    | 'production'
    | undefined) ?? (__DEV__ ? 'development' : 'production')

/** Backend web origin per environment. Replace the dev IP with your machine's. */
const WEB_ORIGINS = {
  development: 'http://192.168.2.194:8000',
  staging: 'https://staging-app.madeithomeapp.com',
  production: 'https://app.madeithomeapp.com',
} as const

/** Canonical production origin — used historically for website/legal links.
 *  Retained because some callers still reference the backend's production
 *  origin separately from the marketing site. Prefer MARKETING_ORIGIN for
 *  user-facing website / legal URLs. */
export const PROD_WEB_ORIGIN = WEB_ORIGINS.production

/** Marketing site origin — Cloudflare Pages, separate from the backend.
 *  Used for legal pages and the public site link. Not env-scoped; the
 *  marketing site has a single production deployment. */
export const MARKETING_ORIGIN = 'https://www.madeithomeapp.com'

/** Active backend origin for this build (drives the API base + file URLs). */
export const WEB_ORIGIN = WEB_ORIGINS[APP_ENV]

/**
 * API Configuration
 */
const _API_BASE_URL = `${WEB_ORIGIN}/api/v1`

if (APP_ENV !== 'development' && !_API_BASE_URL.startsWith('https://')) {
  throw new Error('Non-dev API base URL must use HTTPS')
}

export const API_CONFIG = {
  BASE_URL: _API_BASE_URL,
  TIMEOUT: 30000, // 30 seconds
  RETRY_ATTEMPTS: 3,
  RETRY_DELAY: 1000, // Base delay for exponential backoff
}

/**
 * AsyncStorage Keys
 */
export const STORAGE_KEYS = {
  // Auth
  ACCESS_TOKEN: '@MadeItHome:accessToken',
  REFRESH_TOKEN: '@MadeItHome:refreshToken',
  USER: '@MadeItHome:user',

  // Push Notifications
  EXPO_PUSH_TOKEN: '@MadeItHome:expoPushToken',
  FCM_TOKEN: '@MadeItHome:fcmToken',

  // App State
  ONBOARDING_COMPLETED: '@MadeItHome:onboardingCompleted',
  // Set on first successful auth on this device — gates the welcome
  // carousel (only shown before the first-ever login, flow-review D4).
  HAS_EVER_LOGGED_IN: '@MadeItHome:hasEverLoggedIn',
  BIOMETRIC_ENABLED: '@MadeItHome:biometricEnabled',
  LOCATION_PERMISSION: '@MadeItHome:locationPermission',
  NOTIFICATION_PERMISSION: '@MadeItHome:notificationPermission',

  // User Preferences
  THEME: '@MadeItHome:theme',
  LANGUAGE: '@MadeItHome:language',
  DEFAULT_CHECK_IN_DURATION: '@MadeItHome:defaultCheckInDuration',
}

/**
 * SecureStore keys (auth tokens live in expo-secure-store, not AsyncStorage).
 *
 * SecureStore keys may only contain alphanumerics, '.', '-', and '_' — the
 * '@'/':' in the AsyncStorage STORAGE_KEYS above are rejected by
 * expo-secure-store >= 15 (SDK 54) with "Invalid key provided to SecureStore".
 * These are intentionally distinct from STORAGE_KEYS.ACCESS_TOKEN/REFRESH_TOKEN,
 * which remain the (AsyncStorage-valid) source keys read by the one-time
 * migration in tokenStorage.ts.
 */
export const SECURE_STORE_KEYS = {
  ACCESS_TOKEN: 'MadeItHome.accessToken',
  REFRESH_TOKEN: 'MadeItHome.refreshToken',
}

/**
 * Check-in Configuration
 */
export const CHECKIN_CONFIG = {
  MAX_DURATION_MINUTES: 1440, // 24 hours
  DEFAULT_DURATION_MINUTES: 120, // 2 hours
  LOCATION_UPDATE_INTERVAL: 300000, // 5 minutes
  WARNING_THRESHOLD_MINUTES: 15, // Show warning 15 minutes before expiry

  // A trail's latest fix older than this renders as the static GRAY dot
  // instead of the pulsing blue one (owner decision 2026-07-19): the pulse
  // is a liveness claim, and 15 min = 3 missed cycles of the normal 5-min
  // capture cadence — updates have genuinely stopped, not just skipped once.
  LOCATION_STALE_THRESHOLD_MS: 15 * 60 * 1000,

  QUICK_RETURN_TIMES: [
    { label: '30 minutes', minutes: 30 },
    { label: '1 hour', minutes: 60 },
    { label: '2 hours', minutes: 120 },
    { label: '4 hours', minutes: 240 },
    { label: '6 hours', minutes: 360 },
    { label: '8 hours', minutes: 480 },
  ],

  // Single one-tap option — owner decision "30m is enough, don't
  // overcomplicate" (docs/flow-review.md §4.3 C3). Tap again to add more.
  EXTEND_TIME_OPTIONS: [{ label: '30 minutes', minutes: 30 }],

  // Post-deadline window before the circle is alerted. MUST mirror the
  // backend GRACE_PERIOD_MINUTES (app/core/config.py) — drives the
  // "your circle will be alerted in ~N min" countdown on the session screen.
  ALERT_GRACE_MINUTES: 5,

  // Minimum session length (owner decision 2026-07-19): the deadline can
  // never be SET closer than this to now — on any surface (create form,
  // rotary picker, ±30m adjusters, draft restore). MUST mirror the backend
  // MIN_SESSION_LEAD_MINUTES (app/core/config.py), which enforces the same
  // floor on create and extend/reduce.
  MIN_SESSION_LEAD_MINUTES: 30,

  // How long post-session data (photos, location trail) is kept. MUST mirror
  // the backend SESSION_DATA_RETENTION_DAYS (app/core/config.py) — retention
  // copy must always say this number (.claude/rules/domain-sessions-alerts.md).
  SESSION_DATA_RETENTION_DAYS: 7,

  // Shown wherever an in-flight session's circle has emptied (last member
  // texted STOP) — the screens must retract the "your contacts will be
  // alerted" promise, not keep making it. Tense follows the alert window;
  // post-deadline the useful action is direct help, not list management
  // (owner copy 2026-07-18).
  EMPTY_CIRCLE_COPY: {
    PRE_ALERT:
      'Last Circle member opted out. No alerts will be sent. Add a Circle member.',
    POST_DEADLINE:
      'Last Circle member opted out. No alerts were sent. If you need help, call someone you trust or 911.',
  },

  STATUS: {
    ACTIVE: 'active',
    COMPLETED: 'completed',
    EXPIRED: 'expired',
    CANCELLED: 'cancelled',
  },
}

/**
 * Contact Configuration
 */
export const CONTACT_CONFIG = {
  MAX_TRUSTED_CONTACTS: 10,
  MIN_TRUSTED_CONTACTS: 1,

  RELATIONSHIP_TYPES: [
    { value: 'family', label: 'Family' },
    { value: 'friend', label: 'Friend' },
    { value: 'partner', label: 'Partner' },
    { value: 'colleague', label: 'Colleague' },
    { value: 'neighbor', label: 'Neighbor' },
    { value: 'other', label: 'Other' },
  ],

  PRIORITY_LEVELS: {
    PRIMARY: 1,
    SECONDARY: 2,
    TERTIARY: 3,
  },
}

/**
 * Security Configuration
 */
export const SECURITY_CONFIG = {
  OTP_LENGTH: 6,
  OTP_EXPIRY_MINUTES: 10,
  MAX_OTP_ATTEMPTS: 5,
  OTP_RESEND_DELAY_SECONDS: 60,

  SESSION_TIMEOUT_MINUTES: 1440, // 24 hours
  REFRESH_TOKEN_EXPIRY_DAYS: 30,

  BIOMETRIC_TYPES: {
    FACE_ID: 'Face ID',
    TOUCH_ID: 'Touch ID',
    FINGERPRINT: 'Fingerprint',
    FACE: 'Face Recognition',
    IRIS: 'Iris',
  },
}

/**
 * App Metadata
 */
export const APP_INFO = {
  NAME: 'Made It Home',
  VERSION: '1.0.0',
  BUILD: '1',
  BUNDLE_ID: 'com.madeithome.app',

  SUPPORT_EMAIL: 'support@madeithomeapp.com',
  // Our toll-free Twilio sender (E164). Surfaced in the opt-out-row action
  // sheet, the "Text {name}" share-sheet prefill (START/STOP recovery), and
  // as the display fallback until GET /config overrides it at runtime.
  SMS_NUMBER: '+18774146630',
  PRIVACY_URL: `${MARKETING_ORIGIN}/privacy`,
  TERMS_URL: `${MARKETING_ORIGIN}/terms`,
  WEBSITE_URL: MARKETING_ORIGIN,
  SHORT_DOMAIN: 'https://madeitho.me',

  APP_STORE_URL: 'https://apps.apple.com/app/id6787024225',
  PLAY_STORE_URL:
    'https://play.google.com/store/apps/details?id=com.madeithome.app',
}

// Days between a user texting STOP and the worker auto-cancelling
// their Stripe subscription. Mirrors `settings.SMS_UNSUBSCRIBE_GRACE_DAYS`
// on the backend — keep in sync if changed.
export const SMS_UNSUBSCRIBE_GRACE_DAYS = 14

// SMS consent disclosure shown at every point a user submits their own phone
// number for SMS (mobile login, web /login). Required for Twilio A2P 10DLC
// campaign approval — together these cover the message types, frequency,
// data-rate disclaimer, and HELP/STOP instructions.
//   • promise   — standalone reassurance, shown prominently (not in the checkbox)
//   • agreement — the actual opt-in, shown as the consent checkbox label
//   • help      — informational HELP/STOP line, shown below the checkbox
// Keep textually identical to the web copy in
// `backend/app/web/templates/fragments/sms_consent.html`. See
// `docs/twilio-a2p-consent.md`.
export const SMS_CONSENT_COPY = {
  promise:
    'We never sell your number and never send spam — you’ll only ever get ' +
    'texts tied to relevant activity in the app.',
  agreement:
    'I agree to receive automated text messages from Made It Home at the ' +
    'number above: sign-in codes, check-in and safety alerts, referrals & billing. ' +
    'Message frequency varies, and message &amp; data rates may apply.',
  help: 'Text HELP for assistance with the app or STOP to cancel anytime.',
} as const

export type PlanType =
  | 'monthly'
  | 'annual'
  | 'group_monthly'
  | 'group_annual'

/**
 * Subscription Configuration
 */
export const SUBSCRIPTION_CONFIG = {
  MONTHLY_PRICE: '$5',
  MONTHLY_PRICE_CENTS: 500,
  ANNUAL_PRICE: '$48',
  ANNUAL_PRICE_CENTS: 4800,
  ANNUAL_MONTHLY_PRICE: '$4',
  GROUP_MONTHLY_PRICE: '$10',
  GROUP_MONTHLY_PRICE_CENTS: 1000,
  GROUP_ANNUAL_PRICE: '$96',
  GROUP_ANNUAL_PRICE_CENTS: 9600,
  GROUP_ANNUAL_MONTHLY_PRICE: '$8',
  GROUP_MAX_MEMBERS: 5,
  FREE_TRIAL_SESSIONS: 1,
  REFERRAL_CREDIT_DAYS: 30,

}

/**
 * Environment Configuration
 */
export const ENV = {
  IS_DEV: __DEV__,
  IS_PROD: !__DEV__,
  LOG_LEVEL: __DEV__ ? 'debug' : 'error',
  ENABLE_REDUX_LOGGER: __DEV__,
  ENABLE_NETWORK_LOGGER: __DEV__,
}

export default {
  API_CONFIG,
  STORAGE_KEYS,
  CHECKIN_CONFIG,
  CONTACT_CONFIG,
  SECURITY_CONFIG,
  APP_INFO,
  SUBSCRIPTION_CONFIG,
  ENV,
}
