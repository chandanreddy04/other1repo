import { getInitial } from './initials'

describe('getInitial', () => {
  it('returns the uppercased first letter of a name', () => {
    expect(getInitial('alice')).toBe('A')
    expect(getInitial('Bob')).toBe('B')
  })

  it('returns "?" for null/undefined/empty (no charAt-of-null crash)', () => {
    expect(getInitial(null)).toBe('?')
    expect(getInitial(undefined)).toBe('?')
    expect(getInitial('')).toBe('?')
    expect(getInitial('   ')).toBe('?')
  })

  it('ignores leading whitespace', () => {
    expect(getInitial('  charlie')).toBe('C')
  })
})
