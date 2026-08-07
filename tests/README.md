# Test suite

## Running

```bash
uv sync                       # installs pytest via the dev group
uv run pytest                 # default suite: everything except `slow`
uv run pytest -m ""           # everything, including slow
uv run pytest -m slow         # only the slow ones
uv run pytest tests/test_hall_math.py -v
```

On Linux CI the GUI tests need a display: `xvfb-run -a uv run pytest`.
On Windows they run directly.

## Markers

| Marker | Meaning |
|---|---|
| `slow` | More than ~5 s. Excluded by default. `test_checkup` alone is ~58 s because its fault scenarios include deliberate stalls. |
| `gui` | Builds a real Tk window. |
| `hardware` | Needs a physical instrument. Never run in CI. Nothing carries this yet; it exists for the hardware-in-the-loop protocol. |

## Two styles, on purpose

Before Wave 0a the suite was 25 standalone scripts. Each one re-declared
the same `check(name, condition, detail)` helper, appended failures to a
module-level list, and called `sys.exit(1)` in a footer. They were
converted to pytest mechanically, and two styles now coexist:

1. **Converted section tests.** The scripts already marked their sections
   with `print("\ntest_something:")`; each of those became a test
   function. They still call `check(...)`, which is now a fixture in
   `conftest.py` implementing *soft assertions*: a failing check is
   recorded rather than raising, so one run reports every broken check in
   that test instead of only the first. The test fails at teardown with
   the full list.

2. **Wrapped collector tests.** Eight files defined functions that
   *returned* a list of failures for a `__main__` footer to inspect.
   Under pytest a returned value is ignored, so those would have passed
   unconditionally. The collectors are unchanged and renamed
   `_collect_*`; a generated `test_*` wrapper asserts the list is empty.

## Known limitations

**These files are order-dependent.** The original scripts ran top to
bottom in one module namespace, so a Tk app or fake-driver class built in
one section was still live in a later one. That sharing is preserved with
`global` declarations, and pytest runs tests within a file in definition
order, so the behaviour matches the scripts exactly.

The consequence is that in the affected files a single test cannot be run
in isolation, and parallel execution (`pytest-xdist`) would break them.

Affected: `test_4pp`, `test_checkup`, `test_checkup_all_drivers`,
`test_gsm20h10`, `test_minismu`, `test_timing_scan`, `test_u2722a`,
`test_visa_backends`.

This is deliberate technical debt. Wave 0a's contract was zero behaviour
change; converting the shared setup into module-scoped fixtures would
have meant redesigning what those files test, not just how they run.
The conversion should happen as each experiment is touched in later
waves, at which point the autouse leaked-Tk-root guard (written during
Wave 0a and removed because it destroyed intentionally shared roots)
becomes viable again.

## What Wave 0a found

Three classes of test could not fail before the conversion. None of them
were failing — every original script passed — but the coverage was
narrower than the file count implied.

- **32 functions across 8 files** were named `def test_*` and contained
  no `assert`. Included `test_hall_math`'s bit-identical-to-the-notebook
  guard.
- **`test_dialects`** printed whether the two dialects agreed and exited 0
  regardless. It also carried its reporting block twice, verbatim.
  Separately, its `FakeTransport` returned SCPI field order to both
  drivers, so the 2611A correctly parsed current as voltage and returned
  1/1234. The fake is now dialect-aware and both drivers recover 1234 Ω,
  which is what the file always claimed to prove.
- **`test_demo_mode`** printed `"PASS" if error < 0.5 else "FAIL - chain
  is broken"` and exited 0 either way. Same tolerance, now asserted.

## Why `run_tests.py` exists

`uv run pytest` works, but on Windows it is not reliable, and the reason
is not in this repository.

Eleven files build real Tk windows. In one pytest process the suite
creates 21 Tk interpreters against a single shared Tcl runtime, and on
Windows that runtime does not survive it. Past roughly the tenth,
`tk.Tk()` starts failing in ways unrelated to the test that hits them:

- `TclError: invalid command name "tcl_findLibrary"` (Microsoft Store
  Python 3.11)
- `TclError: couldn't read file "...spinbox.tcl"` — about a file that is
  present on disk (uv-managed CPython 3.12)

Same breakage, different messages, and non-deterministic: it surfaces as
whichever GUI test happens to run after the runtime gives out, so it
looks like a different failure each time.

As 25 standalone scripts the suite never hit this, because each process
built at most three roots and then exited. Process isolation was load
bearing; it was simply implicit. `run_tests.py` makes it explicit — the
non-GUI tests share one fast process, and each GUI file gets its own.

```bash
uv run python run_tests.py           # default, skips `slow`
uv run python run_tests.py --all
```

Use it on Windows and in CI. Plain `uv run pytest` remains fine for a
single file while iterating, and is reliable on Linux.
