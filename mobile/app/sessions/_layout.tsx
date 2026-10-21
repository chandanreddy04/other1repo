import { Stack } from 'expo-router'

/**
 * `/sessions` is its own navigator boundary (frontend-conventions.md
 * "Register nested routes"): the root Stack references the folder, not its
 * individual files, so index/new/[id]/active don't need to be declared in
 * app/_layout.tsx. The root DOES declare `name="sessions"` with
 * `headerShown: false` — this nested Stack's options can't hide the root
 * Stack's header for the folder entry.
 */
export default function SessionsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />
}
