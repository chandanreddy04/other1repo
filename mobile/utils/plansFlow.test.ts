import { plansStep } from './plansFlow'

describe('plansStep', () => {
  it('defaults to options with no checkout param', () => {
    expect(plansStep({})).toBe('options')
    expect(plansStep({ checkout: undefined })).toBe('options')
  })

  it('enters confirming on checkout=success', () => {
    expect(plansStep({ checkout: 'success' })).toBe('confirming')
  })

  it('enters canceled on checkout=canceled', () => {
    expect(plansStep({ checkout: 'canceled' })).toBe('canceled')
  })

  it('falls back to options for an unrecognized checkout value', () => {
    expect(plansStep({ checkout: 'bogus' })).toBe('options')
  })

  it('reads the first value when expo-router hands back an array param', () => {
    expect(plansStep({ checkout: ['success', 'canceled'] })).toBe('confirming')
  })
})
