/**
 * On-device PII redaction and the "reportable until actually reported"
 * contract of services/errorReporting.ts. Module state starts NOT started here
 * (nothing calls startErrorReporting), which is the point of the last test.
 */

import type { Event } from '@bugsnag/core'
import { notify, redactPhones, scrubEvent, wasReported } from './errorReporting'

describe('redaction', () => {
  it('replaces E.164 numbers wherever they appear in a string', () => {
    expect(
      redactPhones(
        'Unable to open URL: sms:+14155551234&body=hi from +447700900123'
      )
    ).toBe('Unable to open URL: sms:[PHONE]&body=hi from [PHONE]')
    expect(redactPhones('attempt 3 of 6 at 2026-09-06')).toBe(
      'attempt 3 of 6 at 2026-09-06'
    )
  })

  it('scrubs every text field of an event before delivery', () => {
    const event = {
      errors: [{ errorMessage: 'Twilio: +14155551234 is not valid' }],
      context: 'sms +14155551234',
      groupingHash: 'send:+14155551234',
      breadcrumbs: [
        {
          message: 'invited +14155551234',
          metadata: { to: '+14155551234', n: 2 },
        },
      ],
    } as unknown as Event
    expect(scrubEvent(event)).toBe(true)
    expect(event.errors[0].errorMessage).toBe('Twilio: [PHONE] is not valid')
    expect(event.context).toBe('sms [PHONE]')
    expect(event.groupingHash).toBe('send:[PHONE]')
    expect(event.breadcrumbs[0].message).toBe('invited [PHONE]')
    expect(event.breadcrumbs[0].metadata).toEqual({ to: '[PHONE]', n: 2 })
  })
})

describe('before the client has started', () => {
  it('does not mark an error reported, so it stays reportable once started', () => {
    const err = new Error('early')
    notify(err, 'boot.early')
    expect(wasReported(err)).toBe(false)
  })
})
