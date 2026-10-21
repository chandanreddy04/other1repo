import { sanitizePhoneForSms } from './sms'

describe('sanitizePhoneForSms', () => {
  it('strips spaces, parens, dashes and dots, keeping a leading +', () => {
    // A device-contact number like this made the sms: URL malformed →
    // canOpenURL false → the surprise OS share sheet.
    expect(sanitizePhoneForSms('+1 (415) 555-1234')).toBe('+14155551234')
    expect(sanitizePhoneForSms('415.555.1234')).toBe('4155551234')
    expect(sanitizePhoneForSms('(415) 555-1234')).toBe('4155551234')
  })

  it('leaves an already-clean E.164 number unchanged', () => {
    expect(sanitizePhoneForSms('+14155551234')).toBe('+14155551234')
  })

  it('drops a trailing extension / letters', () => {
    expect(sanitizePhoneForSms('+1 415 555 1234 ext. 9')).toBe('+141555512349')
  })
})
