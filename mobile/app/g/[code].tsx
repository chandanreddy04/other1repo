// Universal-link landing for `madeitho.me/g/{code}` (group-plan invite).
// AASA claims /g/* (reassigned from /f/, owner decision 2026-09-23 —
// nothing shipped with the old slug, so no alias) — only the in-app
// destination itself is here: a thin redirect shim to
// app/groups/[code].tsx.
import { Redirect, useLocalSearchParams } from 'expo-router'

export default function JoinGroupPlanRedirect() {
  const { code } = useLocalSearchParams<{ code: string }>()
  return <Redirect href={`/groups/${code}`} />
}
