import { Stack } from 'expo-router'

// Folder navigator for the SponsorshipRequest resource: new.tsx (pick a
// contact to ask). Nested stack hides its own headers; the root Stack
// additionally hides the folder entry's header (app/_layout.tsx).
export default function SponsorshipRequestsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />
}
