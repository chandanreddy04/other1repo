import { validateStripeUrl } from './validateStripeUrl'

// validateStripeUrl is a security control: external payment URLs from the
// backend are host-allowlisted before we open them, so a compromised/spoofed
// response can't redirect the user to a phishing host.
describe('validateStripeUrl', () => {
  it('allows the Stripe checkout + billing hosts', () => {
    const checkout = 'https://checkout.stripe.com/c/pay/cs_test_123'
    const billing = 'https://billing.stripe.com/p/session/abc'
    expect(validateStripeUrl(checkout)).toBe(checkout)
    expect(validateStripeUrl(billing)).toBe(billing)
  })

  it('rejects a non-Stripe host', () => {
    expect(() => validateStripeUrl('https://evil.example.com/pay')).toThrow(
      /Unexpected checkout host/
    )
  })

  it('rejects a look-alike host', () => {
    expect(() =>
      validateStripeUrl('https://checkout.stripe.com.evil.com/pay')
    ).toThrow(/Unexpected checkout host/)
  })

  it('throws on a malformed URL', () => {
    expect(() => validateStripeUrl('not a url')).toThrow()
  })
})
