# Secret & config manifest

`manifest.json` is the **single source of truth** for every deployment env var
and config value. It records, for each key:

- which **side** it belongs to (`backend` or `mobile`),
- whether it's a **secret** (goes to Secrets Manager / EAS) or a **static** value
  (plain env var; the value lives in the manifest itself),
- the destination name (`backend_env` for the backend, `mobile_extra` for the
  Expo `extra` field).

`populate-secrets.sh` reads the manifest and distributes values to the right
place for a given environment.

## Files

| File | Committed? | Purpose |
|------|-----------|---------|
| `manifest.json` | yes | The contract: which keys, which side, secret vs static |
| `manifest.py` | yes | Loader/resolver used by the script (and the drift test) |
| `example.secrets.env` | yes | Scaffold of secret keys to fill in |
| `<env>.secrets.env` | **no** (gitignored) | Real secret values for dev/staging/production |

Secret **values** never live in git — only in `<env>.secrets.env`, which the
`secrets/` `.gitignore` rule keeps untracked.

## Usage

```bash
# 1. Create your value file from the template and fill it in
cp infra/secrets/example.secrets.env infra/secrets/production.secrets.env
$EDITOR infra/secrets/production.secrets.env

# 2. Distribute
infra/aws/scripts/populate-secrets.sh dev          # writes backend/.env + mobile/.env
infra/aws/scripts/populate-secrets.sh staging      #  Secrets Manager + ECS tasks + EAS (1 confirm)
infra/aws/scripts/populate-secrets.sh production    # same, double confirmation
```

- **dev** is local-only and quiet.
- **staging / production** print every action (secret names + targets, never
  values) before changing anything. Production additionally requires typing the
  environment name.
- Secrets are wired as **Secrets Manager references** on both the web service and the
  worker task (the ECS task execution role already has *secretsmanager:GetSecretValue*
  from `infra/aws/primary/`). Image deploys (CD) don't touch env vars, so you only
  re-run this when the manifest or values change.

## Adding a new secret or config value

1. Add **one entry** to `manifest.json` (pick `side`, set `secret` true/false;
   static values carry their value inline under `static`).
2. If it's a secret, add the key to each `<env>.secrets.env` and to
   `example.secrets.env` (or regenerate: `python3 infra/secrets/manifest.py template`).
3. If it's a backend env var, add the matching field to
   `backend/app/core/config.py` — the drift test
   (`backend/tests/test_secret_manifest.py`) fails if a config env var is
   missing from the manifest.
4. Run `populate-secrets.sh <env>`.

> EAS secrets are **project-scoped**, not per-channel. The mobile values pushed
> by the last run apply to all build profiles.
