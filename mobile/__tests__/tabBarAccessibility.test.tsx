/**
 * Structural guard for tab-bar accessibility labels.
 *
 * @testing-library/react-native is not installed in this project (confirmed
 * absent from mobile/package.json and node_modules). A full `react-test-
 * renderer` mount was tried and ruled out too: even a bare `<Text>hi</Text>`
 * renders to a `null` tree under this project's jest-expo + React 19 combo
 * (no existing test in the repo renders a React component for exactly this
 * reason — every other mobile test either exercises pure logic or, like
 * route-registration.test.ts, reads source statically).
 *
 * So this proves the labels actually reach the elements the same way
 * route-registration.test.ts proves route wiring: by reading the source and
 * asserting the accessibility props sit on the right JSX element, instead of
 * trusting an options object nothing is shown to read.
 *
 * Related: app/(tabs)/_layout.tsx (tabBarAccessibilityLabel per screen),
 * components/navigation/CustomTabBar.tsx (reads options.tabBarAccessibility
 * Label for the Home/Circle/Account buttons; the SOS button is hand-built,
 * not a Tabs.Screen, so it carries its own literal accessibility props).
 */
import { readFileSync } from 'fs'
import { join } from 'path'

const LAYOUT_PATH = join(__dirname, '..', 'app', '(tabs)', '_layout.tsx')
const TAB_BAR_PATH = join(
  __dirname,
  '..',
  'components',
  'navigation',
  'CustomTabBar.tsx'
)

describe('(tabs)/_layout.tsx tab labels', () => {
  const source = readFileSync(LAYOUT_PATH, 'utf8')

  // One block per <Tabs.Screen name="..." options={{ ... }} /> — DOTALL so
  // the options body (title + tabBarAccessibilityLabel on separate lines)
  // matches.
  const screens = [
    ...source.matchAll(/<Tabs\.Screen\s+name="([^"]+)"\s+options=\{\{([\s\S]*?)\}\}/g),
  ]

  it('declares exactly the three tabs', () => {
    expect(screens.map(([, name]) => name)).toEqual(['index', 'circle', 'account'])
  })

  it.each([
    ['index', 'Home'],
    ['circle', 'Circle'],
    ['account', 'Account'],
  ])('%s carries tabBarAccessibilityLabel %j matching its title', (name, label) => {
    const match = screens.find(([, screenName]) => screenName === name)
    expect(match).toBeTruthy()
    const optionsBody = match![2]

    const title = optionsBody.match(/title:\s*'([^']+)'/)?.[1]
    const accessibilityLabel = optionsBody.match(
      /tabBarAccessibilityLabel:\s*'([^']+)'/
    )?.[1]

    expect(title).toBe(label)
    expect(accessibilityLabel).toBe(label)
  })
})

describe('CustomTabBar forwards the per-tab label', () => {
  const source = readFileSync(TAB_BAR_PATH, 'utf8')

  // React Navigation's option key is `tabBarAccessibilityLabel`; the custom
  // bar must read it off `options` for both tab-button render branches, or
  // the labels declared in _layout.tsx never reach a screen reader.
  it('reads options.tabBarAccessibilityLabel on both tab-button branches', () => {
    const reads = source.match(
      /accessibilityLabel=\{options\.tabBarAccessibilityLabel\}/g
    )
    expect(reads).toHaveLength(2)
  })
})

describe('CustomTabBar SOS button accessibility', () => {
  const source = readFileSync(TAB_BAR_PATH, 'utf8')

  // The SOS TouchableOpacity — identified by its onPressIn handler — up to
  // its opening tag's closing `>` (the style array's `]}` immediately
  // precedes it), so the assertions below only pass if the props sit on
  // that specific element (not merely somewhere in the file). A naive
  // `[\s\S]*?>` would stop early at the `=>` in onPressOut's arrow function.
  const match = source.match(
    /<TouchableOpacity\s+onPressIn=\{handleEmergencyStart\}[\s\S]*?\]\}\s*>/
  )

  it('is present in the tab bar', () => {
    expect(match).toBeTruthy()
  })

  const block = match![0]

  it('declares accessibilityRole="button"', () => {
    expect(block).toMatch(/accessibilityRole="button"/)
  })

  it('declares accessibilityLabel="SOS"', () => {
    expect(block).toMatch(/accessibilityLabel="SOS"/)
  })

  // SOS is press-and-hold (a 3-2-1 countdown), so the hint must name the
  // gesture — a screen-reader double-tap alone starts and immediately
  // cancels the countdown.
  it('declares an accessibilityHint naming the hold gesture and the SOS alert', () => {
    expect(block).toMatch(
      /accessibilityHint="Press and hold to send an SOS alert to your Circle of Trust"/
    )
  })
})
