const { evaluateAudit, validateAllowlist } = require('./npm-audit')

const advisory = (id, severity = 'high') => ({
  source: 1,
  url: `https://github.com/advisories/${id}`,
  severity,
  title: id,
})

// Shape of a real `npm audit --json` report: the leaf package carries the
// advisory objects; everything above it lists the package NAME it depends on.
const report = {
  vulnerabilities: {
    'image-size': { severity: 'high', via: [advisory('GHSA-leaf-1'), advisory('GHSA-leaf-2')] },
    metro: { severity: 'high', via: ['image-size'] },
    expo: { severity: 'high', via: ['metro', '@expo/config'] },
    // A moderate advisory further up must NOT make `expo` fail.
    '@expo/config': { severity: 'moderate', via: [advisory('GHSA-mod-1', 'moderate')] },
    xmldom: { severity: 'moderate', via: [advisory('GHSA-mod-2', 'moderate')] },
  },
}

const allow = (ids, review_by = '2099-01-01') =>
  ids.map(id => ({ id, package: 'x', reason: 'r', added: '2026-09-05', review_by }))

const today = new Date('2026-09-05')

describe('evaluateAudit', () => {
  it('passes when every reachable high advisory is allowlisted, walking the via chain', () => {
    const r = evaluateAudit(report, allow(['GHSA-leaf-1', 'GHSA-leaf-2']), today)
    expect(r.failing).toEqual([])
    expect(r.used.sort()).toEqual(['GHSA-leaf-1', 'GHSA-leaf-2'])
    expect(r.expired).toEqual([])
    expect(r.stale).toEqual([])
  })

  it('fails every package whose chain reaches an advisory that is not allowlisted', () => {
    const r = evaluateAudit(report, allow(['GHSA-leaf-1']), today)
    expect(r.failing.map(f => f.name).sort()).toEqual(['expo', 'image-size', 'metro'])
    expect(r.failing.find(f => f.name === 'expo').advisories).toEqual(['GHSA-leaf-2'])
  })

  it('never gates moderate findings', () => {
    const r = evaluateAudit(report, allow(['GHSA-leaf-1', 'GHSA-leaf-2']), today)
    expect(r.failing.map(f => f.name)).not.toContain('xmldom')
  })

  it('fails closed on a high package with no reachable advisory id', () => {
    const r = evaluateAudit({ vulnerabilities: { odd: { severity: 'high', via: [] } } }, [], today)
    expect(r.failing).toHaveLength(1)
    expect(r.failing[0].advisories[0]).toMatch(/failing closed/)
  })

  it('reports entries past their review_by date', () => {
    const r = evaluateAudit(report, allow(['GHSA-leaf-1', 'GHSA-leaf-2'], '2026-09-04'), today)
    expect(r.expired.sort()).toEqual(['GHSA-leaf-1', 'GHSA-leaf-2'])
  })

  it('reports entries that no longer suppress anything (upstream fixed it)', () => {
    const r = evaluateAudit(report, allow(['GHSA-leaf-1', 'GHSA-leaf-2', 'GHSA-gone']), today)
    expect(r.stale).toEqual(['GHSA-gone'])
  })
})

describe('validateAllowlist', () => {
  it('requires id, package, reason, added and a parseable review_by', () => {
    expect(validateAllowlist(allow(['GHSA-x']))).toEqual([])
    expect(validateAllowlist([{ id: 'GHSA-y', review_by: 'soon' }])).toEqual(
      expect.arrayContaining([expect.stringContaining('missing "package"'), expect.stringContaining('unparseable')])
    )
  })
})
