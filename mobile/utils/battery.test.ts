import { getBatteryColor, getBatteryIcon, hasBatteryReading } from './battery'
import { COLORS } from '../constants'

describe('hasBatteryReading', () => {
  it('is false for null — no reading yet (the session-start "0%" bug)', () => {
    // last_battery_level arrives as JSON null until the first update lands;
    // `null !== undefined` used to slip through and render Math.round(0) = "0%".
    expect(hasBatteryReading(null)).toBe(false)
  })

  it('is false for undefined', () => {
    expect(hasBatteryReading(undefined)).toBe(false)
  })

  it('is true for a real level', () => {
    expect(hasBatteryReading(0.85)).toBe(true)
  })

  it('is true for a genuine 0 — a near-dead battery is a valid reading', () => {
    expect(hasBatteryReading(0)).toBe(true)
  })
})

describe('getBatteryIcon', () => {
  it('charging wins over level', () => {
    expect(getBatteryIcon(0.05, 'charging')).toBe('battery-charging')
  })

  it('full above 50%', () => {
    expect(getBatteryIcon(0.51)).toBe('battery-full')
  })

  it('half between 10% and 50%', () => {
    expect(getBatteryIcon(0.5)).toBe('battery-half')
    expect(getBatteryIcon(0.11)).toBe('battery-half')
  })

  it('dead at or below 10% — including a genuine 0', () => {
    expect(getBatteryIcon(0.1)).toBe('battery-dead')
    expect(getBatteryIcon(0)).toBe('battery-dead')
  })

  it('neutral half icon with no reading', () => {
    expect(getBatteryIcon(null)).toBe('battery-half')
    expect(getBatteryIcon(undefined)).toBe('battery-half')
  })
})

describe('getBatteryColor', () => {
  it('green above 50%', () => {
    expect(getBatteryColor(0.51)).toBe(COLORS.accent.green)
  })

  it('warning between 10% and 50%', () => {
    expect(getBatteryColor(0.5)).toBe(COLORS.warning)
  })

  it('danger at or below 10% — including a genuine 0', () => {
    expect(getBatteryColor(0.1)).toBe(COLORS.danger)
    expect(getBatteryColor(0)).toBe(COLORS.danger)
  })

  it('muted with no reading', () => {
    expect(getBatteryColor(null)).toBe(COLORS.textLight)
    expect(getBatteryColor(undefined)).toBe(COLORS.textLight)
  })
})
