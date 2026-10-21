import { getCircleMemberDisplayName } from './circleMemberName'

describe('getCircleMemberDisplayName', () => {
  it('prefers the resolved display_name', () => {
    expect(
      getCircleMemberDisplayName({
        display_name: 'Mom',
        nickname: 'Mommy',
        contact_full_name: 'Mary Smith',
      })
    ).toBe('Mom')
  })

  it('falls back to nickname, then the app-account name', () => {
    expect(getCircleMemberDisplayName({ nickname: 'Mom' })).toBe('Mom')
    expect(
      getCircleMemberDisplayName({ contact_full_name: 'Mary Smith' })
    ).toBe('Mary Smith')
  })

  it('never renders blank — the reported "no name" bug', () => {
    expect(getCircleMemberDisplayName({})).toBe('Contact')
    expect(
      getCircleMemberDisplayName({
        display_name: null,
        nickname: null,
        contact_full_name: null,
      })
    ).toBe('Contact')
    expect(getCircleMemberDisplayName({ display_name: '' })).toBe('Contact')
  })
})
