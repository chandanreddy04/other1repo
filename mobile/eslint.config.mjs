import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

import swallowedErrorsRule from './eslint-rules/swallowed-errors.js'

export default [
  {
    ignores: [
      'node_modules/',
      'dist/',
      '.expo/',
      'web-build/',
      'babel.config.js',
      'tailwind.config.js',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    plugins: {
      react,
      'react-hooks': reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      '@typescript-eslint/explicit-module-boundary-types': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'react-hooks/refs': 'off',
    },
  },
  {
    // Native OS permission requests must originate from ONE module
    // (services/permissions.ts) so a system dialog can only appear from a
    // guided, foregrounded flow — never as a cold surprise. Everyone else uses
    // its wrappers (requestPermission, requestCameraPermission,
    // requestImagePickerMediaPermission).
    files: ['**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'CallExpression[callee.property.name=/^request(Permissions|ForegroundPermissions|BackgroundPermissions|CameraPermissions|MediaLibraryPermissions)Async$/]',
          message:
            'Call native permission requests only from services/permissions.ts. Use its wrappers (requestPermission / requestCameraPermission / requestImagePickerMediaPermission) instead.',
        },
        {
          // Names are functional, never vendor-bound: setErrorReportingUser,
          // not setBugsnagUser (the `Bugsnag` SDK import itself is fine).
          selector: 'Identifier[name=/^bugsnag[A-Z]|[a-z]Bugsnag/]',
          message:
            'Name this after what it does (error reporting), not the vendor behind it — the vendor is an implementation detail of services/errorReporting.ts.',
        },
      ],
    },
  },
  {
    // Every swallowed error is reported or explicitly benign (the mobile twin
    // of backend/scripts/check_except_blocks.py). Errors report through
    // services/errorReporting.ts notify(); a catch that is genuinely fine to
    // ignore says why in a `// benign: <reason>` comment inside the handler
    // (or on the line before it). console.error/warn inside a catch is not a
    // report — nobody watches a device console in production.
    // See .claude/rules/frontend-conventions.md.
    files: [
      'app/**/*.{ts,tsx}',
      'components/**/*.{ts,tsx}',
      'hooks/**/*.{ts,tsx}',
      'services/**/*.{ts,tsx}',
      'store/**/*.{ts,tsx}',
      'utils/**/*.{ts,tsx}',
    ],
    ignores: ['**/*.test.{ts,tsx}', 'services/errorReporting.ts'],
    plugins: { local: { rules: { 'swallowed-errors': swallowedErrorsRule } } },
    rules: { 'local/swallowed-errors': 'error' },
  },
  {
    // The single allowed home for native request* calls.
    files: ['services/permissions.ts'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  {
    // Node/CommonJS files (app.config.js, the local eslint rule, dev scripts)
    // run under Node, not the RN bundler — give them the Node globals they use.
    // `make mobile-lint` (pre-commit hook + CI) lints these too.
    files: [
      '*.config.js',
      'app.config.js',
      'eslint-rules/**/*.js',
      'scripts/**/*.js',
    ],
    languageOptions: {
      globals: {
        module: 'writable',
        require: 'readonly',
        process: 'readonly',
        __dirname: 'readonly',
        console: 'readonly',
        fetch: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
      },
    },
    rules: {
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
  {
    // Jest test files + setup: provide test globals and allow the CommonJS
    // require() that jest.mock factories use.
    files: ['**/*.test.{js,jsx,ts,tsx}', 'jest.setup.js'],
    languageOptions: {
      globals: {
        jest: 'readonly',
        describe: 'readonly',
        it: 'readonly',
        test: 'readonly',
        expect: 'readonly',
        beforeEach: 'readonly',
        afterEach: 'readonly',
        beforeAll: 'readonly',
        afterAll: 'readonly',
        require: 'readonly',
        module: 'writable',
      },
    },
    rules: {
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
]
