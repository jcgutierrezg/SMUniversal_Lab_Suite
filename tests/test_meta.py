"""Checks on the test suite itself.

Wave 0a shipped with the `gui` marker applied from a hand-written list.
It was wrong: twelve files build Tk roots and only nine were marked, so
three of them ran inside the shared process that `run_tests.py` exists
to keep free of Tk. The consequence was a Windows-only, intermittent
TclError in whichever unmarked file happened to run third.

A hand-maintained list of "which files touch Tk" will drift again the
next time someone adds a test. This makes the invariant executable.
"""
import ast

import pytest
from pathlib import Path

TESTS = Path(__file__).parent


def _creates_tk(path: Path) -> bool:
    """True if the module contains a `tk.Tk()` / `tkinter.Tk()` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "Tk":
            return True
    return False


def test_every_tk_file_is_marked_gui():
    """Files that build a Tk root must be isolated by `run_tests.py`.

    `run_tests.py` gives each `gui` file its own process, because a
    Windows Tcl runtime does not survive many interpreters being built
    and torn down inside one. A file that creates a root without the
    marker silently rejoins the shared process and reintroduces the
    failure.
    """
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        if not _creates_tk(path):
            continue
        if "pytest.mark.gui" not in path.read_text(encoding="utf-8"):
            missing.append(path.name)
    assert not missing, (
        "these files create a Tk root but are not marked `gui`, so "
        f"run_tests.py will not isolate them: {missing}"
    )
