# Running Made It Home

## Local Development

### Prerequisites
- Docker and Docker Compose

### Start everything

```bash
docker compose up --build   # first time (builds the image)
docker compose up           # subsequent runs
```

This starts PostgreSQL, runs database migrations, and starts the backend with hot reload.

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

OTP codes appear in the backend container logs — no Twilio account needed:
```
📱 OTP CODE FOR +14155552671: 123456
```

### Testing with external services (Twilio, Stripe, etc.)

Add extra keys directly to the `environment` block in `docker-compose.yml`. The database URLs always point at the local postgres container regardless.

---

## Mobile App

### 1. Install dependencies
```bash
cd mobile
npm install
```

### 2. Point at your local backend

Edit `mobile/constants/config.ts` and set your machine's LAN IP in
`WEB_ORIGINS.development`:
```typescript
const WEB_ORIGINS = {
  development: 'http://YOUR_LOCAL_IP:8000',
  staging: 'https://staging-app.madeithomeapp.com',
  production: 'https://app.madeithomeapp.com',
} as const
```

Find your IP: `ip route get 1 | awk '{print $7}'` (Linux) or `ipconfig getifaddr en0` (macOS)

### 3. Start Expo
```bash
npx expo start
```

Press `i` for iOS simulator, `a` for Android emulator, or scan the QR code with Expo Go on a physical device.

### 4. Native / EAS builds

Which backend a build talks to is chosen at build time by `EXPO_PUBLIC_APP_ENV`,
set per profile in `mobile/eas.json`: `development` → local, `staging` →
`staging-app.madeithomeapp.com`, `production` → `app.madeithomeapp.com`. It's one
app/bundle ID — a `staging` build sent to internal TestFlight just points at the
staging backend (and shows a persistent **“STAGING APP”** banner in-app via
`components/EnvBanner.tsx`).

```bash
npm install -g eas-cli

# Dev client — local development on a physical device
eas build --profile development --platform ios

# Staging — internal TestFlight / Play internal testing (→ staging backend)
eas build  --profile staging    --platform ios
eas submit --profile production --platform ios   # same bundle ID / ASC app

# Production release
eas build  --profile production --platform ios
eas build  --profile production --platform android
eas submit --profile production --platform ios
eas submit --profile production --platform android
```

> Only promote **production** builds to the App Store; use **internal** TestFlight
> (no Apple review) for staging so testers never receive a staging-pointed public build.

---

## Deployment

### Staging

Happens automatically when CI passes on `master`. No manual action needed.

### Production

Manual trigger: GitHub → Actions → CD → Run workflow → select `production`.

### First-time setup

AWS infrastructure is managed via Terraform in `infra/aws/primary/` and provisioned by `infra/aws/scripts/bootstrap.sh`. See `docs/deployment.md` for the full runbook.

---

## Common Issues

**Backend won't start**
- Check postgres is healthy: `docker compose ps`
- View logs: `docker compose logs backend`
- Rebuild after dependency changes: `docker compose up --build`

**Cannot connect from mobile**
- Use your machine's LAN IP, not `localhost` — the phone is on a different network interface
- Ensure the backend port (8000) isn't blocked by a firewall

**OTP not showing**
- Check backend logs: `docker compose logs -f backend`

**Migration failed on startup**
- Check for conflicts: `docker compose logs backend | grep alembic`
- Connect directly: `docker compose exec postgres psql -U postgres made_it_home`
