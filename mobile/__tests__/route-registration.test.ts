/**
 * Structural guard for Expo Router route registration.
 *
 * Expo Router auto-registers FLAT route files (`app/foo.tsx`), so those are
 * reachable from the root Stack without an explicit declaration. A route in a
 * SUBFOLDER that has no `_layout.tsx` of its own (e.g. `app/session/[id].tsx`,
 * with no `app/session/_layout.tsx`) is NOT reachable from the root Stack
 * unless it is declared as `<Stack.Screen name="session/[id]" .../>` — and
 * neither tsc nor eslint can see the gap, so a `router.push('/session/…')`
 * silently goes nowhere. That exact dead-tap shipped once (History → session
 * summary). This test fails if such a nested route is left undeclared.
 *
 * Folders that own a `_layout.tsx` (`f/`, `r/`, `sessions/`, `account/`,
 * `referrals/`, `sponsorship-requests/`, `groups/`, `(tabs)`, `(auth)`) are
 * their own navigators — the root references the folder/group, not its files
 * — so their files are skipped by the first check; the second check requires
 * every non-group folder navigator itself to be declared in the root Stack
 * (so its root header can be hidden). Group folders (`(...)`) are skipped.
 *
 * IMPORTANT: this file lives OUTSIDE `app/` on purpose. Expo Router's
 * `require.context('./app', …)` sweeps every file under `app/` into the
 * production JS bundle, so a `.test.ts` there (importing Node `fs`/`path`)
 * breaks the Metro "Bundle JavaScript" build phase for every production build
 * (APK, Play AAB, iOS). Keep it here and reference `app/` via APP_DIR below.
 *
 * Related: app/_layout.tsx, .claude/rules/frontend-conventions.md
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'

const APP_DIR = join(__dirname, '..', 'app')

/** Every `name="…"` declared in the root Stack. */
function declaredScreenNames(): Set<string> {
  const layout = readFileSync(join(APP_DIR, '_layout.tsx'), 'utf8')
  const names = new Set<string>()
  for (const m of layout.matchAll(/name="([^"]+)"/g)) names.add(m[1])
  return names
}

/**
 * Route "names" (path relative to app/, sans extension) for every `.tsx`
 * route file reachable under `dir`, descending only into subfolders that do
 * NOT own a `_layout.tsx` (a folder layout is its own navigator boundary).
 */
function routeNamesIn(dir: string, prefix: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (existsSync(join(full, '_layout.tsx'))) continue
      out.push(...routeNamesIn(full, `${prefix}${entry}/`))
    } else if (entry.endsWith('.tsx') && entry !== '_layout.tsx') {
      out.push(`${prefix}${entry.replace(/\.tsx$/, '')}`)
    }
  }
  return out
}

describe('nested routes without a folder layout are registered in the root Stack', () => {
  const declared = declaredScreenNames()

  it('root _layout.tsx declares at least one screen', () => {
    expect(declared.size).toBeGreaterThan(0)
  })

  // Immediate subfolders of app/ that are neither groups nor own a layout —
  // these hold routes the root Stack must declare explicitly.
  const looseSubdirs = readdirSync(APP_DIR).filter(entry => {
    const full = join(APP_DIR, entry)
    return (
      statSync(full).isDirectory() &&
      !entry.startsWith('(') &&
      !existsSync(join(full, '_layout.tsx'))
    )
  })

  for (const dir of looseSubdirs) {
    for (const routeName of routeNamesIn(join(APP_DIR, dir), `${dir}/`)) {
      it(`declares "${routeName}" in app/_layout.tsx`, () => {
        expect([...declared]).toContain(routeName)
      })
    }
  }
})

// A folder that owns a `_layout.tsx` is its own navigator, but its nested
// stack's `headerShown: false` only covers the screens INSIDE it — the root
// Stack still renders its default header above the folder entry unless the
// root declares `<Stack.Screen name="<folder>" options={{ headerShown: false }} />`.
describe('folder navigators are declared in the root Stack (header hidden)', () => {
  const declared = declaredScreenNames()
  const folderNavigators = readdirSync(APP_DIR).filter(entry => {
    const full = join(APP_DIR, entry)
    return (
      statSync(full).isDirectory() &&
      !entry.startsWith('(') &&
      existsSync(join(full, '_layout.tsx'))
    )
  })

  it('finds at least one folder navigator', () => {
    expect(folderNavigators.length).toBeGreaterThan(0)
  })

  for (const dir of folderNavigators) {
    it(`declares "${dir}" in app/_layout.tsx`, () => {
      expect([...declared]).toContain(dir)
    })
  }
})
