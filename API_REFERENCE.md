# Made It Home - API Reference

Base URL: `http://localhost:8000/api/v1`

> Paths and methods below are generated from `app.routes` on 2026-09-27
> (`python -c "from app.main import app; ..."` over `app.routes`, filtered to
> `/api/v1`). Request/response bodies are drawn from `app/schemas/`.

## Authentication

Made It Home uses phone number-based OTP (One-Time Password) authentication. No email or password is required.

### Request OTP
Send a verification code to a phone number.

```http
POST /auth/request-otp
Content-Type: application/json

{
  "phone_number": "+14155552671"  // E164 format required
}
```

Response:
```json
{
  "success": true,
  "message": "Verification code sent to your phone"
}
```

### Verify OTP
Verify the OTP code and authenticate/register the user.

```http
POST /auth/verify-otp
Content-Type: application/json

{
  "phone_number": "+14155552671",
  "otp_code": "123456"
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "is_new_user": false,
  "user": {
    "id": "uuid",
    "phone_number": "+14155552671",
    "full_name": "John Doe",
    "profile_photo_url": null,
    "is_active": true,
    "phone_ownership_verified": true,
    "share_code": "ABC123",
    "circle_invite_code": "XYZ789",
    "referrals_remaining": 6,
    "sms_unsubscribed": false,
    "created_at": "2025-01-19T12:00:00Z",
    "updated_at": "2025-01-19T12:00:00Z"
  },
  "deletion_pending": false,
  "scheduled_deletion_at": null
}
```

Note: If `is_new_user` is `true`, `user` is `null` and the app collects the
user's name next. `deletion_pending: true` (with `scheduled_deletion_at`) means
the account is soft-deleted mid-grace: the tokens work only for
`POST /users/me/restore`.

### Resend OTP
Resend the verification code to a phone number.

```http
POST /auth/resend-otp
Content-Type: application/json

{
  "phone_number": "+14155552671"
}
```

Response:
```json
{
  "success": true,
  "message": "Verification code sent to your phone"
}
```

### Refresh Token
```http
POST /auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJ..."
}
```

## User Management

### Get Current User
```http
GET /users/me
Authorization: Bearer <access_token>
```

### Update User
```http
PUT /users/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "full_name": "Jane Doe",
  "profile_photo_url": "https://example.com/photo.jpg"
}
```

Note: Phone number cannot be updated directly through this endpoint as it requires OTP verification.

### Upload Profile Photo
```http
POST /users/me/profile-photo
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <image_file>
```

Response:
```json
{
  "id": "uuid",
  "phone_number": "+14155552671",
  "full_name": "John Doe",
  "profile_photo_url": "https://s3.amazonaws.com/bucket/profile-photos/...",
  "is_active": true,
  "phone_ownership_verified": true,
  "created_at": "2025-01-19T12:00:00Z",
  "updated_at": "2025-01-19T12:00:00Z"
}
```

### Delete Account
Soft-deletes immediately (schedules a hard purge after the grace period);
Stripe subscriptions are cancelled at period end. `sponsorship_choices` maps
Stripe subscription IDs the caller is sponsoring to `"stop"` (default) or
`"keep"`. See `docs/account-deletion-plan.md`.
```http
DELETE /users/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "sponsorship_choices": {"sub_123": "keep"}
}
```

Response:
```json
{
  "soft_deleted": true,
  "scheduled_deletion_at": "2026-10-23T12:00:00Z",
  "grace_days": 30
}
```

### Restore Account
Clears a soft-delete mid-grace. Callable with the access token issued by the
deletion-pending `verify-otp` response even though the account is soft-deleted.
```http
POST /users/me/restore
Authorization: Bearer <access_token>
```

## Circle of Trust

### Get Circle of Trust Members
```http
GET /circle/members
Authorization: Bearer <access_token>
```

### Add Contact to Circle of Trust
```http
POST /circle/members
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "nickname": "John Doe",
  "contact_phone_number": "+14155552671"
}
```

### Get Circle of Trust Settings
```http
GET /circle/settings
Authorization: Bearer <access_token>
```

### Update Circle of Trust Settings
```http
PUT /circle/settings
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "max_contacts": 3,
  "auto_import_contacts": false,
  "sms_invitations_enabled": true,
  "notification_preferences": null
}
```

### Remove from Circle of Trust
```http
DELETE /circle/members/{member_id}
Authorization: Bearer <access_token>
```

## Sessions

A session is a check-in (`session_type: "checkin"`) or an SOS
(`session_type: "sos"`, immediately overdue by design). Both share the same
pipeline and resource path — there is no separate `/checkins`.

### Get Sessions
```http
GET /sessions?skip=0&limit=20
Authorization: Bearer <access_token>
```

### Get Active Session
Returns the caller's current non-terminal session (`active`, `missed` or
`alerted`), or `null`.
```http
GET /sessions/active
Authorization: Bearer <access_token>
```

### Get Session
```http
GET /sessions/{session_id}
Authorization: Bearer <access_token>
```

### Create Session
`expected_return_time` is required for `checkin`; ignored (set to now) for
`sos`, which also forces `location_sharing_enabled: true`. SOS is always
free regardless of subscription status.
```http
POST /sessions
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "session_type": "checkin",
  "expected_return_time": "2026-09-23T22:00:00Z",
  "tz_offset_minutes": -420,
  "destination": "Downtown with friends",
  "location_sharing_enabled": false
}
```

### Upload Outfit Photo
```http
POST /sessions/outfit-photos
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file=<binary>
session_id=<uuid>
```

### Complete Session
Marks the session safe/complete; if it had escalated, resolves alerts and
sends the all-clear to the circle.
```http
PUT /sessions/{session_id}/complete
Authorization: Bearer <access_token>
```

### Extend Session
`minutes_to_extend` may be negative (correct an accidental over-extend);
zero is rejected. Bounded to ±240 minutes.
```http
PUT /sessions/{session_id}/extend
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "minutes_to_extend": 60
}
```

### Adjust Data Retention
Owner-only. Adjusts the post-session data purge date by
±`RETENTION_EXTENSION_DAYS`; only while the data still exists.
```http
PUT /sessions/{session_id}/retention
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "days": 7
}
```

### Report Location / Battery
Appends one reading to the session's locations and refreshes its last-known
position. Coordinates are optional (a battery-only reading is accepted) but
must be sent together; coordinates require `location_sharing_enabled`.
Returns the updated session (200).
```http
POST /sessions/{session_id}/locations
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "latitude": 37.7749,
  "longitude": -122.4194,
  "battery_level": 0.82,
  "battery_state": "unplugged"
}
```

### Get Location History
Owner, or a circle member who was alerted for the session.
```http
GET /sessions/{session_id}/locations
Authorization: Bearer <access_token>

Response: [{"latitude": 37.7749, "longitude": -122.4194, "battery_level": 0.82,
            "battery_state": "unplugged", "recorded_at": "..."}]
```

## Groups

A group plan shares one group-tier subscription among up to
`GROUP_PLAN_MAX_MEMBERS` accounts. The segment after `/groups/` is the plan
id in every route except join, where it is the shared invite code.

### Get My Group
Returns the caller's active group plan, or `null`.
```http
GET /groups
Authorization: Bearer <access_token>
```

### Join a Group
```http
POST /groups/{invite_code}/members
Authorization: Bearer <access_token>
```

### Leave a Group
Deletes the caller's own membership. 404 if the caller isn't in that plan;
400 for the owner (cancel the subscription instead).
```http
DELETE /groups/{plan_id}/members/me
Authorization: Bearer <access_token>
```

### Remove a Member (owner only)
```http
DELETE /groups/{plan_id}/members/{member_id}
Authorization: Bearer <access_token>
```

### Regenerate Invite Code (owner only)
Invalidates the old invite link.
```http
POST /groups/{plan_id}/invite-code
Authorization: Bearer <access_token>

Response: {"invite_code": "..."}
```

## Subscriptions

### Get Subscription Status
```http
GET /subscriptions
Authorization: Bearer <access_token>
```

Response:
```json
{
  "has_access": true,
  "reason": "subscription",
  "expires_at": "2026-10-27T12:00:00Z",
  "sessions_remaining": null,
  "plan_type": "monthly",
  "group_plan_id": null,
  "group_plan_owner_name": null,
  "source": "stripe_web",
  "cancel_at_period_end": false
}
```

Note: `reason` is one of `subscription`, `promotion`, `referral_credit`,
`free_trial`, `group_plan`, `none`. `source` (the backing `Subscription`
row's `SubscriptionSource`) and `cancel_at_period_end` are `null` when
access isn't a self-paid recurring Stripe subscription.

### Cancel / Reactivate Subscription
Native cancel-at-period-end and reactivate. The only mutable field is
`cancel_at_period_end`. Only a self-paid recurring Stripe subscription is
manageable here — gift/comp/day-pass access has no recurring subscription
to toggle (404). Change-plan and payment-method updates stay on the
Stripe-hosted portal (`POST /subscriptions/portal`).
```http
PATCH /subscriptions
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cancel_at_period_end": true
}
```

Response: same shape as `GET /subscriptions`.

### Create Checkout Session
```http
POST /subscriptions/checkout
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "plan_type": "monthly"
}
```

`plan_type`: `monthly`, `annual`, `group_monthly`, or `group_annual`. 409 if
the caller already has an active subscription.

Response:
```json
{
  "checkout_url": "https://checkout.stripe.com/..."
}
```

### Create Day Pass Checkout Session
One-time $0.99 pass covering the next 24h.
```http
POST /subscriptions/day-pass
Authorization: Bearer <access_token>
```

Response: same shape as the checkout-session response above
(`{"checkout_url": "..."}`).

### Create Billing Portal Session
Opens the Stripe-hosted customer portal for changing plan or payment
method.
```http
POST /subscriptions/portal
Authorization: Bearer <access_token>
```

Response:
```json
{
  "portal_url": "https://billing.stripe.com/..."
}
```

## Referrals

### Get Referral Info
Returns (and lazily generates) the caller's own referral code and usage.
```http
GET /referrals
Authorization: Bearer <access_token>
```

Response:
```json
{
  "referral_code": "ABC123XY",
  "can_refer": true,
  "referrals_used": 1,
  "referrals_max": 6
}
```

### Apply a Referral Code
Redeems someone else's referral code for the caller. 400 if the caller
already used a code or the code is their own; 404 if the code is invalid.
```http
POST /referrals
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "referral_code": "ABC123XY"
}
```

Response:
```json
{
  "message": "Referral applied. You received 30 days free."
}
```

### Look Up a Referral Code
Public lookup (used by the web referral landing page) — no auth.
```http
GET /referrals/{code}
```

Response:
```json
{
  "referrer_name": "Jane",
  "referral_code": "ABC123XY"
}
```

## Sponsorship Requests

### Ask a Sponsor
Records an "ask a sponsor" event for fulfillment-rate analytics; the actual
ask SMS is sent from the user's own native SMS app, not by the backend.
Idempotent — a second call for the same (requester, target) pair while one
is still pending is a no-op.
```http
POST /sponsorship-requests
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "target_phone": "+14155552671"
}
```

Response: `201 Created`, empty body.

## Config

### Get App Config
Public (no auth) — read before login, e.g. by the auth screens. Lets the
mobile app rotate the SMS sender number, support email, and marketing URLs
without a store release; the mobile client caches the response and falls
back to its last-known-good values when offline.
```http
GET /config
```

Response:
```json
{
  "sms_number": "+18774146630",
  "support_email": "support@madeithomeapp.com",
  "app_domain": "https://app.madeithomeapp.com",
  "short_domain": "https://madeitho.me",
  "marketing_origin": "https://www.madeithomeapp.com",
  "privacy_url": "https://www.madeithomeapp.com/privacy",
  "terms_url": "https://www.madeithomeapp.com/terms"
}
```

## Alerts

Circle members are notified by SMS only and view/acknowledge alerts via the
tokenized public alert page (`/alerts/{alert_id}`, web-only) — there is no
mobile API surface for alerts (owner decision 2026-09-22). The logged-in web
`/alerts` page (the Circle member's post-login landing) is list-only; each row links to the public page,
which is the only place details and acknowledgement render.

SOS is not a separate alert endpoint: it is `POST /sessions` with
`"session_type": "sos"`.

## Delivery Webhooks

These are served at the site root, **not** under `/api/v1`.

### Twilio Delivery Status
```http
POST /webhooks/delivery/twilio
Content-Type: application/x-www-form-urlencoded
X-Twilio-Signature: <signature>
```
Receives SMS delivery status updates from Twilio. Validates request signature.

### SNS Delivery Status
```http
POST /webhooks/delivery/sns
Content-Type: application/json
```
Receives SMS delivery status updates from AWS SNS (via SNS delivery-status logging forwarded by a Lambda bridge). Authenticated by an HMAC-SHA256 signature over the raw request body in the `X-MIH-Signature` header (shared secret `AWS_SNS_DELIVERY_WEBHOOK_SECRET`, constant-time compare). Fail-closed: returns 403 for all requests until the secret is configured.

## Session Statuses

Sessions follow this lifecycle: `active` → `completed` (on-time check-in), or `active` → `missed` → `alerted` → `completed` (marked safe) / `cancelled` (admin closed it as a false alarm).

| Status | Description |
|--------|-------------|
| `active` | Session in progress, user hasn't checked in yet |
| `missed` | Past deadline + grace period, circle being notified |
| `alerted` | At least one circle member's alert SMS was accepted by the provider |
| `completed` | User checked in or marked safe |
| `cancelled` | An admin closed a missed/alerted session as a false alarm (no all-clear is sent) |

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Email or phone number already registered"
}
```

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "You can only complete your own sessions"
}
```

### 404 Not Found
```json
{
  "detail": "Session not found"
}
```

### 422 Validation Error
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "invalid email format",
      "type": "value_error"
    }
  ]
}
```

## WebSocket Events (Future)

### Connect
```javascript
ws://localhost:8000/ws/{user_id}?token={access_token}
```

### Events
- `session.reminder` - Reminder notification
- `session.overdue` - Check-in overdue alert
- `circle.invitation` - New Circle invitation
- `alert.new` - New alert created

## Rate Limits

- Global default: 60 requests per minute per IP (`RATE_LIMIT_DEFAULT`, slowapi; disabled in the test environment)
- `POST /auth/request-otp` and `POST /auth/resend-otp`: 5 requests per minute per IP

## Testing with cURL

### Authenticate via OTP
```bash
# Request OTP (code appears in backend console in dev mode)
curl -X POST http://localhost:8000/api/v1/auth/request-otp \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+14155552671"}'

# Verify OTP
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+14155552671", "otp_code": "123456"}'

# Save the access token from the response
TOKEN="your-access-token"
```

### Create Session
```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_type": "checkin",
    "expected_return_time": "'$(date -u -d "+2 hours" '+%Y-%m-%dT%H:%M:%S')'",
    "destination": "Testing the API",
    "location_sharing_enabled": false
  }'
```

### Complete Session
```bash
curl -X PUT http://localhost:8000/api/v1/sessions/{session_id}/complete \
  -H "Authorization: Bearer $TOKEN"
```
