const ALLOWED_STRIPE_HOSTS = [
  'checkout.stripe.com',
  'billing.stripe.com',
]

export function validateStripeUrl(url: string): string {
  const parsed = new URL(url)
  if (!ALLOWED_STRIPE_HOSTS.includes(parsed.hostname)) {
    throw new Error(`Unexpected checkout host: ${parsed.hostname}`)
  }
  return url
}
