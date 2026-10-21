import { Stack } from 'expo-router'

// Folder navigator for the Group resource's join lander: [code].tsx (accept
// a group-plan invite). Nested stack hides its own headers; the root Stack
// additionally hides the folder entry's header (app/_layout.tsx).
export default function GroupsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />
}
