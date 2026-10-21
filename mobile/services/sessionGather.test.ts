import { planGather } from './sessionGather'

describe('planGather', () => {
  it('always gathers battery, regardless of the toggle or permission', () => {
    expect(
      planGather({ locationSharing: false }, { locationSufficient: false })
        .battery
    ).toBe(true)
  })

  it('gathers location only when shared AND permission is sufficient', () => {
    expect(
      planGather({ locationSharing: true }, { locationSufficient: true })
        .location
    ).toBe(true)
    // toggle off
    expect(
      planGather({ locationSharing: false }, { locationSufficient: true })
        .location
    ).toBe(false)
    // permission insufficient
    expect(
      planGather({ locationSharing: true }, { locationSufficient: false })
        .location
    ).toBe(false)
  })

  it('gathers everything when the toggle is on and permission is sufficient', () => {
    expect(
      planGather({ locationSharing: true }, { locationSufficient: true })
    ).toEqual({ battery: true, location: true })
  })
})
