"""User-visible copy uses the shared vocabulary (owner decision 2026-09-23).

Circle / Circle of Trust, Circle member, Session, Alert, Acknowledge, I'm
Safe / mark safe / All clear, Subscription / plan / day pass, Group Plan,
Sponsor / sponsorship, Referral / code, Account / profile, Circle
invitation. This is a static scan for terms the vocabulary retired —
"emergency contact", "trusted contact", etc. — in on-screen copy: web
templates, mobile screen/component/hook/store/util source, the Live
Activity copy (services/liveStatus.ts) and the native permission prompts
(app.config.js). docs/ (store listing etc.) is not scanned.

User-visible copy also lives in backend strings — an ``HTTPException``
string ``detail`` is shown by the app as the error message
(mobile/services/api.ts), and push/SMS constants, vCard text and schema
validation messages reach people too — so every non-docstring string
constant in backend/app/**/*.py is scanned (via the AST, so comments and
docstrings are skipped), and so is mobile/services/** with comments
stripped (excluding *.test.ts).

Matching is case-insensitive, on whole words, over whitespace-collapsed text
— JSX wraps long copy across lines ("Add trusted\\n contacts"), which a
per-line substring scan misses.

Deliberately NOT a check for the vocabulary being used correctly everywhere
(that's a review, not a grep) — just that the retired terms don't reappear.

Related: .claude/rules/domain-sessions-alerts.md, .claude/rules/
domain-subscriptions.md, test_removed_feature_tombstones.py (identifier
renames from the same commit).
"""

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Terms the vocabulary retired (matched case-insensitively, as whole words,
# plural included — "trusted contacts" matches "trusted contact").
BANNED_TERMS = [
    "emergency contact",
    "safety backup",
    "safety network",
    "trusted contact",
    "Mark as Read",
    "I'm on it",
    "Family Plan",
    "check-in session",
    "Complete Session",
    "Gift a",
    "Gifted",
    # Series-review gaps: an Alert is an "SOS alert" or a "missed check-in
    # alert"; the people alerted are the Circle of Trust.
    "chosen contact",
    "Safety Alert",
    "Emergency Alert",
    "your people",
    "panic button",
]

_BANNED_RE = [
    (term, re.compile(r"(?<!\w)" + re.escape(term) + r"s?(?!\w)", re.IGNORECASE))
    for term in BANNED_TERMS
]

_JINJA_COMMENT = re.compile(r"{#.*?#}", re.DOTALL)
_WS = re.compile(r"\s+")

_TEMPLATES_ROOT = _REPO / "backend/app/web/templates"
_MOBILE_ROOTS = [
    _REPO / "mobile/app",
    _REPO / "mobile/components",
    _REPO / "mobile/constants",
    _REPO / "mobile/hooks",
    _REPO / "mobile/store",
    _REPO / "mobile/utils",
]
_MOBILE_SUFFIXES = {".ts", ".tsx"}
# User-visible copy that lives outside the screen roots: the Live Activity /
# lock-screen status copy and the native permission prompts (iOS infoPlist).
_MOBILE_EXTRA_FILES = [
    _REPO / "mobile/services/liveStatus.ts",
    _REPO / "mobile/app.config.js",
]

# Deliberately kept wording that uses a retired term: the push/SMS bodies and
# prefilled share-sheet texts that used to sit here were reworded in the
# owner-reviewed 2026-09-27 copy batch (pinned by test_reviewed_copy.py), so
# what remains is wording that is not ours to change — generic phone advice
# and the registered A2P 10DLC consent disclosure. Each entry is (path, exact
# text) — only that text is exempt, the rest of the file is still scanned —
# and each must still exist, so a stale entry fails instead of silently
# widening the allowlist.
ALLOWED: list[tuple[str, str]] = [
    # Generic advice about the PHONE's own "emergency contacts" feature
    # (owner decision: leave — it's not our Circle feature).
    ("mobile/constants/safetyTips.ts", "Save emergency contacts on your lock screen."),
    # A2P 10DLC SMS-consent disclosure — registered carrier wording, frozen.
    (
        "backend/app/web/templates/fragments/sms_consent.html",
        "sign-in codes, check-in and safety alerts,",
    ),
    ("mobile/constants/config.ts", "sign-in codes, check-in and safety alerts,"),
    (
        "backend/app/web/templates/circle_invite.html",
        "you agree to receive safety alert texts",
    ),
]


def _allowed_for(rel: str) -> list[str]:
    return [text for path, text in ALLOWED if path == rel]


def _iter_template_files():
    yield from _TEMPLATES_ROOT.rglob("*.html")


def _iter_mobile_files():
    for root in _MOBILE_ROOTS:
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix in _MOBILE_SUFFIXES
                and ".test." not in path.name
                and "node_modules" not in path.parts
            ):
                yield path
    yield from _MOBILE_EXTRA_FILES


def _hits(path: Path, text: str) -> list[str]:
    rel = path.relative_to(_REPO).as_posix()
    for allowed in _allowed_for(rel):
        text = text.replace(allowed, "")
    flat = _WS.sub(" ", text)
    found = []
    for term, pattern in _BANNED_RE:
        for match in pattern.finditer(flat):
            context = flat[max(0, match.start() - 40) : match.end() + 40]
            found.append(f"{rel}: {term!r} in …{context}…")
    return found


def test_web_templates_use_shared_vocabulary():
    files = list(_iter_template_files())
    assert len(files) > 10, (
        "template scan found suspiciously few files — root path drifted?"
    )
    hits: list[str] = []
    for path in files:
        text = _JINJA_COMMENT.sub("", path.read_text(encoding="utf-8"))
        hits.extend(_hits(path, text))
    assert not hits, "retired vocabulary found in web templates:\n" + "\n".join(hits)


def test_mobile_screens_use_shared_vocabulary():
    files = list(_iter_mobile_files())
    assert len(files) > 50, (
        "mobile scan found suspiciously few files — root path drifted?"
    )
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits.extend(_hits(path, text))
    assert not hits, "retired vocabulary found in mobile source:\n" + "\n".join(hits)


def test_allowlist_entries_still_exist():
    stale = [
        f"{path}: {text!r}"
        for path, text in ALLOWED
        if text not in (_REPO / path).read_text(encoding="utf-8")
    ]
    assert not stale, (
        "allowlisted frozen copy no longer present — drop the entry:\n"
        + "\n".join(stale)
    )


# ---- Backend string constants + mobile/services -----------------------------

_BACKEND_APP = _REPO / "backend/app"
_MOBILE_SERVICES = _REPO / "mobile/services"

# Frozen backend copy, keyed (path, key): key is the module-level constant the
# string is assigned to, or else the exact string value. Each entry must still
# produce a hit, so the list can only shrink.
BACKEND_ALLOWED: list[tuple[str, str]] = [
    # Empty since the 2026-09-27 copy batch reworded every frozen string.
]

# Whole files exempt from the mobile/services scan, with the reason.
MOBILE_SERVICES_ALLOWED_FILES: dict[str, str] = {
    # Empty since mobile/services/sms.ts was deleted (2026-09-27).
}

# JS/TS string literals (kept) vs comments (stripped). A comment is only
# recognised outside a string, so "https://" inside a literal survives.
_TS_TOKEN = re.compile(
    r"""('(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`)"""
    r"|(//[^\n]*|/\*.*?\*/)",
    re.DOTALL,
)


def _strip_ts_comments(text: str) -> str:
    return _TS_TOKEN.sub(lambda m: m.group(1) if m.group(1) else " ", text)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
        ):
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def _module_constant_names(tree: ast.Module) -> dict[int, str]:
    """Map each string node under a module-level assignment to its target."""
    names: dict[int, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if isinstance(target, ast.Name):
            for sub in ast.walk(value):
                names[id(sub)] = target.id
    return names


def _backend_string_hits() -> list[tuple[str, int, str, str, str]]:
    """(rel, line, term, constant name or '', string value) per banned hit."""
    hits = []
    for path in sorted(_BACKEND_APP.rglob("*.py")):
        rel = path.relative_to(_REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        names = _module_constant_names(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                flat = _WS.sub(" ", node.value)
                for term, pattern in _BANNED_RE:
                    if pattern.search(flat):
                        hits.append(
                            (
                                rel,
                                node.lineno,
                                term,
                                names.get(id(node), ""),
                                node.value,
                            )
                        )
    return hits


def _backend_allowed(rel: str, name: str, value: str) -> bool:
    return any(path == rel and key in (name, value) for path, key in BACKEND_ALLOWED)


def test_backend_strings_use_shared_vocabulary():
    hits = [
        f"{rel}:{line}: {term!r} in {value[:80]!r}"
        for rel, line, term, name, value in _backend_string_hits()
        if not _backend_allowed(rel, name, value)
    ]
    assert not hits, (
        "retired vocabulary in backend strings (HTTPException details, "
        "push/SMS copy, validation messages are user-visible):\n" + "\n".join(hits)
    )


def test_backend_allowlist_entries_still_hit():
    hits = _backend_string_hits()
    stale = [
        f"{path}: {key!r}"
        for path, key in BACKEND_ALLOWED
        if not any(
            rel == path and key in (name, value) for rel, _, _, name, value in hits
        )
    ]
    assert not stale, (
        "allowlisted frozen backend copy no longer uses a retired term — drop "
        "the entry:\n" + "\n".join(stale)
    )


def test_mobile_services_use_shared_vocabulary():
    files = [
        path
        for path in _MOBILE_SERVICES.rglob("*")
        if path.is_file()
        and path.suffix in _MOBILE_SUFFIXES
        and ".test." not in path.name
        and path.relative_to(_REPO).as_posix() not in MOBILE_SERVICES_ALLOWED_FILES
    ]
    assert len(files) > 10, (
        "mobile/services scan found suspiciously few files — root path drifted?"
    )
    hits: list[str] = []
    for path in files:
        text = _strip_ts_comments(path.read_text(encoding="utf-8", errors="ignore"))
        hits.extend(_hits(path, text))
    assert not hits, "retired vocabulary in mobile/services:\n" + "\n".join(hits)


def test_mobile_services_allowlisted_files_still_exist():
    missing = [
        rel for rel in MOBILE_SERVICES_ALLOWED_FILES if not (_REPO / rel).exists()
    ]
    assert not missing, "allowlisted file is gone — drop the entry:\n" + "\n".join(
        missing
    )
