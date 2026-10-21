import { simpleState, locationState } from './permissions'

describe('simpleState (contacts / notifications)', () => {
  it('maps granted → granted', () => {
    expect(simpleState({ status: 'granted' })).toBe('granted')
  })
  it('maps undetermined → undetermined', () => {
    expect(simpleState({ status: 'undetermined' })).toBe('undetermined')
  })
  it('maps denied → denied', () => {
    expect(simpleState({ status: 'denied' })).toBe('denied')
  })
})

describe('locationState (Always required)', () => {
  it('background granted → granted (regardless of fg)', () => {
    expect(
      locationState({ status: 'granted' }, { status: 'granted' })
    ).toBe('granted')
  })
  it('foreground granted + background still promptable → undetermined', () => {
    expect(
      locationState(
        { status: 'granted' },
        { status: 'undetermined', canAskAgain: true }
      )
    ).toBe('undetermined')
  })
  it('foreground granted + background not promptable → insufficient', () => {
    expect(
      locationState(
        { status: 'granted' },
        { status: 'undetermined', canAskAgain: false }
      )
    ).toBe('insufficient')
  })
  it('foreground granted + background denied → insufficient', () => {
    expect(
      locationState({ status: 'granted' }, { status: 'denied' })
    ).toBe('insufficient')
  })
  it('foreground undetermined → undetermined', () => {
    expect(
      locationState({ status: 'undetermined' }, { status: 'undetermined' })
    ).toBe('undetermined')
  })
  it('foreground denied → denied', () => {
    expect(
      locationState({ status: 'denied' }, { status: 'denied' })
    ).toBe('denied')
  })
})
