#!/usr/bin/env node
/**
 * EAS `eas-build-on-success` hook — upload Android Hermes source maps to Bugsnag.
 *
 * Replaces `@bugsnag/plugin-expo-eas-sourcemaps`'s `bugsnag-eas-build-on-success`
 * binary, which invokes `bugsnag-cli upload react-native-android` with no control
 * over the CLI args. That bare call fails our Android build at the post-build
 * success hook (even though the APK/AAB is already built + uploaded) for two
 * reasons this wrapper fixes:
 *
 *   1. [FATAL] more than one variant found. Please specify using `--variant`
 *        → we pass `--variant=release`.
 *   2. [FATAL] missing required identifiers ("No AndroidManifest.xml located for
 *      variant release") → the CLI can't find the merged manifest to read the
 *        version, so we pass `--version-name` / `--version-code` ourselves.
 *
 * Version resolution matters for symbolication: the source map must be tagged
 * with the SAME versionCode the shipped app reports at crash time. EAS's remote
 * app-version source injects the real versionCode (e.g. 8) into the MERGED
 * manifest, NOT into android/app/build.gradle (which keeps the prebuild default
 * `1`). So we read the merged release AndroidManifest.xml first and only fall
 * back to build.gradle if it can't be found.
 *
 * A source-map upload is post-build telemetry, so a failure here is logged as a
 * WARNING and does NOT fail the build — the app binary is already produced, and
 * a symbolication-upload hiccup must never block shipping the artifact (that was
 * the repeated "build errored but the APK is fine" trap). iOS is a no-op here
 * (the upstream plugin skipped iOS too); development builds are skipped.
 *
 * Related: app.config.js (extra.bugsnag.apiKey), docs/mobile-release.md.
 */
/* eslint-disable no-console -- console output is this build hook's interface */
const { execFileSync } = require('child_process')
const { readFileSync, readdirSync } = require('fs')
const path = require('path')
const { getConfig } = require('@expo/config')

const PROJECT_ROOT = process.cwd()

if (process.env.EAS_BUILD_PLATFORM !== 'android') {
  console.log('Skipping Android source map upload: not an Android build')
  process.exit(0)
}
if (process.env.EAS_BUILD_PROFILE === 'development') {
  console.log('Skipping Android source map upload: development build')
  process.exit(0)
}

/** versionName/versionCode from android/app/build.gradle (fallback; versionCode is often the prebuild default). */
function versionFromGradle() {
  try {
    const gradle = readFileSync(
      path.join(PROJECT_ROOT, 'android', 'app', 'build.gradle'),
      'utf8'
    )
    return {
      versionName: gradle.match(/versionName\s+["']([^"']+)["']/)?.[1],
      versionCode: gradle.match(/versionCode\s+(\d+)/)?.[1],
    }
  } catch (error) {
    console.warn(`Could not read android/app/build.gradle: ${error.message}`)
    return {}
  }
}

/**
 * versionName/versionCode from the merged release AndroidManifest.xml — the
 * authoritative build values (EAS injects the remote versionCode here). Walks
 * android/app/build/intermediates for a release AndroidManifest.xml and picks
 * the one with the highest android:versionCode (the app module's, not a
 * library's). AGP-version-agnostic (the exact merged-manifest path varies).
 */
function versionFromMergedManifest() {
  const root = path.join(
    PROJECT_ROOT,
    'android',
    'app',
    'build',
    'intermediates'
  )
  const stack = [root]
  let best
  let iterations = 0
  while (stack.length && iterations < 20000) {
    iterations++
    const dir = stack.pop()
    let entries
    try {
      entries = readdirSync(dir, { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        stack.push(full)
      } else if (
        entry.name === 'AndroidManifest.xml' &&
        /release/i.test(full) &&
        !/debug/i.test(full)
      ) {
        let xml
        try {
          xml = readFileSync(full, 'utf8')
        } catch {
          continue
        }
        const code = xml.match(/android:versionCode="(\d+)"/)?.[1]
        if (!code) continue
        const codeNum = Number(code)
        if (!best || codeNum > best.codeNum) {
          best = {
            codeNum,
            versionCode: code,
            versionName: xml.match(/android:versionName="([^"]+)"/)?.[1],
            file: full,
          }
        }
      }
    }
  }
  return best
}

function resolveVersion() {
  const gradle = versionFromGradle()
  const merged = versionFromMergedManifest()
  if (merged) {
    console.log(
      `Version from merged manifest (${path.relative(PROJECT_ROOT, merged.file)}): ` +
        `${merged.versionName ?? gradle.versionName ?? '?'} (${merged.versionCode})`
    )
    return {
      versionName: merged.versionName || gradle.versionName,
      versionCode: merged.versionCode,
    }
  }
  console.warn(
    'Merged manifest not found; falling back to android/app/build.gradle ' +
      `(versionCode may be the prebuild default): ${gradle.versionName ?? '?'} (${gradle.versionCode ?? '?'})`
  )
  return gradle
}

let apiKey
try {
  apiKey = getConfig(PROJECT_ROOT)?.exp?.extra?.bugsnag?.apiKey
} catch (error) {
  console.warn(
    `Skipping source map upload: failed to read app config.\n${error}`
  )
  process.exit(0)
}
if (!apiKey) {
  console.warn('Skipping source map upload: no Bugsnag API key in app config')
  process.exit(0)
}

const { versionName, versionCode } = resolveVersion()
const cli = path.join(
  PROJECT_ROOT,
  'node_modules',
  '@bugsnag',
  'cli',
  'bin',
  'bugsnag-cli'
)

const args = [
  'upload',
  'react-native-android',
  `--api-key=${apiKey}`,
  `--project-root=${PROJECT_ROOT}`,
  '--variant=release',
]
if (versionName) args.push(`--version-name=${versionName}`)
if (versionCode) args.push(`--version-code=${versionCode}`)
args.push(PROJECT_ROOT)

console.log(
  `Uploading Android source map to Bugsnag ` +
    `(variant=release, version=${versionName ?? '?'} (${versionCode ?? '?'}))...`
)
try {
  execFileSync(cli, args, { stdio: 'inherit' })
  console.log('Successfully uploaded Android source map to Bugsnag.')
} catch (error) {
  // Non-fatal: never fail the build for a post-build telemetry upload.
  console.warn(
    `WARNING: Bugsnag source map upload failed; continuing (build not failed). ` +
      `${error.message}`
  )
  process.exit(0)
}
