# Single source of truth for every quality / security / build gate.
#
# Both CI (.github/workflows/ci.yml) and the local git pre-commit hook invoke these
# targets, so the two can never diverge: add or change a gate HERE once and
# both pick it up. The target set is the UNION of everything that used to run
# only locally OR only in CI.
#
#   make verify   — fast gate set (backend + mobile). Run before every commit
#                   on a quiescent tree; this is what the git pre-commit hook runs.
#   make ci       — the complete union: verify + docker builds + clean-tree check.
#                   This is the full set CI runs.
#
# Individual targets (backend-audit, mobile-tsc, …) exist so CI jobs can run
# them in parallel and so you can run one gate at a time locally.

.DEFAULT_GOAL := help
.ONESHELL:

# Resolve a backend interpreter: the project venv locally, PATH python in CI.
BACKEND_PY := $(if $(wildcard backend/venv/bin/python),$(abspath backend/venv/bin/python),python)

# ---- Install (used by CI jobs and for local bootstrap) ---------------------

install-backend: ## Install backend dependencies
	cd backend && $(BACKEND_PY) -m pip install -r requirements.txt

install-mobile: ## Install mobile dependencies (clean, lockfile-exact)
	cd mobile && npm ci

# ---- Backend gates ---------------------------------------------------------

backend-audit: ## Backend dependency vulnerability scan (pip-audit --strict)
	cd backend && $(BACKEND_PY) -m pip_audit --strict

backend-lint: ## Backend lint (ruff + every except block reports or is marked benign)
	cd backend && $(BACKEND_PY) -m ruff check . && $(BACKEND_PY) scripts/check_except_blocks.py

backend-types: ## Backend type check (mypy)
	cd backend && $(BACKEND_PY) -m mypy app/ --config-file pyproject.toml

backend-db-preflight: ## Fail fast with one line if the test DB is down (avoids a traceback flood)
	cd backend && $(BACKEND_PY) scripts/db_preflight.py

backend-test: backend-db-preflight ## Backend tests + coverage gate
	cd backend && $(BACKEND_PY) -m pytest tests/ -q --asyncio-mode=auto --tb=short \
		--disable-warnings \
		--cov=app --cov-config=.coveragerc --cov-report=term-missing:skip-covered \
		--cov-fail-under=84

error-reporting-smoke: ## Send 2 test events to Bugsnag from this machine: BUGSNAG_API_KEY=… make error-reporting-smoke [STAGE=staging]
	cd backend && BUGSNAG_API_KEY="$$BUGSNAG_API_KEY" $(BACKEND_PY) scripts/error_reporting_smoke.py --stage $(or $(STAGE),staging)

backend-testcount: ## Enforce the test-count ratchet
	cd backend && \
	CURRENT=$$($(BACKEND_PY) -m pytest tests/ --collect-only -q --asyncio-mode=auto 2>/dev/null | tail -1 | grep -oE '[0-9]+ tests?' | grep -oE '[0-9]+'); \
	MIN=$$(cat tests/.min-test-count 2>/dev/null || echo 0); \
	echo "Test count: $$CURRENT (minimum: $$MIN)"; \
	case "$$CURRENT" in ''|*[!0-9]*) echo "ERROR: could not read the collected test count (got '$$CURRENT') — did an addopts/verbosity change drop pytest's 'N tests collected' line?"; exit 1;; esac; \
	if [ "$$CURRENT" -lt "$$MIN" ]; then echo "ERROR: Test count dropped from $$MIN to $$CURRENT"; exit 1; fi

# ---- Mobile gates ----------------------------------------------------------

mobile-audit: ## Mobile dependency vulnerability scan (npm audit high+, dated allowlist in mobile/npm-audit-allowlist.json)
	cd mobile && node scripts/npm-audit.js

mobile-tsc: ## Mobile type check (tsc)
	cd mobile && npx tsc --noEmit

mobile-lint: ## Mobile lint (eslint)
	cd mobile && npx eslint 'app/**/*.{ts,tsx}' 'components/**/*.{ts,tsx}' 'store/**/*.{ts,tsx}' 'services/**/*.{ts,tsx}' 'hooks/**/*.{ts,tsx}' 'utils/**/*.{ts,tsx}' --max-warnings=100

mobile-test: ## Mobile unit tests (jest)
	# --forceExit: native-module mocks (AppState listeners, SOS retry intervals)
	# can leave open handles that hang jest indefinitely under --ci (a 6h CI
	# timeout). Tests still tear down their own handles; this is the backstop.
	cd mobile && npx jest --ci --forceExit

# ---- Infra gates -----------------------------------------------------------

docker-build: ## Validate backend web + worker Docker images build
	docker build -f backend/Dockerfile -t mih-web-test backend/
	docker build -f backend/Dockerfile.worker -t mih-worker-test backend/

# ---- Repo gates ------------------------------------------------------------

repo-clean: ## Fail if the git working tree has uncommitted changes
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "ERROR: working tree is dirty:"; git status --porcelain; exit 1; \
	fi

# ---- Aggregates ------------------------------------------------------------

backend: backend-audit backend-lint backend-types backend-test backend-testcount ## All backend gates
mobile: mobile-audit mobile-tsc mobile-lint mobile-test ## All mobile gates
infra: docker-build ## All infra gates

hooks-installed: ## Install the tracked pre-commit hook into .git/hooks if missing or stale (no-op in CI)
	@if [ -z "$$CI" ] && [ -d .git ]; then \
		if ! cmp -s scripts/git-hooks/pre-commit .git/hooks/pre-commit 2>/dev/null; then \
			install -m 755 scripts/git-hooks/pre-commit .git/hooks/pre-commit.tmp && \
				mv -f .git/hooks/pre-commit.tmp .git/hooks/pre-commit || exit 1; \
			echo "hooks-installed: installed scripts/git-hooks/pre-commit into .git/hooks/pre-commit"; \
		fi; \
	fi

verify: hooks-installed backend mobile ## Fast gate set (no docker) — what the git pre-commit hook runs; run on a quiescent tree
ci: verify infra repo-clean ## The complete union of every gate (what CI runs end to end)

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install-backend install-mobile backend-audit backend-lint backend-types \
	backend-db-preflight backend-test backend-testcount error-reporting-smoke mobile-audit mobile-tsc mobile-lint mobile-test \
	docker-build repo-clean backend mobile infra verify ci help
