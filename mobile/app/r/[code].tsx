// Universal-link landing for `madeitho.me/r/{code}`. iOS Universal
// Links / Android App Links route here when the app is installed; the
// browser fallback at /referrals/{code} on the backend handles the
// uninstalled case.
//
// The screen redirects to /referrals/new with the code pre-filled and an
// applyOnMount flag so the user just sees "Referral code applied" and
// is taken into the app — no manual paste.

import { useEffect } from 'react'
import { Redirect, useLocalSearchParams } from 'expo-router'

export default function ReferralShortLink() {
  const { code } = useLocalSearchParams<{ code: string }>()
  // useEffect placeholder so the file isn't completely declarative;
  // the redirect with params is the entire job.
  useEffect(() => {}, [])
  return (
    <Redirect
      href={{
        pathname: '/referrals/new',
        params: { code: (code ?? '').toUpperCase(), autoApply: '1' },
      }}
    />
  )
}
