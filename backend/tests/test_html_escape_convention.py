"""Lint test: every web route file that uses f-string HTMLResponse must import escape.

When we write HTMLResponse(content=f"...") instead of Jinja2 templates,
user-controlled data must be escaped via markupsafe.escape(). This test
ensures the escape import exists as a baseline guard. It cannot prove that
every interpolation is escaped, but it catches the common oversight of
adding a new f-string HTML block without importing escape at all.
"""

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "app" / "web"


def test_fstring_html_files_import_escape():
    violations = []
    for py_file in sorted(WEB_DIR.glob("routes_*.py")):
        source = py_file.read_text()
        if ('content=f"""' in source or "content=f'" in source) and "from markupsafe import escape" not in source:
            violations.append(py_file.name)

    assert not violations, (
        f"Files using f-string HTMLResponse without `from markupsafe import escape`: "
        f"{', '.join(violations)}. "
        f"All user-controlled data in f-string HTML must be escaped."
    )
