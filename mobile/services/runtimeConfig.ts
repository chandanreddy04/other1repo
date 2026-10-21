// Runtime config service: fetches GET /api/v1/config and persists the
// result so display values (SMS sender number, support email, marketing
// URLs) can be rotated without an app store release.
//
// Strategy:
//   1. On every cold start, return the cached value immediately so the
//      UI never blocks on a network round-trip.
//   2. Fire a background fetch; on success, persist + push to the
//      zustand store so already-mounted screens re-render.
//   3. On fetch failure, keep using whatever was cached (or the
//      hardcoded fallback baked at build time).
//
// Anything time-critical (auth token, base URL) is intentionally NOT in
// here — those have to be available pre-network and aren't safe to
// rotate from the backend.

import AsyncStorage from '@react-native-async-storage/async-storage'
import { API_BASE_URL } from '../constants'
import { APP_INFO, MARKETING_ORIGIN } from '../constants/config'

export interface AppConfig {
  smsNumber: string
  supportEmail: string
  appDomain: string
  shortDomain: string
  marketingOrigin: string
  privacyUrl: string
  termsUrl: string
}

// Defaults baked into the bundle. Used until the first successful fetch
// (and as a fallback when we've never had a successful fetch on this
// install). Sourced from constants/config.ts so a build-time override
// is still possible if the backend is unreachable on a brand-new install.
export const FALLBACK_CONFIG: AppConfig = {
  smsNumber: APP_INFO.SMS_NUMBER,
  supportEmail: APP_INFO.SUPPORT_EMAIL,
  appDomain: APP_INFO.WEBSITE_URL,
  shortDomain: APP_INFO.SHORT_DOMAIN,
  marketingOrigin: MARKETING_ORIGIN,
  privacyUrl: APP_INFO.PRIVACY_URL,
  termsUrl: APP_INFO.TERMS_URL,
}

const CACHE_KEY = '@MadeItHome:runtimeConfig'

// Server uses snake_case; the type below mirrors backend/app/schemas/
// app_config.py.
interface ServerConfig {
  sms_number: string
  support_email: string
  app_domain: string
  short_domain: string
  marketing_origin: string
  privacy_url: string
  terms_url: string
}

function fromServer(s: ServerConfig): AppConfig {
  return {
    smsNumber: s.sms_number,
    supportEmail: s.support_email,
    appDomain: s.app_domain,
    shortDomain: s.short_domain,
    marketingOrigin: s.marketing_origin,
    privacyUrl: s.privacy_url,
    termsUrl: s.terms_url,
  }
}

export async function readCachedConfig(): Promise<AppConfig | null> {
  try {
    const raw = await AsyncStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<AppConfig>
    // Merge over fallback so a partial cached value (e.g. older app
    // wrote fewer keys) still produces a fully-populated object.
    return { ...FALLBACK_CONFIG, ...parsed }
  } catch {
    // benign: an unreadable cache means fallback config
    return null
  }
}

async function writeCachedConfig(cfg: AppConfig): Promise<void> {
  try {
    await AsyncStorage.setItem(CACHE_KEY, JSON.stringify(cfg))
  } catch {
    // benign: Cache write failures are non-fatal — the next launch just gets
    // the older cached value (or fallback).
  }
}

export async function fetchRuntimeConfig(): Promise<AppConfig | null> {
  // Uses fetch directly (not the auth-wrapped api client) — the endpoint
  // is public and hits before any token exists, plus this call has no
  // user-context to attach.
  try {
    const res = await fetch(`${API_BASE_URL}/config`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) return null
    const cfg = fromServer((await res.json()) as ServerConfig)
    await writeCachedConfig(cfg)
    return cfg
  } catch {
    // benign: falls back to cached config; api.ts reports transport failures
    return null
  }
}
