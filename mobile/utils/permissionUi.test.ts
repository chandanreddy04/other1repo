import { sessionRequirementItems, requirementCta } from './permissionUi'
import type { PermissionStatus } from '../services/permissions'

const gap = (
  key: PermissionStatus['key'],
  state: PermissionStatus['state']
): PermissionStatus => ({ key, state, sufficient: false })

describe('sessionRequirementItems', () => {
  it('maps every session gap to a loud (warning) row, preserving order', () => {
    const items = sessionRequirementItems([
      gap('location', 'undetermined'),
      gap('notifications', 'denied'),
    ])
    expect(items.map(i => [i.status.key, i.severity])).toEqual([
      ['location', 'warning'],
      ['notifications', 'warning'],
    ])
  })
  it('returns nothing when there are no gaps', () => {
    expect(sessionRequirementItems([])).toEqual([])
  })
})

describe('requirementCta', () => {
  it('undetermined can be granted in-app (allow)', () => {
    expect(requirementCta('undetermined')).toBe('allow')
  })
  it('insufficient/denied route to settings', () => {
    expect(requirementCta('insufficient')).toBe('settings')
    expect(requirementCta('denied')).toBe('settings')
  })
})
