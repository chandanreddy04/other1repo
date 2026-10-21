// Expo app config. Ported 1:1 from the former app.json so that secret-bearing
// `extra` values can be sourced from the environment instead of a committed file.
//
// `extra.bugsnag.apiKey` (the shape @bugsnag/expo and the EAS source-map plugin
// both read) is populated by infra/aws/scripts/populate-secrets.sh:
//   - local dev : mobile/.env (gitignored) -> process.env.MOBILE_BUGSNAG_API_KEY
//   - EAS builds/updates: the EAS environment bound to the eas.json profile
//     (`environment`) / passed to `eas update --environment` via the
//     `npm run update:<env>` scripts.
// See infra/secrets/manifest.json (the single source of truth).
//
// The staging/non-prod indicator is the in-app EnvBanner (components/
// EnvBanner.tsx), not a home-screen name change — the app name stays constant.

const APP_ENV = process.env.EXPO_PUBLIC_APP_ENV
const BUGSNAG_API_KEY = process.env.MOBILE_BUGSNAG_API_KEY ?? ''

// A bundle headed for devices — an EAS build (EAS_BUILD=true) or an
// export/OTA publish (Expo CLI bundles with NODE_ENV=production) — must know
// its environment and carry the Bugsnag key. A bare `eas update` leaves
// EXPO_PUBLIC_APP_ENV unset and the key empty; before 2026-09-06 that shipped
// with error reporting silently OFF for everyone who installed it. Refuse
// instead. `npx expo start` sets neither marker, so local dev is untouched;
// the `development` (dev-client) profile is exempt from the key.
const isDeviceBundle =
  process.env.EAS_BUILD === 'true' || process.env.NODE_ENV === 'production'
if (isDeviceBundle && APP_ENV !== 'development') {
  if (!['staging', 'production'].includes(APP_ENV)) {
    throw new Error(
      'EXPO_PUBLIC_APP_ENV must be staging or production for a build or update ' +
        '(got ' + APP_ENV + '). Use `npm run update:staging` / `npm run update:production`, ' +
        'or an eas.json profile bound to an EAS environment.'
    )
  }
  if (!BUGSNAG_API_KEY) {
    throw new Error(
      `MOBILE_BUGSNAG_API_KEY is empty for EXPO_PUBLIC_APP_ENV=${APP_ENV}. ` +
        'Builds take it from the EAS environment bound in eas.json; updates must ' +
        'go through `npm run update:staging` / `npm run update:production`.'
    )
  }
}

module.exports = {
  expo: {
    name: 'Made It Home',
    slug: 'made-it-home',
    // 1.4.0: universal-link claims changed (/g/, /sub, /plans, /subscription;
    // /c/ and /f/ dropped) + Time Sensitive entitlement removed — NATIVE
    // (intentFilters + an entitlement change both need a fresh build).
    // runtimeVersion follows appVersion, so this bump keeps this 1.4.0
    // bundle (no /f/ route) off 1.3.0 binaries that still claim /f/* — and
    // don't claim /g/ or /sub — so no OTA lands a mismatched pair.
    // 1.3.0: background photo discovery removed — NATIVE (the media-library
    // package unlinked, NSPhotoLibraryUsageDescription rewritten). runtimeVersion
    // follows appVersion, so this bump keeps the older 1.2.0 bundles (which
    // import that module at the top level) off binaries that no longer ship
    // it; needs a fresh EAS build + store release, not OTA.
    // 1.2.0: MapLibre trail maps — NATIVE module (@maplibre/maplibre-react-
    // native, replacing react-native-maps). runtimeVersion follows appVersion,
    // so this bump keeps the new JS (MapLibre components) off older binaries;
    // ship via a fresh EAS build + store release, not OTA. (1.1.0 was the
    // live-activity widget redesign — also native, also unshipped; both ride
    // the same build.)
    version: '1.4.0',
    orientation: 'portrait',
    owner: 'ragarwal6397',
    runtimeVersion: {
      policy: 'appVersion',
    },
    updates: {
      url: 'https://u.expo.dev/f6db40df-7218-47d2-a517-548cdb47f28e',
    },
    icon: './assets/images/icon.png',
    scheme: 'madeithome',
    userInterfaceStyle: 'automatic',
    newArchEnabled: true,
    splash: {
      image: './assets/images/splash-icon.png',
      resizeMode: 'contain',
      // Match the splash image's own teal background (#14B8A6, the app
      // primary). With resizeMode:'contain', any device whose aspect differs
      // from the image (1284x2778) gets letterbox bars filled with THIS color
      // — blue (#2563eb) made them show as jarring vertical borders on the
      // sides; teal blends them into the image seamlessly.
      backgroundColor: '#14B8A6',
    },
    ios: {
      supportsTablet: false,
      bundleIdentifier: 'com.madeithome.app',
      // Universal Links: iOS claims these hosts so madeitho.me/r/, /g/
      // (group-plan join, reassigned from /f/ — owner decision 2026-09-23,
      // nothing shipped with the old slug), /sub, /plans and /subscription
      // (and their s.madeitho.me staging equivalents) open the app
      // directly when installed — a user tap on a link does; a Stripe
      // return's script-driven redirect MAY (the /plans confirming step's
      // foreground re-check is the reliable unlock path). Hosts must also serve a valid AASA file
      // at /.well-known/apple-app-site-association — see the backend
      // route in app/api/v1/endpoints/well_known.py. The exact path set
      // is governed server-side there (UNIVERSAL_LINK_PATHS); iOS
      // associatedDomains are host-level only. Sponsorship checkout (/s/)
      // is intentionally NOT claimed (IAP rationale in well_known.py), and
      // neither is /c/ Circle invite — Circle members use mobile web only
      // (owner decision 2026-09-23), so there's no in-app accept screen to
      // route into.
      associatedDomains: [
        'applinks:madeitho.me',
        'applinks:s.madeitho.me',
      ],
      infoPlist: {
        NSCameraUsageDescription:
          'This app needs access to your camera to take photos of your outfit for check-ins.',
        NSPhotoLibraryUsageDescription:
          'Made It Home uses your photo library so you can choose an outfit photo for a session or a profile picture.',
        NSLocationWhenInUseUsageDescription:
          'This app needs access to your location to share it with your Circle of Trust during check-ins.',
        NSLocationAlwaysAndWhenInUseUsageDescription:
          'This app needs background location access to share your location with your Circle of Trust during active sessions.',
        NSSupportsLiveActivities: true,
        ITSAppUsesNonExemptEncryption: false,
      },
      backgroundColor: '#FAFBFC',
      // 'location' → the background location task (live trail during a session).
      // 'processing' → expo-background-task's BGTaskScheduler worker, used by the
      // SOS retry queue AND the opportunistic session gather (battery/location
      // when the location task isn't feeding updates). See services/sessionGather.ts.
      UIBackgroundModes: ['location', 'processing'],
    },
    android: {
      adaptiveIcon: {
        foregroundImage: './assets/images/adaptive-icon.png',
        // The foreground is an opaque teal tile (#14B8A6) with a white mark,
        // so this background only shows at the ~4% masked corners during the
        // launcher's shape/parallax. Teal (not blue) keeps that bleed
        // consistent with the tile and the rest of the brand.
        backgroundColor: '#14B8A6',
      },
      package: 'com.madeithome.app',
      // FCM config for remote push (Firebase project made-it-home-beffb).
      // The file is non-secret per Google docs; the FCM V1 service-account
      // key (the actual secret) lives in EAS credentials, never the repo.
      googleServicesFile: './google-services.json',
      permissions: [
        'CAMERA',
        'WRITE_EXTERNAL_STORAGE',
        'ACCESS_FINE_LOCATION',
        'android.permission.CAMERA',
        'android.permission.RECORD_AUDIO',
        'android.permission.ACCESS_COARSE_LOCATION',
        'android.permission.ACCESS_FINE_LOCATION',
      ],
      // App Links: same purpose as the iOS associatedDomains above.
      // autoVerify=true makes Android fetch /.well-known/assetlinks.json
      // at install time; failed verification falls back to the
      // browser/chooser dialog. Backend route lists the SHA-256 cert
      // fingerprints we sign with.
      //
      // Claimed: /r/ (referral, code-bearing pathPrefix), /g/ (group-plan
      // join, reassigned from /f/ — owner decision 2026-09-23, nothing
      // shipped with the old slug), and the codeless exact paths /sub (the
      // frozen lapse-SMS link, opens the paywall), /plans and /subscription
      // (the app's own Stripe checkout-return URLs on SHORT_DOMAIN — not
      // short links; a return MAY hand back to the app). Sponsorship checkout (/s/) is
      // intentionally NOT claimed here — see
      // backend/app/api/v1/endpoints/well_known.py for the IAP rationale;
      // it stays browser-only so Stripe checkout isn't pulled into the app
      // and tripped by Play Billing / StoreKit policy. /c/ Circle invite is
      // ALSO not claimed (owner decision 2026-09-23) — Circle members use
      // mobile web only, so there's no in-app accept screen to claim the
      // link into.
      intentFilters: [
        {
          action: 'VIEW',
          autoVerify: true,
          data: [
            { scheme: 'https', host: 'madeitho.me', pathPrefix: '/r/' },
            { scheme: 'https', host: 'madeitho.me', pathPrefix: '/g/' },
            { scheme: 'https', host: 'madeitho.me', path: '/sub' },
            { scheme: 'https', host: 'madeitho.me', path: '/plans' },
            { scheme: 'https', host: 'madeitho.me', path: '/subscription' },
            { scheme: 'https', host: 's.madeitho.me', pathPrefix: '/r/' },
            { scheme: 'https', host: 's.madeitho.me', pathPrefix: '/g/' },
            { scheme: 'https', host: 's.madeitho.me', path: '/sub' },
            { scheme: 'https', host: 's.madeitho.me', path: '/plans' },
            { scheme: 'https', host: 's.madeitho.me', path: '/subscription' },
          ],
          category: ['BROWSABLE', 'DEFAULT'],
        },
      ],
      edgeToEdgeEnabled: true,
    },
    web: {
      bundler: 'metro',
      output: 'static',
      favicon: './assets/images/favicon.png',
    },
    plugins: [
      'expo-router',
      'expo-updates',
      // MapLibre (session trail maps; OSM-based OpenFreeMap tiles, no Google
      // SDK / API key anywhere). NATIVE module — needs an EAS build.
      '@maplibre/maplibre-react-native',
      [
        'expo-camera',
        {
          cameraPermission:
            'Allow Made It Home to access your camera for outfit photos',
        },
      ],
      [
        'expo-notifications',
        {
          icon: './assets/images/notification-icon.png',
          // Teal accent (app primary) for the notification tint. The
          // notification icon is a white silhouette, so the tint just colors
          // it teal.
          color: '#14B8A6',
        },
      ],
      [
        'expo-location',
        {
          locationAlwaysAndWhenInUsePermission:
            'Allow Made It Home to track your location during check-ins.',
        },
      ],
      [
        'expo-contacts',
        {
          contactsPermission:
            'Allow Made It Home to access your contacts to add trusted people to your Circle of Trust.',
        },
      ],
      // EAS build hook (package.json `eas-build-on-success`) uploads Hermes
      // source maps so Bugsnag stack traces resolve; reads extra.bugsnag.apiKey.
      '@bugsnag/plugin-expo-eas-sourcemaps',
      'expo-localization',
      'expo-secure-store',
      'expo-live-activity',
    ],
    experiments: {
      typedRoutes: true,
    },
    extra: {
      router: {},
      bugsnag: { apiKey: BUGSNAG_API_KEY },
      eas: {
        projectId: 'f6db40df-7218-47d2-a517-548cdb47f28e',
      },
    },
  },
}
