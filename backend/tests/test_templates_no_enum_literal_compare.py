"""Jinja templates never compare a value to an UPPER_CASE string literal.

Enum-backed columns store lowercase values (`AlertStatus.ACKNOWLEDGED ==
"acknowledged"`), so `{% if alert.status == 'ACKNOWLEDGED' %}` is silently
always false — that exact bug shipped and was fixed in 556a8e6. The rule
(.claude/rules/frontend-conventions.md): compute labels from enum members in
Python and pass them in; a template that must branch on a raw value compares
against the lowercase value (`item.status.value in ('missed', 'alerted')`).

Scans only inside Jinja `{% %}` / `{{ }}` tags (comments stripped), so inline
JavaScript in a template is not affected. Catches `x == 'FOO'`, `x != "FOO"`,
`'FOO' == x` and `x in ('FOO', ...)` / `x in ['FOO']`.

Related: backend/app/web/templates/, tests/test_vocabulary.py (same scan
shape).
"""

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[1] / "app/web/templates"

_JINJA_COMMENT = re.compile(r"{#.*?#}", re.DOTALL)
_JINJA_TAG = re.compile(r"{%.*?%}|{{.*?}}", re.DOTALL)

_UPPER_LIT = r"""(['"])[A-Z][A-Z0-9_]+\1"""
_COMPARE_RIGHT = re.compile(r"(?:==|!=)\s*" + _UPPER_LIT)
_COMPARE_LEFT = re.compile(_UPPER_LIT + r"\s*(?:==|!=|\bin\b|\bnot\s+in\b)")
_IN_SEQUENCE = re.compile(r"\bin\s*[\(\[]([^\)\]]*)[\)\]]")
_UPPER_LIT_RE = re.compile(_UPPER_LIT)


def _violations(tag: str) -> bool:
    if _COMPARE_RIGHT.search(tag) or _COMPARE_LEFT.search(tag):
        return True
    return any(_UPPER_LIT_RE.search(m.group(1)) for m in _IN_SEQUENCE.finditer(tag))


def _scan(text: str) -> list[tuple[int, str]]:
    text = _JINJA_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    found = []
    for match in _JINJA_TAG.finditer(text):
        tag = match.group(0)
        if _violations(tag):
            line = text.count("\n", 0, match.start()) + 1
            found.append((line, " ".join(tag.split())))
    return found


def test_scanner_catches_the_556a8e6_bug_shape():
    assert _scan("{% if alert.status == 'ACKNOWLEDGED' %}x{% endif %}")
    assert _scan('{{ "yes" if s != "MISSED" }}')
    assert _scan("{% if s in ('ACTIVE', 'MISSED') %}{% endif %}")
    assert _scan("{% if 'SOS' == t %}{% endif %}")
    assert not _scan("{% if item.status.value in ('missed', 'alerted') %}{% endif %}")
    assert not _scan("{# {% if s == 'ACTIVE' %} #}")
    assert not _scan("<script>if (s === 'ACTIVE') {}</script>")


def test_templates_do_not_compare_to_upper_case_literals():
    files = sorted(_TEMPLATES.rglob("*.html"))
    assert len(files) > 10, "template scan found suspiciously few files"
    hits = [
        f"{path.relative_to(_TEMPLATES)}:{line}: {tag}"
        for path in files
        for line, tag in _scan(path.read_text(encoding="utf-8"))
    ]
    assert not hits, (
        "Jinja compares against an UPPER_CASE literal — enum values are stored "
        "lowercase, so this never matches; compute the label in Python:\n"
        + "\n".join(hits)
    )
