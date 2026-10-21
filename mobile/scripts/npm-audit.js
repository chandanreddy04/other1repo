#!/usr/bin/env node
/**
 * Mobile dependency audit gate: `npm audit` at high/critical, with a dated,
 * self-policing allowlist for advisories that have NO fixed release.
 *
 * `npm audit --audit-level=high` has no ignore mechanism, so one unfixable
 * transitive advisory (image-size under metro, 2026-09) would keep CI red for
 * months and train everyone to ignore the job. This wrapper parses
 * `npm audit --json` and fails on any high/critical advisory that is not in
 * npm-audit-allowlist.json — and ALSO fails when an allowlist entry is past
 * its `review_by` date, or when npm no longer reports it (upstream fixed it),
 * so an exception can never rot silently in either direction.
 *
 * Packages npm marks high only because they sit above an allowlisted advisory
 * (expo → metro → image-size) are resolved by walking their `via` chain to the
 * underlying advisories; a high package with no reachable high/critical
 * advisory fails closed.
 *
 * Related: ../npm-audit-allowlist.json, Makefile `mobile-audit`,
 * .github/workflows/ci.yml (Mobile job), scripts/npm-audit.test.js.
 */

const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const MOBILE_DIR = path.join(__dirname, '..')
const ALLOWLIST_PATH = path.join(MOBILE_DIR, 'npm-audit-allowlist.json')
const GATED = new Set(['high', 'critical'])
const REQUIRED_FIELDS = ['id', 'package', 'reason', 'added', 'review_by']

function advisoryId(via) {
  return via.url ? via.url.split('/').pop() : String(via.source)
}

/** High/critical advisory ids reachable from a package through its `via` chain. */
function advisoriesReachableFrom(name, vulns, seen = new Set()) {
  const ids = new Set()
  if (seen.has(name) || !vulns[name]) return ids
  seen.add(name)
  for (const via of vulns[name].via || []) {
    if (typeof via === 'string') {
      for (const id of advisoriesReachableFrom(via, vulns, seen)) ids.add(id)
    } else if (GATED.has(via.severity)) {
      ids.add(advisoryId(via))
    }
  }
  return ids
}

function validateAllowlist(allow) {
  const problems = []
  for (const entry of allow) {
    for (const f of REQUIRED_FIELDS) {
      if (!entry[f]) problems.push(`entry ${entry.id || '?'} is missing "${f}"`)
    }
    if (entry.review_by && Number.isNaN(Date.parse(entry.review_by))) {
      problems.push(`entry ${entry.id} has an unparseable review_by "${entry.review_by}"`)
    }
  }
  return problems
}

/**
 * Pure evaluation of an `npm audit --json` report against the allowlist.
 * Returns { failing, used, expired, stale }:
 *   failing — gated packages with at least one advisory not on the allowlist
 *   used    — allowlist ids that currently suppress a gated finding
 *   expired — allowlist ids whose review_by is before `today`
 *   stale   — allowlist ids that suppress nothing (npm no longer reports them)
 */
function evaluateAudit(report, allow, today = new Date()) {
  const allowIds = new Set(allow.map(a => a.id))
  const vulns = report.vulnerabilities || {}
  const failing = []
  const used = new Set()

  for (const [name, v] of Object.entries(vulns)) {
    if (!GATED.has(v.severity)) continue
    const ids = advisoriesReachableFrom(name, vulns)
    const unallowed = [...ids].filter(id => !allowIds.has(id))
    if (ids.size === 0) {
      failing.push({ name, severity: v.severity, advisories: ['<no advisory id reachable — failing closed>'] })
    } else if (unallowed.length) {
      failing.push({ name, severity: v.severity, advisories: unallowed })
    } else {
      ids.forEach(id => used.add(id))
    }
  }

  const expired = allow.filter(a => new Date(a.review_by) < today).map(a => a.id)
  const stale = allow.filter(a => !used.has(a.id)).map(a => a.id)
  return { failing, used: [...used], expired, stale }
}

function runNpmAudit() {
  // npm exits 1 whenever any vulnerability exists; only the JSON matters here.
  const res = spawnSync('npm', ['audit', '--json'], {
    cwd: MOBILE_DIR,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
  let report
  try {
    report = JSON.parse(res.stdout)
  } catch {
    throw new Error(`npm audit produced no JSON (registry unreachable?):\n${res.stderr || res.stdout}`)
  }
  if (report.error) throw new Error(`npm audit error: ${JSON.stringify(report.error)}`)
  return report
}

function main() {
  const { allow } = JSON.parse(fs.readFileSync(ALLOWLIST_PATH, 'utf8'))
  const problems = validateAllowlist(allow)
  if (problems.length) {
    console.error(`✗ npm-audit-allowlist.json is malformed:\n  ${problems.join('\n  ')}`)
    process.exit(1)
  }

  const report = runNpmAudit()
  const { failing, used, expired, stale } = evaluateAudit(report, allow)
  const byId = new Map(allow.map(a => [a.id, a]))

  for (const id of used) {
    const a = byId.get(id)
    console.log(`allowlisted ${id} (${a.package}, review by ${a.review_by}): ${a.reason}`)
  }

  let ok = true
  if (failing.length) {
    ok = false
    console.error('✗ high/critical advisories not on the allowlist:')
    for (const f of failing) console.error(`  ${f.name} (${f.severity}): ${f.advisories.join(', ')}`)
  }
  if (expired.length) {
    ok = false
    console.error(
      `✗ allowlist entries past their review_by — re-evaluate, then renew with a fresh reason or delete: ${expired.join(', ')}`
    )
  }
  if (stale.length) {
    ok = false
    console.error(
      `✗ allowlist entries npm audit no longer reports (upstream fixed it?) — delete them: ${stale.join(', ')}`
    )
  }

  const m = (report.metadata && report.metadata.vulnerabilities) || {}
  console.log(
    `npm audit: ${m.high || 0} high, ${m.critical || 0} critical, ${m.total || 0} total (below high is not gated)`
  )
  console.log(ok ? '✓ mobile audit passed' : '✗ mobile audit failed')
  process.exit(ok ? 0 : 1)
}

if (require.main === module) main()

module.exports = { advisoriesReachableFrom, evaluateAudit, validateAllowlist }
