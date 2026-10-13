"""What moves a commissioning fingerprint, and what must not.

A driver is *commissioned* while the code that was checked at the bench
is the code that is running, and the fingerprint is how that is asked.
Until 2026-10-13 it hashed each file's bytes. A comment corrected in a
driver then marked its instrument as owed a checkup, so the cheapest
improvement there is - writing down what a bench session had just found
- cost a second bench session, and findings were kept out of the files
they were about to avoid it.

The fingerprint now compares what a file *does*. That is a looser
question, and a looser check is only acceptable if its two edges are
pinned:

  * **what it ignores is exactly what cannot run** - comments,
    docstrings, layout - and nothing else;
  * **everything the interpreter acts on still moves it**, including
    the ways a change can hide inside something that looks like a
    comment edit.

Each half is a list of real edits below. The second list is the one
that matters: a fingerprint that failed to move is a driver believed
current against code nobody checked.
"""
import pytest

from smuniversal_lab_suite.core.provenance import (
    code_fingerprint,
    code_paths_for,
    operative_source,
)

#: A driver in miniature, with one of everything the fingerprint has to
#: tell apart: a module docstring, a comment, a constant, a class and a
#: method docstring, a command string, a default, and a message.
DRIVER = '''"""A driver for an instrument.

Written from the manual.
"""
import time

#: How long to wait, in seconds.
SETTLE_S = 0.5


class Driver:
    """Drives it."""

    LIMIT = 10.0  # from the specification

    def set_level(self, volts, verify=False):
        """Set the level.

        The instrument rounds it.
        """
        if volts > self.LIMIT:
            raise ValueError(f"{volts} V is above the limit")
        # Full precision: the instrument does the rounding.
        self.transport.write(f"V {volts:.6g}")
        time.sleep(SETTLE_S)
        return verify
'''


def fingerprint(tmp_path, source, name="drivers/example.py"):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.encode("utf-8"))
    return code_fingerprint([name], root=str(tmp_path))


def edited(old, new, count=1):
    assert DRIVER.count(old) == count, f"{old!r} is not in the sample"
    return DRIVER.replace(old, new)


# ---------------------------------------------------------------
# What must NOT move it
# ---------------------------------------------------------------

SAYS_ONLY = {
    "a comment reworded":
        edited("# Full precision: the instrument does the rounding.",
               "# Sent in full. Measured 2026-10-08: it rounds to the "
               "nearest step."),
    "a comment added":
        edited("        time.sleep(SETTLE_S)",
               "        # The output takes a second to settle.\n"
               "        time.sleep(SETTLE_S)"),
    "a comment removed":
        edited("        # Full precision: the instrument does the "
               "rounding.\n", ""),
    "a trailing comment changed":
        edited("LIMIT = 10.0  # from the specification",
               "LIMIT = 10.0  # confirmed at the bench"),
    "a `#:` attribute note rewritten":
        edited("#: How long to wait, in seconds.",
               "#: Measured on both units: about a second."),
    "the module docstring rewritten":
        edited('"""A driver for an instrument.\n\nWritten from the '
               'manual.\n"""',
               '"""A driver for an instrument.\n\nBoth units have since '
               'been on a bench.\n"""'),
    "a class docstring rewritten":
        edited('    """Drives it."""', '    """Drives it, carefully."""'),
    "a method docstring rewritten":
        edited("        The instrument rounds it.\n",
               "        The instrument rounds it to the nearest step.\n"),
    "a method docstring removed":
        edited('        """Set the level.\n\n        The instrument '
               'rounds it.\n        """\n', ""),
    "blank lines added":
        edited("SETTLE_S = 0.5\n", "SETTLE_S = 0.5\n\n\n"),
    "a line re-wrapped":
        edited('            raise ValueError(f"{volts} V is above the '
               'limit")',
               '            raise ValueError(\n'
               '                f"{volts} V is above the limit")'),
    "quotes changed":
        edited('f"V {volts:.6g}"', "f'V {volts:.6g}'"),
    "windows line endings": DRIVER.replace("\n", "\r\n"),
}


@pytest.mark.parametrize("name", sorted(SAYS_ONLY))
def test_what_a_file_only_says_does_not_move_the_fingerprint(name, tmp_path):
    before = fingerprint(tmp_path, DRIVER)
    after = fingerprint(tmp_path, SAYS_ONLY[name])
    assert SAYS_ONLY[name] != DRIVER, "the edit did nothing"
    assert before == after, (
        f"{name} marked the driver stale. It changes nothing the "
        f"instrument is sent and nothing a checkup could have seen.")


# ---------------------------------------------------------------
# What MUST move it
# ---------------------------------------------------------------

DOES = {
    "a constant changed":
        edited("SETTLE_S = 0.5", "SETTLE_S = 1.5"),
    "a class attribute changed":
        edited("LIMIT = 10.0", "LIMIT = 35.3"),
    "the same number as another type":
        edited("LIMIT = 10.0", "LIMIT = 10"),
    "the command spelled differently":
        edited('f"V {volts:.6g}"', 'f"VV {volts:.6g}"'),
    "the command's precision changed":
        edited('f"V {volts:.6g}"', 'f"V {volts:.2f}"'),
    "a message reworded":
        edited("is above the limit", "exceeds the limit"),
    "a default changed":
        edited("verify=False", "verify=True"),
    "a comparison turned round":
        edited("if volts > self.LIMIT", "if volts >= self.LIMIT"),
    "a statement removed":
        edited("        time.sleep(SETTLE_S)\n", ""),
    "a statement commented out":
        edited("        time.sleep(SETTLE_S)",
               "        # time.sleep(SETTLE_S)"),
    "a statement added":
        edited("        return verify",
               "        self.transport.write('OP 1')\n"
               "        return verify"),
    "a method renamed":
        edited("def set_level", "def set_voltage"),
    "an exception type changed":
        edited("raise ValueError", "raise RuntimeError"),
    "an import changed":
        edited("import time", "import time as clock"),
    "a docstring turned into a value":
        edited('    """Drives it."""', '    NAME = """Drives it."""'),
    "a string that is not a docstring changed":
        DRIVER + '\nBANNER = "one"\n"not a docstring, but a statement"\n',
    "two statements swapped":
        edited('        self.transport.write(f"V {volts:.6g}")\n'
               '        time.sleep(SETTLE_S)\n',
               '        time.sleep(SETTLE_S)\n'
               '        self.transport.write(f"V {volts:.6g}")\n'),
}


@pytest.mark.parametrize("name", sorted(DOES))
def test_what_a_file_does_still_moves_the_fingerprint(name, tmp_path):
    before = fingerprint(tmp_path, DRIVER)
    after = fingerprint(tmp_path, DOES[name])
    assert before and after and before != after, (
        f"{name} left the fingerprint where it was, so a checkup would "
        f"stay 'commissioned' through a change to what the driver does")


def test_only_a_leading_string_is_a_docstring(tmp_path):
    """A bare string further down a body is not documentation the
    interpreter skips for free - and one that is *moved* off the top is
    no longer a docstring. Only the first statement is dropped."""
    plain = "def f():\n    return 1\n"
    documented = 'def f():\n    """Says what it does."""\n    return 1\n'
    trailing = 'def f():\n    x = 1\n    """A stray string."""\n    return x\n'
    without = "def f():\n    x = 1\n    return x\n"
    assert fingerprint(tmp_path, plain) == fingerprint(tmp_path, documented)
    assert fingerprint(tmp_path, trailing) != fingerprint(tmp_path, without)


def test_the_two_levels_of_docstring_are_both_dropped():
    """Module, class, method and nested function - a docstring is
    dropped wherever Python would treat it as one."""
    documented = (b'"""m"""\nclass C:\n    """c"""\n    def f(self):\n'
                  b'        """f"""\n        def g():\n'
                  b'            """g"""\n            return 1\n'
                  b'        return g\n')
    bare = (b'class C:\n    def f(self):\n        def g():\n'
            b'            return 1\n        return g\n')
    assert operative_source(documented) == operative_source(bare)


def test_a_file_that_does_not_parse_is_compared_byte_for_byte(tmp_path):
    """The strict direction to fail in. A file the fingerprint cannot
    read as Python gets no benefit of the doubt: a comment edit moves
    it, exactly as before."""
    broken = "def f(:\n    return 1  # one\n"
    assert operative_source(broken.encode()) == broken.encode()
    one = fingerprint(tmp_path, broken)
    two = fingerprint(tmp_path, broken.replace("# one", "# two"))
    assert one and two and one != two


def test_a_file_that_is_not_python_is_compared_byte_for_byte(tmp_path):
    one = fingerprint(tmp_path, "# a note\nvalue: 1\n", "drivers/table.yml")
    two = fingerprint(tmp_path, "# another note\nvalue: 1\n",
                      "drivers/table.yml")
    assert one != two


def test_the_position_of_a_statement_is_not_part_of_it(tmp_path):
    """Fifty lines of comment added above a class shift every line
    number in it. That must not read as fifty changes."""
    padded = DRIVER.replace(
        "class Driver:", "# a long story\n" * 50 + "class Driver:")
    assert fingerprint(tmp_path, DRIVER) == fingerprint(tmp_path, padded)


def test_a_change_in_any_covered_file_moves_it(tmp_path):
    """The fingerprint is of a driver *and* its base classes. A comment
    in the base leaves it alone; a statement in the base does not."""
    (tmp_path / "drivers").mkdir()
    base = tmp_path / "drivers" / "base_instrument.py"
    smu = tmp_path / "drivers" / "base_smu.py"
    driver = tmp_path / "drivers" / "example.py"
    base.write_text("class Base:\n    WRITE_DELAY_S = 0.0\n", encoding="utf-8")
    smu.write_text("class SMU:\n    pass\n", encoding="utf-8")
    driver.write_text(DRIVER, encoding="utf-8")
    paths = code_paths_for("drivers/example.py", fleet="smu")
    before = code_fingerprint(paths, root=str(tmp_path))

    base.write_text("class Base:\n    # no instrument needs it yet\n"
                    "    WRITE_DELAY_S = 0.0\n", encoding="utf-8")
    assert code_fingerprint(paths, root=str(tmp_path)) == before

    base.write_text("class Base:\n    WRITE_DELAY_S = 0.005\n",
                    encoding="utf-8")
    assert code_fingerprint(paths, root=str(tmp_path)) != before


def test_two_identical_drivers_are_still_told_apart(tmp_path):
    """The path is hashed with the content. Two models that happen to
    share a file's worth of code are different commissioning records."""
    assert (fingerprint(tmp_path, DRIVER, "drivers/one.py")
            != fingerprint(tmp_path, DRIVER, "drivers/two.py"))


def test_every_fingerprinted_file_in_the_package_parses():
    """The byte-for-byte fallback is for files that are not Python. If a
    real driver ever fell into it, its comments would start marking it
    stale again and nothing would say why."""
    import pathlib

    import smuniversal_lab_suite

    root = pathlib.Path(smuniversal_lab_suite.__file__).parent
    fallen = []
    for path in sorted((root / "drivers").glob("*.py")):
        raw = path.read_bytes()
        if operative_source(raw) == raw.replace(b"\r\n", b"\n") and raw:
            fallen.append(path.name)
    assert not fallen, f"compared byte for byte, not as code: {fallen}"
