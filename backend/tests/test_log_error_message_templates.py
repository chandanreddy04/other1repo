"""ERROR-level log calls use a ``%s`` template, never an f-string.

``app/core/error_reporting.py`` groups message-only records by
``logger_name:record.msg`` — the UNFORMATTED template — so every "Twilio error
sending SMS to <tag>" lands in one Bugsnag error with a count instead of one
error per rendered message (for a message carrying a phone tag or an id: one
per recipient, and the dedupe/snooze the grouping exists for is inverted). An
f-string, ``%``-formatting or ``.format()`` renders before the logger sees it
and silently defeats that. Nine sites did exactly this on 2026-09-06.

Related: app/core/error_reporting.py (_LogForwarder._annotate),
.claude/rules/backend-conventions.md.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    *sorted((ROOT / "app").rglob("*.py")),
    ROOT / "worker_tick.py",
    ROOT / "worker_loop.py",
]
FORWARDED_LEVELS = {"error", "exception", "critical"}


def _rendered_before_logging(arg: ast.expr) -> bool:
    if isinstance(arg, ast.JoinedStr):  # f"..."
        return True
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):  # "..." % x
        return True
    return (  # "...".format(x)
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Attribute)
        and arg.func.attr == "format"
    )


def _is_logger(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):  # logging.getLogger(...)
        func = node.func
        return (func.attr if isinstance(func, ast.Attribute) else "") == "getLogger"
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    return name in {"logger", "log", "root"} or name.endswith(("logger", "_log"))


def _violations(path: Path, root: Path = ROOT) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in FORWARDED_LEVELS or not _is_logger(node.func.value):
            continue
        if node.args and _rendered_before_logging(node.args[0]):
            out.append(f"{path.relative_to(root)}:{node.lineno}")
    return out


def test_error_level_logs_use_a_template_not_an_fstring() -> None:
    violations = [v for path in FILES for v in _violations(path)]
    assert violations == [], (
        "ERROR-level log messages must be `%s` templates (they are the Bugsnag "
        "grouping key); pass values as arguments:\n  " + "\n  ".join(violations)
    )


def test_the_detector_sees_each_rendered_form(tmp_path: Path) -> None:
    src = (
        'logger.error(f"a {x}")\n'
        'logger.exception("a %s" % x)\n'
        'log.critical("a {}".format(x))\n'
        'self.logger.error(f"b {x}")\n'
        'logger.error("ok %s", x)\n'
        'result.error(f"not a logger {x}")\n'
    )
    path = tmp_path / "probe_templates.py"
    path.write_text(src)
    assert _violations(path, root=tmp_path) == [
        "probe_templates.py:1",
        "probe_templates.py:2",
        "probe_templates.py:3",
        "probe_templates.py:4",
    ]
