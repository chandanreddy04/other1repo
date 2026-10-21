"""Build identity of the running image.

``GIT_SHA`` is stamped into the Docker image at build time (``ARG GIT_SHA`` in
backend/Dockerfile*, passed by deploy-aws.yml as the commit SHA). It is NOT
deploy-time configuration — it never comes from Secrets Manager or the task
definition — which is why it lives here rather than in app/core/config.py
(whose env vars must all be declared in infra/secrets/manifest.json).

Consumers: app/core/error_reporting.py (Bugsnag ``app_version``), app/main.py
(``GET /health`` ``version``), app/web/routes_admin.py (dashboard panel).
"""

import os


def git_sha() -> str:
    """The commit this image was built from, or ``dev`` outside a built image."""
    return os.environ.get("GIT_SHA", "dev")
