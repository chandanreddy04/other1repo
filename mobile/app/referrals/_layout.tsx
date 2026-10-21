import { Stack } from 'expo-router'

// Folder navigator for the Referral resource: index.tsx (share your code)
// and new.tsx (redeem a code). Nested stack hides its own headers; the root
// Stack additionally hides the folder entry's header (app/_layout.tsx).
export default function ReferralsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />
}
