#!/usr/bin/env node
/**
 * Prove MOBILE_BUGSNAG_API_KEY works from this machine before a build or an
 * OTA update: POST one test event straight to Bugsnag's notify API and check
 * the 200. No app, no simulator — a bad key fails here with the HTTP status.
 *
 *   MOBILE_BUGSNAG_API_KEY=<key> npm run error-reporting:smoke [-- --stage staging]
 *
 * The event lands under the chosen release stage (default staging) as
 * "BugsnagSmokeTest" with context scripts/error-reporting-smoke.js. In-app delivery is
 * verified separately by the EnvBanner "test error reporting" link (services/errorReporting.ts).
 *
 * Related: ../app.config.js (refuses a keyless staging/production bundle),
 * ../../backend/scripts/error_reporting_smoke.py (backend counterpart), docs/mobile-release.md.
 */

const os = require('node:os')

const key = process.env.MOBILE_BUGSNAG_API_KEY
if (!key) {
  process.stderr.write(
    '✗ MOBILE_BUGSNAG_API_KEY is not set in the environment.\n'
  )
  process.exit(2)
}
const stageIdx = process.argv.indexOf('--stage')
const stage = stageIdx === -1 ? 'staging' : process.argv[stageIdx + 1]
if (!['staging', 'production'].includes(stage)) {
  process.stderr.write(
    `✗ --stage must be staging or production (got ${stage})\n`
  )
  process.exit(2)
}
const version = require('../package.json').version

const payload = {
  apiKey: key,
  payloadVersion: '5',
  notifier: {
    name: 'made-it-home mobile smoke',
    version: '1.0.0',
    url: 'https://github.com/Hey-June-Inc/made-it-home',
  },
  events: [
    {
      exceptions: [
        {
          errorClass: 'BugsnagSmokeTest',
          message: 'mobile smoke test from a developer machine',
          stacktrace: [],
        },
      ],
      severity: 'info',
      unhandled: false,
      context: 'scripts/error-reporting-smoke.js',
      app: { releaseStage: stage, version },
      metaData: { smoke: { host: os.hostname(), stage } },
    },
  ],
}

fetch('https://notify.bugsnag.com/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Bugsnag-Api-Key': key,
    'Bugsnag-Payload-Version': '5',
  },
  body: JSON.stringify(payload),
})
  .then(async res => {
    if (res.ok) {
      process.stdout.write(
        `✓ Event accepted by Bugsnag — check the dashboard for release stage '${stage}' (BugsnagSmokeTest).\n`
      )
      process.exit(0)
    }
    process.stderr.write(
      `✗ Bugsnag rejected the event: HTTP ${res.status} ${await res.text()}\n`
    )
    process.exit(1)
  })
  .catch(err => {
    process.stderr.write(
      `✗ Could not reach notify.bugsnag.com: ${err.message}\n`
    )
    process.exit(1)
  })
