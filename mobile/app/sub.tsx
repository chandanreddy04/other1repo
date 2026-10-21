// Universal-link landing for the frozen lapse-SMS link
// (`https://madeitho.me/sub` — see backend/app/services/
// sub_lapse_notifications.py, whose SMS text embedding this URL is
// frozen and NOT touched by this commit). The app now claims /sub itself
// and opens its own paywall directly (owner decision 2026-09-23),
// replacing the old marketing-site bounce.
import { Redirect } from 'expo-router'

export default function SubRedirect() {
  return <Redirect href="/plans" />
}
