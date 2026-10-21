import { describeGaps, permissionGaps } from './permissionGaps'

describe('permissionGaps', () => {
  it('reports no gaps when everything is fully granted', () => {
    expect(
      permissionGaps({
        notifications: 'granted',
        location: 'granted',
      })
    ).toEqual([])
  })

  it('treats never-asked (undetermined) as a gap', () => {
    expect(
      permissionGaps({
        notifications: 'undetermined',
        location: 'undetermined',
      })
    ).toEqual(['notifications', 'location'])
  })

  it('treats denied as a gap', () => {
    expect(
      permissionGaps({
        notifications: 'denied',
        location: 'granted',
      })
    ).toEqual(['notifications'])
  })
})

describe('describeGaps', () => {
  it('spells out the single permission when exactly one is pending', () => {
    expect(describeGaps(['location'])).toBe(
      'Location access is still needed so we can keep you safe during a session.'
    )
  })

  it('uses a count (not names) when more than one is pending', () => {
    expect(describeGaps(['notifications', 'location'])).toBe(
      '2 permissions are still needed so we can keep you safe during a session.'
    )
  })
})
