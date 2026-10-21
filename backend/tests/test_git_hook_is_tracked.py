"""The git pre-commit gate is a tracked file, not a local-only artifact.

`.git/` is never committed, so the hand-written pre-commit script that runs
`make verify` used to live ONLY at `.git/hooks/pre-commit` — invisible to
code review and lost on a fresh clone. `scripts/git-hooks/pre-commit` is now
the tracked source of truth; `make hooks-installed` (a `verify` prerequisite)
installs it into `.git/hooks/pre-commit` whenever the two differ.

This also pins the retirement of the inert hook configs (owner decision
2026-09-27): `.pre-commit-config.yaml` stays on disk but must not be what
SETUP/README/CLAUDE.md point people at, and `.husky/` + its `prepare` script
are gone outright.

Related: CLAUDE.md "Verification Layers → Git pre-commit", SETUP.md "Git
hooks (one-time)".
"""

import stat
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HOOK = _REPO / "scripts" / "git-hooks" / "pre-commit"


def test_tracked_hook_exists_and_is_executable() -> None:
    assert _HOOK.is_file(), f"{_HOOK} is missing"
    mode = _HOOK.stat().st_mode
    assert mode & stat.S_IXUSR, f"{_HOOK} is not executable"


def test_tracked_hook_runs_make_verify() -> None:
    content = _HOOK.read_text()
    assert "make verify" in content


def test_makefile_hooks_installed_references_tracked_hook() -> None:
    makefile = (_REPO / "Makefile").read_text()
    # Grab just the hooks-installed target body (up to the next top-level target).
    start = makefile.index("hooks-installed:")
    end = makefile.index("\nverify:", start)
    target_body = makefile[start:end]
    assert "scripts/git-hooks/pre-commit" in target_body
    assert ".git/hooks/pre-commit" in target_body


def test_setup_hooks_section_points_at_make_hooks_installed() -> None:
    setup = (_REPO / "SETUP.md").read_text()
    start = setup.index("### Git hooks")
    next_heading = setup.find("\n#", start + 1)
    section = setup[start : next_heading if next_heading != -1 else len(setup)]
    assert "make hooks-installed" in section


def test_no_pre_commit_install_command_remains() -> None:
    # Prose may still WARN against `pre-commit install` (SETUP.md / CLAUDE.md
    # deliberately do). What must never come back is a line that IS the command
    # — e.g. inside a ```bash block — since running it replaces the tracked hook.
    # Matching on command position (not on a nearby "don't") means a line like
    # "pre-commit install (not recommended)" is still caught.
    candidates = [_REPO / "SETUP.md", _REPO / "CLAUDE.md"]
    candidates.extend(_REPO.glob("README*.md"))
    for path in candidates:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            command = line.strip().lstrip("$>").strip().strip("`").strip()
            assert not command.startswith("pre-commit install"), (
                f"{path}:{lineno} instructs 'pre-commit install', "
                "which would replace the tracked hook"
            )


def test_husky_dir_absent() -> None:
    assert not (_REPO / ".husky").exists()


def test_mobile_package_json_has_no_prepare_script() -> None:
    import json

    package_json = json.loads((_REPO / "mobile" / "package.json").read_text())
    assert "prepare" not in package_json.get("scripts", {})
