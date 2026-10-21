export interface User {
  id: string
  email: string
  phone_number: string
  full_name: string
  profile_photo_url?: string
  expo_push_token?: string
  is_active: boolean
  is_verified: boolean
  share_code?: string
  circle_invite_code?: string
  created_at: string
  updated_at: string
  // True when the user's own phone has texted STOP to our Twilio
  // number. Surfaces the management banner + profile callout.
  sms_unsubscribed?: boolean
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Session {
  id: string
  user_id: string
  session_type: 'checkin' | 'sos'
  expected_return_time: string
  expected_end_time?: string // For backward compatibility with backend
  expected_arrival_time?: string // Alias for expected_return_time
  actual_return_time?: string
  destination?: string
  location_name?: string // For backward compatibility with backend
  contact_name?: string // Name of the primary contact for this session
  outfit_photo_url?: string
  outfit_photo_uploaded_at?: string
  location_sharing_enabled: boolean
  last_known_latitude?: string
  last_known_longitude?: string
  last_location_update?: string
  last_battery_level?: number | null
  last_battery_state?: 'charging' | 'unplugged' | 'full' | 'unknown'
  status: 'active' | 'completed' | 'missed' | 'cancelled' | 'alerted'
  // When post-session data (photos, location trail) is purged; the
  // owner can adjust it from History/summary (±7d, floored at the original
  // deletion date — never below the evidence window).
  purge_after?: string
  // When the data was ACTUALLY deleted (covers admin early purge). Render
  // deletion dates from this; fall back to session end + 7d for legacy rows.
  purged_at?: string
  // When an admin cancelled the session — the neutral session-end anchor
  // (never actual_return_time: nobody marked themselves safe).
  cancelled_at?: string
  // Server truth: ANY alert ever fired for this session. Populated on the
  // owner detail endpoint; drives the summary's "Was shared with your
  // Circle" vs "Nothing was shared with your Circle". Fail-safe False.
  was_alerted?: boolean
  // Server truth: a circle member claimed an alert for this session ("I'm on
  // it"). Only populated by the owner poll endpoints (GET /sessions/{id} and
  // GET /sessions/active); other endpoints leave it false/absent.
  alert_acknowledged?: boolean
  // Server truth: the session is MISSED and every circle-alert delivery is
  // terminally undeliverable (or the circle emptied) — no one is coming.
  // Only populated by the owner poll endpoints; false/absent elsewhere.
  circle_unreachable?: boolean
  created_at: string
  updated_at: string
  completed_at?: string
}

// Circle of Trust types
export interface CircleOfTrustSettings {
  enabled: boolean
  auto_invite_enabled: boolean
  max_contacts: number
  require_mutual_trust: boolean
}

export interface CircleOfTrustMember {
  id: string
  user_id: string
  trusted_contact_id?: string
  // The inviter's label for the contact (from their phone contacts). The
  // backend resolves display_name = nickname ?? contact_full_name (the
  // contact's own app-account name). Render display_name.
  nickname?: string | null
  display_name?: string | null
  contact_full_name?: string | null
  is_app_user?: boolean
  contact_phone?: string
  contact_phone_number?: string // Backend uses this field name
  contact_email?: string
  priority_level?: string // Backend field mapped to trust_level on frontend
  status: 'active' | 'pending' | 'blocked' | 'opted_out'
  opted_out_at?: string | null
  added_at: string
  created_at?: string // Backend returns this, mapped to added_at on frontend
}

// Subscription types
export interface SubscriptionStatus {
  has_access: boolean
  reason:
    | 'subscription'
    | 'promotion'
    | 'referral_credit'
    | 'free_trial'
    | 'group_plan'
    | 'none'
  expires_at: string | null
  sessions_remaining: number | null
  plan_type: string | null
  group_plan_id: string | null
  group_plan_owner_name: string | null
  // Source of the backing subscription row (stripe_web/stripe_gift/comp/...),
  // used to tell a self-paid plan (manageable in-app) from a gift/comp/day-pass
  // (status-only). Null when access isn't a subscription row.
  source: string | null
  // True when a self-paid recurring sub is scheduled to stop at period end
  // ("Cancels …" + Reactivate); false when renewing; null when N/A.
  cancel_at_period_end: boolean | null
}

// Group plan types
export interface GroupPlanMember {
  id: string
  user_id: string
  full_name: string | null
  role: 'owner' | 'member'
  joined_at: string
}

export interface GroupPlan {
  id: string
  owner_user_id: string
  owner_name: string | null
  invite_code: string
  max_members: number
  member_count: number
  members: GroupPlanMember[]
  created_at: string
}

// Phone contact types (for expo-contacts integration)
export interface PhoneContact {
  id: string
  name: string
  phoneNumbers: string[]
  emails: string[]
  imageAvailable: boolean
  image?: { uri: string }
}
