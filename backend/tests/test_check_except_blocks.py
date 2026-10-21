"""scripts/check_except_blocks.py — the `make backend-lint` gate that every
swallowed exception reports or is marked benign — behaves as documented.

Related: scripts/check_except_blocks.py, .claude/rules/backend-conventions.md.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_except_blocks.py"
_spec = importlib.util.spec_from_file_location("check_except_blocks", _SCRIPT)
assert _spec and _spec.loader
check_except_blocks = importlib.util.module_from_spec(_spec)
sys.modules["check_except_blocks"] = check_except_blocks
_spec.loader.exec_module(check_except_blocks)
check_source = check_except_blocks.check_source


def _problems(src: str) -> list[str]:
    return check_source(src, "x.py")


def test_reporting_and_raising_except_blocks_pass():
    assert not _problems(
        "try:\n    f()\nexcept ValueError:\n    logger.exception('x')\n"
    )
    assert not _problems("try:\n    f()\nexcept ValueError:\n    logger.error('x')\n")
    assert not _problems("try:\n    f()\nexcept ValueError:\n    raise\n")
    assert not _problems(
        "try:\n    f()\nexcept ValueError as e:\n    raise RuntimeError('y') from e\n"
    )
    assert not _problems(
        "try:\n    f()\nexcept ValueError as e:\n    notify(e, context='c')\n"
    )


def test_benign_comment_is_accepted_on_any_adjacent_line():
    assert not _problems(
        "try:\n    f()\n# benign: expected\nexcept ValueError:\n    return None\n"
    )
    assert not _problems(
        "try:\n    f()\nexcept ValueError:  # benign: expected\n    return None\n"
    )
    assert not _problems(
        "try:\n    f()\nexcept ValueError:\n    # benign: expected\n    return None\n"
    )


def test_silent_except_blocks_fail():
    problems = _problems("try:\n    f()\nexcept ValueError:\n    return None\n")
    assert len(problems) == 1 and "x.py:3" in problems[0]
    # warning/info/debug are not forwarded to the tracker, so they don't count
    assert _problems("try:\n    f()\nexcept ValueError:\n    logger.warning('x')\n")
    assert _problems("try:\n    f()\nexcept ValueError:\n    pass\n")


def test_only_an_unconditional_direct_report_counts():
    # A raise behind an `if` leaves the other branch silent.
    assert _problems(
        "try:\n    f()\nexcept ValueError:\n    if x:\n        raise\n    return None\n"
    )
    # A report inside a nested try belongs to the inner handler, not this one.
    problems = _problems(
        "try:\n    f()\nexcept ValueError:\n    try:\n        g()\n"
        "    except KeyError:\n        logger.error('y')\n"
    )
    assert len(problems) == 1 and "x.py:3" in problems[0]
    # `.error(...)` on something that is not a logger is not a report.
    assert _problems("try:\n    f()\nexcept ValueError:\n    result.error('x')\n")
    assert not _problems(
        "try:\n    f()\nexcept ValueError:\n"
        "    logging.getLogger(__name__).exception('x')\n"
    )
    assert not _problems(
        "try:\n    f()\nexcept ValueError as e:\n    await notify(e, context='c')\n"
    )
    # A conditional exit AHEAD of the report leaves a silent path...
    assert _problems(
        "try:\n    f()\nexcept ValueError:\n    if x:\n        return None\n    raise\n"
    )
    # ...a conditional raise ahead of it does not (both paths report).
    assert not _problems(
        "try:\n    f()\nexcept ValueError:\n    if x:\n        raise\n"
        "    logger.error('y')\n"
    )
    # Only loggers count: not `dialog.error(...)`, but `self.logger.error(...)`.
    assert _problems("try:\n    f()\nexcept ValueError:\n    dialog.error('x')\n")
    assert not _problems(
        "try:\n    f()\nexcept ValueError:\n    self.logger.error('x')\n"
    )
    # A record the forwarder deliberately drops reports nothing on its own.
    assert _problems(
        "try:\n    f()\nexcept ValueError:\n"
        "    logger.error('x', extra={'error_report_skip': True})\n"
    )


def test_suppress_needs_a_benign_comment():
    assert _problems("with contextlib.suppress(ValueError):\n    f()\n")
    assert not _problems(
        "# benign: optional\nwith contextlib.suppress(ValueError):\n    f()\n"
    )
    assert not _problems(
        "with contextlib.suppress(ValueError):  # benign: optional\n    f()\n"
    )


def test_the_live_tree_passes():
    assert check_except_blocks.main() == 0
