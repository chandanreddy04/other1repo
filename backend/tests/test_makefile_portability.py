"""Guard: the root Makefile must run identically on CI (Linux/GNU make) and
locally (macOS ships GNU make 3.81 + BSD grep).

Two real portability bugs shipped in `backend-testcount` and only failed on
macOS — the local Stop-hook gate — while passing in CI:
  1. `cd backend` on its own recipe line relied on `.ONESHELL`, which make 3.81
     silently ignores → each line runs in a fresh shell, so the `cd` was lost.
  2. `grep -oP` (Perl regex) is GNU-only; BSD grep rejects `-P`.

These assert the Makefile stays portable so the same class can't recur.
"""

import re
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"


def _recipe_lines() -> list[str]:
    """Return recipe lines (those beginning with a TAB) from the Makefile."""
    return [
        line
        for line in MAKEFILE.read_text().splitlines()
        if line.startswith("\t")
    ]


def test_no_perl_regex_grep():
    """`grep -P`/`grep -oP` is GNU-only — BSD grep (macOS) rejects it."""
    offenders = [ln for ln in _recipe_lines() if re.search(r"grep\s+-\S*P", ln)]
    assert not offenders, (
        "GNU-only 'grep -P' found in Makefile recipe(s) — use 'grep -oE' for "
        "BSD/GNU portability:\n" + "\n".join(offenders)
    )


def test_no_bare_cd_recipe_line():
    """A recipe line that is only `cd <dir>` relies on .ONESHELL (make >= 3.82)
    to carry the directory to the next line. macOS make 3.81 ignores .ONESHELL,
    so chain within one shell instead: `cd <dir> && ...` or `cd <dir> && \\`."""
    offenders = [ln for ln in _recipe_lines() if re.fullmatch(r"\t\s*cd\s+\S+\s*", ln)]
    assert not offenders, (
        "Bare 'cd' recipe line(s) rely on .ONESHELL (broken on macOS make 3.81) — "
        "chain with '&&' / '\\' so the recipe runs in one shell:\n"
        + "\n".join(offenders)
    )
