# Claude Assistant Instructions for Made It Home

## Project Overview
Made It Home is a personal safety application that allows users to set check-in times and automatically alerts their Circle of Trust if they don't check in on time. The app uses phone-based OTP authentication and focuses on a friendly, approachable user experience.

## Tech Stack
### Backend (Python/FastAPI)
- **FastAPI** with async/await support
- **PostgreSQL** with SQLAlchemy 2.0
- **Alembic** for database migrations
- **Phone OTP Authentication** using SMS verification
- **phonenumbers** library for E164 phone validation
- **Twilio** for SMS/OTP delivery (console logging in dev mode), with **AWS SNS** as the failover provider (`SMS_FAILOVER_PROVIDER=sns` — the only supported value)
- **Cron worker** (`worker_tick.py`) for background tasks (session monitoring, alert retries, reminders)
- **Photo storage** on **AWS S3** (`STORAGE_BACKEND=s3` — the only supported value)
- **Stripe** for all subscriptions and sponsorship checkout (no IAP / RevenueCat)

### Mobile App (React Native/Expo)
- **Expo SDK 54** with React Native 0.81.5
- **TypeScript** for type safety
- **Expo Router** for file-based routing
- **Zustand** for state management
- **Custom Design System** with teal primary color (#14B8A6)

## Key Design Principles
1. **Phone-First**: The app uses phone numbers as the primary identifier, no email/password required
2. **Minimal Friction**: OTP-only authentication, no complex registration
3. **Friendly Tone**: Conversational copy like "What do your friends call you?"
4. **Clean UI**: Form elements directly on screen, no unnecessary card nesting
5. **Playful but Professional**: Rounded buttons, warm colors, friendly icons

## Surfaces by Role
One surface per role (owner decision 2026-09-23) — don't add a role's screens to another surface without an owner decision.
- **User** (session owner) → native app → `mobile/app/` (one web exception: `/account/delete`, which Google Play requires)
- **Circle member** → mobile web → `backend/app/web/templates/` (`routes_web.py`, e.g. `/alerts/{id}`, `/circles/{code}`)
- **Sponsor** → web → `backend/app/web/templates/` (`routes_web_sponsorships.py` for `/sponsorships`, sign-in links and the portal; `routes_web.py` for `/sponsorships/new` and the `/sponsorships/{share_code}` checkout routes)
- **Admin** → desktop web → `backend/app/web/templates/admin/` (`routes_admin.py`, `admin_registry.py`, `admin_views.py`)
- **Marketing** → marketing-site repo (separate repo, not this one)
- The app-download footer (`fragments/footer.html` via `base_web.html`) intentionally renders on the Circle-member and Sponsor pages (owner decision 2026-09-26) — reviewers must not flag it as marketing content

## Important Conventions

### General
- **DRY**: When two or more callers share the same logic, extract it into a CRUD method, service function, or helper
- **Normalize by default**: Every table should be in at least 3NF. Denormalization requires a measured performance need and a code comment
- **RESTful design**: URLs are nouns, HTTP methods are verbs. Resources over actions

Detailed conventions are in `.claude/rules/` (backend, frontend, domain, testing, security, admin, UI/UX).

## File Structure
- Backend models: `backend/app/models/`
- API endpoints: `backend/app/api/v1/endpoints/`
- CRUD operations: `backend/app/crud/`
- Services: `backend/app/services/`
- Schemas: `backend/app/schemas/`
- Web/Admin: `backend/app/web/`
- Mobile screens: `mobile/app/`
- Mobile components: `mobile/components/`
- Design system: `mobile/design_explorations/design-refined.html`

## Common Commands
### Backend
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
alembic upgrade head              # Run migrations
alembic revision -m "description" # Create migration
python -m pytest tests/ -v --asyncio-mode=auto  # Run tests
ruff check .                      # Lint
mypy app/ --config-file pyproject.toml  # Type check
python worker_tick.py              # Run worker tick manually
```

### Mobile
```bash
cd mobile
npm install
npx expo start
npx expo run:ios
npx expo run:android
npx tsc --noEmit                  # Type check
npx eslint 'app/**/*.{ts,tsx}'    # Lint
npm test                          # Unit tests (jest + jest-expo)
```

## Development Notes
- Backend API runs on http://localhost:8000
- API docs available at http://localhost:8000/docs
- Update `mobile/constants/index.ts` with your machine's IP for mobile testing
- OTP codes in dev mode appear in backend console as: `📱 OTP CODE FOR +14155552671: 123456`
- This is a personal safety app — reliability and simplicity are paramount. When in doubt, choose the simpler, more reliable solution
- Always prefer a library vs a manual implementation if the library has significant usage and popularity
- All push/SMS templates and their triggers: `docs/notifications.md`

## Production Infrastructure
- **CI/CD**: GitHub Actions — CI runs tests/lint on push and PRs. CD is **manual-only**: `.github/workflows/cd.yml`'s `workflow_run` auto-deploy-to-staging-on-master trigger has been commented out since 2026-07-02 (staging infra was torn down — every push would otherwise produce a guaranteed-failing deploy run), so master pushes no longer auto-deploy anything
- **Deployment**: **AWS only.** Both staging and production deploys are triggered by hand via `workflow_dispatch` (`.github/workflows/cd.yml` → `deploy-aws.yml`, choosing the target environment); restoring the commented-out `workflow_run` block is what would resume auto-deploying master to staging after CI.
  - Primary region `us-west-2`, DR data-only to `us-east-2` (no standing compute). `infra/aws/scripts/bootstrap.sh [staging|production]` provisions VPC + ECS Fargate + ALB + RDS + ECR + Secrets Manager (Terraform in `infra/aws/primary/`; state in `infra/aws/state-bootstrap/`). DB is RDS Postgres `db.t4g.medium` (production Multi-AZ, staging single-AZ; master password managed by RDS).
  - Full topology + runbooks + infra decisions: `docs/deployment.md`; AWS region-loss recovery: `docs/dr-runbook-aws.md`
- **Logging**: Structured JSON via `app.core.logging`. Request IDs via `X-Request-ID` header and `request_id_var` contextvar
- **Error tracking**: Bugsnag — backend (`BUGSNAG_API_KEY`; `app/core/error_reporting.py` attaches a root-logger handler so every `logger.error/exception/critical` reports, plus explicit reports for unhandled request exceptions and `HTTPException` 5xx; `app_version` = `GIT_SHA` baked into the image; a blank key refuses to boot in staging/production), mobile (`extra.bugsnag.apiKey` in app.config.js from `MOBILE_BUGSNAG_API_KEY`; `services/errorReporting.ts` starts synchronously in `app/_layout.tsx`; `services/api.ts` reports 5xx + throttled network failures; app.config.js refuses a keyless staging/production bundle). Only production/staging release stages deliver. Verify from dev: `BUGSNAG_API_KEY=… make error-reporting-smoke` (backend), `MOBILE_BUGSNAG_API_KEY=… npm run error-reporting:smoke` + the EnvBanner "test error reporting" link (mobile), and the admin dashboard "Send error-reporting test event" button after a deploy. All keys are declared in `infra/secrets/manifest.json` and distributed by `infra/aws/scripts/populate-secrets.sh` (Secrets Manager / EAS environments)
- **Rate limiting**: slowapi — global 60 req/min per IP, disabled in test env
- **Health checks**: `GET /health` (liveness), `GET /health/ready` (deep — DB check, returns 503 if degraded)
- **Background tasks**: `worker_loop.py` runs the tick every ~60s in a long-lived **ECS service** (`madeithome-worker-<env>`) — warm, so due notifications go out within seconds instead of paying a per-tick Fargate cold start. `worker_tick.py` (one tick, then exit) stays as the migrate one-off + manual/rollback entrypoint. A Postgres advisory lock in `run_tick_with_lock` guarantees only one tick runs at a time (safe across a rolling deploy's old+new task). Business logic in `app/services/session_tasks.py`. Test business logic directly with `db_session`

## Definition of Done

**All gates live in the root `Makefile` — the single source of truth shared by CI
and the local git pre-commit hook, so they cannot diverge.** A task is NOT complete until:
1. `make verify` passes — the full backend + mobile gate set (audit, lint, type
   check, tests + coverage, test-count ratchet). This is what the git pre-commit
   hook runs; run it yourself before committing, on a quiescent tree.
2. `make ci` passes for changes touching infra/Docker — adds the docker
   build + clean-tree check on top of `make verify`. It includes `repo-clean`,
   so run it only after committing.
3. New code has tests; `backend/tests/.min-test-count` is ratcheted up if tests were added.
4. No unintended file changes in `git status` (`make repo-clean`).
5. Run `/retro` — review changes, extract enforceable lessons, add new linter rules/tests/conventions.

Run `make help` to list every individual gate (e.g. `make backend-test`, `make mobile-lint`).

## Do Not (enforced)

These are hard rules enforced by hooks and deny rules — not suggestions.

- **Do not read or write `.env` files** — blocked by deny rules in `.claude/settings.json`
- **Do not modify existing test files without human approval** — enforced by PreToolUse hook on git-tracked files in `backend/tests/`. An owner-created marker (`.claude/.test-edits-approved`) can pre-approve a planned series; every edit it lets through is logged to `.claude/test-edits.log`, and a marker older than 24 hours is treated as absent
- **Do not delete or weaken tests to make code pass** — fix the code instead
- **Do not skip verification** — the git pre-commit hook (`.git/hooks/pre-commit`) runs `make verify` and aborts the commit on failure
- **Do not drop test count** — `make backend-testcount` / CI ratchet fails below `backend/tests/.min-test-count`
- **Do not drop coverage** — `make backend-test` / CI fails below `--cov-fail-under=84`

### Conventions (agent briefs)

Not hook-enforced — these hold because every agent brief carries them.

- **One working tree, current branch.** No `git stash`, `git worktree`, branch switches or `git checkout -- <path>`; to see the pre-change state use `git show HEAD:<path>` / `git diff`
- **Never run alembic against the dev database from an agent** (`alembic upgrade/downgrade`); migration correctness is checked inside the test suite. The owner migrates the dev DB
- **Only kill a process you started, by its recorded PID.** Never `pkill -f`/`killall` a bare pattern; if unavoidable, bracket the first character (`pkill -f '[u]vicorn app.main:app'`) so it can't match your own shell. Port 8000 is the owner's dev server; agent servers use another port
- **Gates run on a quiescent tree.** Never run `make verify`/`make ci` while another agent may be editing — a run that overlapped edits is void, not a failure. Before a commit run `make verify`; `make ci` (includes `repo-clean`) only after committing

## Verification Layers

The Makefile is the single source of truth; CI (`.github/workflows/ci.yml`) and the
local git pre-commit hook both invoke its targets, so local and CI run the **same gate set**.

### Claude Code hooks (`.claude/settings.json`)
- Only a **PreToolUse** hook on `Edit|Write` (`.claude/hooks/protect-baseline-tests.sh` — blocks edits to git-tracked `backend/tests/` files without approval). There is **no** Stop hook and **no** PostToolUse lint hook (removed in 4789399 and 03e7643) — nothing runs lint/types/tests automatically while an agent edits

### Git pre-commit (`.git/hooks/pre-commit`)
- A custom script that runs `make verify` and aborts the commit on failure, printing a bounded summary (full log in `$TMPDIR/mih-verify.*.log`). Bypass a known-broken WIP with `git commit --no-verify`. The tracked source is `scripts/git-hooks/pre-commit`; `make hooks-installed` (part of `make verify`, skipped in CI) installs it into `.git/hooks/pre-commit` whenever the two differ or the hook is missing
- `.pre-commit-config.yaml` is kept on disk but is not what the gate runs — don't run `pre-commit install`, it would replace the tracked hook; if revived, its hooks must invoke **Makefile targets**, never a restated command

### CI gates (all must pass on push — each job runs a `make` target)
- **Backend Tests** — `make backend-test` (pytest, `--cov-fail-under=84`) + `make backend-testcount`
- **Backend Audit** — `make backend-audit` (`pip-audit --strict`)
- **Backend Lint / Type Check** — `make backend-lint` (ruff + `scripts/check_except_blocks.py`: every except block reports or is `# benign:`) / `make backend-types`
- **Mobile** — `make mobile-audit` (`npm audit` high+ via `mobile/scripts/npm-audit.js`, with the dated, self-expiring allowlist in `mobile/npm-audit-allowlist.json`), `make mobile-tsc`, `make mobile-lint` (max 100 warnings; includes the local `swallowed-errors` rule — every catch reports or is `// benign:`), `make mobile-test` (jest)
- **Docker Build / Working Tree Clean** — `make docker-build` / `make repo-clean`

### When adding new code
- New endpoints: add tests in a NEW file in `backend/tests/`
- New models: import in `conftest.py` AND export from `app/models/__init__.py` — alembic autogenerate only sees what that package imports (`test_models_registry_complete.py`; `account_grants` was missing and autogenerate proposed dropping it), create migration, add tests
- Update `backend/tests/.min-test-count` when adding tests (ratchet up; lowering it is an owner-approved exception reserved for deleting a feature together with its tests — e.g. photo discovery, 2026-09-05)
- New Python files: add a module-level docstring with purpose and related files

## When Making Changes
1. Check existing patterns in the codebase first — reuse before creating
2. Follow the established design system (`design-refined.html` for UI work)
3. Maintain phone-first approach
4. Keep authentication simple (OTP only)
5. Ensure name is always required for new users
6. Test on both iOS and Android
7. Run migrations after model changes
8. Update API documentation if adding endpoints
9. After a plan is fully executed, push commits to remote
10. Removing a feature: delete its model/endpoints/tests together; add its identifiers to `backend/tests/test_removed_feature_tombstones.py`; sweep comments, `.claude/rules/` and `docs/` for the feature's *nouns*, not just its identifiers (an identifier grep missed "photo gallery"); re-home any invariant the deleted tests carried (a deleted class held a module's only non-admin check); run `/code-review` before committing
