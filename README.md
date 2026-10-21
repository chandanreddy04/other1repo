# Made It Home - Personal Safety Check-in App

A personal safety application that allows users to set check-in times and automatically alerts trusted contacts if they don't check in on time.

## Quick Start

```bash
# Backend (Terminal 1)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your values
createdb made_it_home
alembic upgrade head
uvicorn app.main:app --reload

# Mobile (Terminal 2)
cd mobile
npm install
npx expo start
```

Update `mobile/constants/index.ts` with your machine's IP for device testing.

## Tech Stack

### Mobile (Expo + React Native)
- Expo SDK 54 with React Native
- TypeScript, Expo Router, Zustand
- OTA updates via EAS Update

### Backend (Python/FastAPI)
- FastAPI with async/await, SQLAlchemy 2.0, PostgreSQL
- Redis for caching, Celery for background tasks
- Phone OTP authentication via Twilio
- Bugsnag error tracking, structured JSON logging

## Project Structure

```
made_it_home/
├── mobile/            # Expo React Native app
│   ├── app/           # Expo Router pages
│   ├── services/      # API and service layers
│   ├── store/         # Zustand state management
│   └── constants/     # App constants and design tokens
├── backend/           # FastAPI backend
│   ├── app/           # Application code
│   ├── alembic/       # Database migrations
│   └── tests/         # Test suite
└── .github/workflows/ # CI pipeline
```

## Backend Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Fill in your values
createdb made_it_home
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- Readiness check: http://localhost:8000/health/ready

In development, OTP codes print to the backend console instead of sending SMS.

## Mobile Setup

```bash
cd mobile
npm install
npx expo start
```

Update `mobile/constants/index.ts` with your machine's IP address so the app can reach the backend from a physical device.

## Testing

```bash
# Backend
cd backend && source venv/bin/activate
python -m pytest tests/ -v --asyncio-mode=auto

# Mobile type check
cd mobile
npx tsc --noEmit
```

## OTA Updates

The app uses [EAS Update](https://docs.expo.dev/eas-update/introduction/) for over-the-air updates. JS/TS changes ship instantly without going through App Store or Play Store review.

### What can be updated OTA
- UI changes, new screens, copy updates
- Bug fixes in JS/TS code
- API call changes, store logic, navigation

### What requires a new store build
- Adding or removing native modules
- Expo SDK version bumps
- Changes to `app.config.js` (permissions, splash screen, icons)
- Native config plugin changes

### Publishing an update

```bash
cd mobile
eas update --branch production --message "description of changes"
```

Users receive the update on next app launch.

### How it works
- `runtimeVersion` uses `appVersion` policy — updates are scoped to the `version` in `app.config.js`
- Each EAS build profile has a `channel` that maps to an update branch
- When you bump `version` for a native change, old builds stop receiving new OTA updates (they need the new store build)
- `expo-updates` checks for updates on app launch by default

### Building for stores

```bash
# Build for both platforms
eas build --platform all --profile production

# Submit to App Store / Play Store
eas submit --platform all
```

## CI

GitHub Actions runs on push to master and PRs:
- Backend tests (pytest with PostgreSQL)
- Backend lint (ruff)
- Mobile TypeScript check and ESLint

## License

This project is private and proprietary.
