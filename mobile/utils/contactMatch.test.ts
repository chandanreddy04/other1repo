import {
  digitsOnly,
  isValidMatchNumber,
  numberMatchesCircle,
  isAddableContact,
  shouldPromptContacts,
} from './contactMatch'

describe('digitsOnly', () => {
  it('strips all non-digits', () => {
    expect(digitsOnly('+1 (415) 555-0101')).toBe('14155550101')
    expect(digitsOnly('415.555.0101')).toBe('4155550101')
    expect(digitsOnly('')).toBe('')
  })
})

describe('isValidMatchNumber', () => {
  it('accepts only 10 or 11 digit numbers', () => {
    expect(isValidMatchNumber('4155550101')).toBe(true) // 10
    expect(isValidMatchNumber('+14155550101')).toBe(true) // 11
    expect(isValidMatchNumber('555-0101')).toBe(false) // 7
    expect(isValidMatchNumber('+441632960961')).toBe(false) // 12 (UK)
    expect(isValidMatchNumber('')).toBe(false)
  })
})

describe('numberMatchesCircle (containment, not suffix)', () => {
  const circle = ['+14155550101'] // digits 14155550101

  it('matches a national contact number as a substring of E164', () => {
    expect(numberMatchesCircle('(415) 555-0101', circle)).toBe(true)
  })

  it('matches an 11-digit contact number that equals the circle digits', () => {
    expect(numberMatchesCircle('14155550101', circle)).toBe(true)
  })

  it('does not match a different number', () => {
    expect(numberMatchesCircle('4155550102', circle)).toBe(false)
  })

  it('rejects invalid-length contact numbers even if contained', () => {
    // "5550101" (7) is contained in the circle digits but isn't a valid length
    expect(numberMatchesCircle('555-0101', circle)).toBe(false)
  })
})

describe('isAddableContact', () => {
  const circle = ['+14155550101', '+14155550102']

  it('is addable when no number is in the circle', () => {
    expect(isAddableContact(['415-555-9999'], circle)).toBe(true)
  })

  it('is NOT addable when any number matches the circle', () => {
    expect(isAddableContact(['415-555-0101', '415-555-9999'], circle)).toBe(
      false
    )
  })

  it('is NOT addable with only invalid numbers (can not invite)', () => {
    expect(isAddableContact(['x', '555-0101'], circle)).toBe(false)
  })

  it('is NOT addable with no numbers', () => {
    expect(isAddableContact([], circle)).toBe(false)
  })
})

describe('shouldPromptContacts', () => {
  const circleNumbers = ['+14155550101']

  it('is false when the circle is full', () => {
    expect(
      shouldPromptContacts({
        memberCount: 10,
        maxMembers: 10,
        circleNumbers,
        accessibleContacts: [{ phoneNumbers: ['415-555-9999'] }],
      })
    ).toBe(false)
  })

  it('is false when there is an addable contact (access is not the bottleneck)', () => {
    expect(
      shouldPromptContacts({
        memberCount: 1,
        maxMembers: 10,
        circleNumbers,
        accessibleContacts: [{ phoneNumbers: ['415-555-9999'] }],
      })
    ).toBe(false)
  })

  it('is true when there is room but no accessible contact is addable (denied → 0 visible)', () => {
    expect(
      shouldPromptContacts({
        memberCount: 1,
        maxMembers: 10,
        circleNumbers,
        accessibleContacts: [],
      })
    ).toBe(true)
  })

  it('is true when every visible contact is already in the circle (Limited hiding the rest)', () => {
    expect(
      shouldPromptContacts({
        memberCount: 1,
        maxMembers: 10,
        circleNumbers,
        accessibleContacts: [{ phoneNumbers: ['(415) 555-0101'] }],
      })
    ).toBe(true)
  })
})
