"""The test runner must not let a stale `.pyc` decide what runs.

Found in Wave 7b, while mutation-testing the version check. The source
on disk read `0.1.0`; the imported module reported `0.2.0`. Nothing was
wrong with either file.

CPython decides whether a cached `.pyc` is still valid by comparing the
source's **modification time and size**. `"0.1.0"` and `"0.2.0"` are the
same size, and the edit landed inside a single mtime tick, so the
validator saw an unchanged file and reused bytecode compiled from the
previous version.

Why this is worth a test rather than a note
-------------------------------------------
Most of the real defects in this project were found by mutating the code
and checking that a test goes red. That technique is only as good as the
guarantee that the mutated source is the code being executed, and this
breaks exactly that guarantee - silently, and in both directions:

  * a mutation can survive being reverted, so later rounds test code
    nobody wrote;
  * a mutation can be *masked*, so a test that would have caught it
    appears not to. The natural response is to rewrite a perfectly good
    test until it "catches" something, which leaves the suite worse than
    before.

The second is the dangerous one, and it is invisible: everything passes.

Mutations that hit it are not exotic. `>=` for `<=`, `1e-3` for `1e-9`,
one instrument's command string for another's of equal length - the
dialect checks in this suite are full of candidates.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_runner_disables_the_bytecode_cache():
    """`run_tests.py` must pass `PYTHONDONTWRITEBYTECODE` to pytest.

    Asserted on the source rather than by running the suite, because
    running it to find out costs minutes and this is a one-line
    property. The companion test below proves the flag does what it is
    being relied on to do.
    """
    text = (ROOT / "run_tests.py").read_text(encoding="utf-8")
    assert "PYTHONDONTWRITEBYTECODE" in text, (
        "run_tests.py no longer disables the bytecode cache. Without it a "
        "same-length edit inside one mtime tick can leave stale bytecode "
        "running, which quietly invalidates mutation testing - see this "
        "file's docstring."
    )
    assert "env=env" in text, (
        "PYTHONDONTWRITEBYTECODE is set but the environment is not passed "
        "to the pytest subprocess, so it has no effect."
    )


def test_the_flag_actually_prevents_the_staleness(tmp_path):
    """The mechanism, demonstrated rather than trusted.

    Two runs of a child process importing the same module, with the
    source rewritten between them to a string of **identical length**
    and the mtime forced to match. Without the flag the second run can
    report the first version; with it, it must report the second.

    This is the discriminating half. Asserting only that the string
    `PYTHONDONTWRITEBYTECODE` appears in `run_tests.py` would pass just
    as well if the flag were spelled wrongly or did nothing.

    No sleeping and no timing assumptions: `os.utime` pins both mtimes
    to the same value explicitly, which reproduces the condition
    deterministically instead of racing the clock.
    """
    module = tmp_path / "probe_module.py"
    reader = tmp_path / "read_it.py"
    reader.write_text(
        "import probe_module\nprint(probe_module.VALUE)\n", encoding="utf-8")

    def write(value, when):
        module.write_text(f'VALUE = "{value}"\n', encoding="utf-8")
        import os
        os.utime(module, (when, when))

    def read(env_extra):
        import os
        env = dict(os.environ, PYTHONPATH=str(tmp_path), **env_extra)
        out = subprocess.run([sys.executable, str(reader)],
                             cwd=tmp_path, text=True, capture_output=True,
                             env=env)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    pinned = 1_700_000_000
    write("aaaaa", pinned)
    first = read({"PYTHONDONTWRITEBYTECODE": "1"})
    assert first == "aaaaa", first

    # Same length, same mtime: everything CPython's cache validator
    # looks at is unchanged.
    write("bbbbb", pinned)
    second = read({"PYTHONDONTWRITEBYTECODE": "1"})

    assert second == "bbbbb", (
        f"the child reported {second!r} after the source was changed to "
        f"'bbbbb'. Stale bytecode is being executed even with the cache "
        f"disabled, which means the protection run_tests.py relies on is "
        f"not working on this platform."
    )
