import { Redirect } from 'expo-router'

// Any URL the app doesn't route (a stale or mistyped deep link) goes to the
// launch router, which sends the user to the right place, instead of Expo
// Router's default "Unmatched Route" screen.
export default function NotFound() {
  return <Redirect href="/" />
}
