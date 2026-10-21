import { profileScreenMode } from './profileScreenMode'

describe('profileScreenMode', () => {
  it('is required when the ?required=1 param is set, regardless of user', () => {
    expect(profileScreenMode({ full_name: 'Jane' }, '1')).toBe('required')
    expect(profileScreenMode(null, '1')).toBe('required')
  })

  it('is required when the user has no name yet, param or not', () => {
    expect(profileScreenMode(null, undefined)).toBe('required')
    expect(profileScreenMode(undefined, undefined)).toBe('required')
    expect(profileScreenMode({ full_name: null }, undefined)).toBe('required')
    expect(profileScreenMode({ full_name: '' }, undefined)).toBe('required')
    expect(profileScreenMode({ full_name: '   ' }, undefined)).toBe('required')
  })

  it('is edit for a named user with no required param', () => {
    expect(profileScreenMode({ full_name: 'Jane' }, undefined)).toBe('edit')
  })

  it('ignores a non-"1" param value and falls back to the user', () => {
    expect(profileScreenMode({ full_name: 'Jane' }, '0')).toBe('edit')
    expect(profileScreenMode(null, '0')).toBe('required')
  })

  it('takes the first value when the param arrives as an array', () => {
    expect(profileScreenMode({ full_name: 'Jane' }, ['1', '1'])).toBe(
      'required'
    )
    expect(profileScreenMode({ full_name: 'Jane' }, ['0'])).toBe('edit')
  })
})
