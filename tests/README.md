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

## Two files cover 4PP, and they cover different things

`test_4pp.py` calls `exp._do_run(params)` directly on the main thread.
That is right for what it tests — the correction-table edges, the
geometry rules, the plot filtering, the copy-to-calculation precision —
and it means **the worker thread is never entered**. A green
`test_4pp.py` says nothing about cancellation, ownership or threading.

`test_4pp_lifecycle.py` presses Run through `run_pressed()`, so the
measurement runs on a background thread exactly as it does at the bench,
and then presses Stop at precisely known instants.

Keep the split. Merging them would make the fast physics tests pay the
threading tests' runtime, and would hide which of the two a failure
belongs to.

## Cancellation is chosen, not timed

`stage_blocking_smu.py` is a `DummySMU` that pauses at a named stage and
waits on an event. The test waits for `reached` — a fact — presses Stop
while the run is parked, then releases.

The alternative is sleeping and hoping, and that is a test which passes
on a fast machine and fails on a loaded runner. On Windows the 15.6 ms
clock quantisation makes "wait 20 ms then cancel" a coin toss. An
intermittently red matrix teaches everybody to press re-run, which costs
more than the matrix is worth.

Two things learned building it, both worth not rediscovering:

* **A driver call already entered cannot be interrupted.** The first
  version of "nothing energising issued after Stop" counted the blocked
  call itself and failed on three boundaries — the *test* was wrong, not
  the code. The guarantee is about the checkpoint after the call.
* **`wait_idle()` must drain the UI queue.** The commit sink posts
  `_record_run` through `app.ui()`, so the controller reaches IDLE
  before the row is in the table. Asserting the instant idle goes true
  races the pump and fails roughly one run in three.

## Property-based tests

Wave 2 added `hypothesis` to the dev group. It is used in
`test_validation.py` and lightly in `test_identity.py`, and only where
an invariant is genuinely stronger than a table of examples — for
instance:

> for any text, `whole_number` either raises or returns exactly the
> number that was typed.

That is the §24 rule stated as a property. Truncation is precisely its
violation, so it catches `int(float(x))` however the truncation is
spelled, which a list of decimals to try does not.

The dependency is there for the shrinking, not the generation. A
hand-rolled random sweep finds the same bugs and reports them as
whatever 24-character string happened to trip; hypothesis reduces the
failure to `'0.5'` and prints the seed to reproduce it.

Keep the tables. They document what the validators promise; the
properties only prove the promise has no holes.

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

`test_4pp_lifecycle.py` is in the GUI group and is the slowest file in
it (~95 s): every row of the matrix builds a Tk root, runs a real
threaded measurement and waits for it to unwind. That is the price of
testing the thing that actually runs at the bench.

Wave 2's four new files (`test_validation`, `test_identity`,
`test_parameters`, `test_thread_guard`) are not among them: they build
no Tk root, share no module state and can each be run alone. That is
partly why `test_thread_guard.py` tests the guard against a five-line
fake rather than against `tkinter.Variable` — a real Tk target would
have earned the file a `gui` marker and a process of its own to prove
something the fake proves for free.

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


## The Windows TclError

Wave 0 spent several days on an intermittent Windows failure: `tk.Tk()`
reporting that a Tcl file which exists on disk could not be read, with
errno 0. It appeared on the bench machine and on CI, in a different test
each time, and it stopped reproducing without being fixed.

Ruled out by experiment:

| Suspected | Verdict |
|---|---|
| The Python distribution | No — Store, uv-managed and python.org all showed it |
| A synced or cloud filesystem | No — a clean CI runner under `C:\hostedtoolcache` showed it |
| pytest's output capture | No — `fd`, `sys` and `-s` all pass |
| How the child process is launched | No — console, pipes, DEVNULL and file all pass |
| matplotlib, PIL, ttk, threads | No — every scenario passes on Windows in isolation |
| Repeated create/destroy of roots | No — ten cycles pass |

Two things remain in the tree because of it, and neither should be
removed for being quiet. `_retry_tk_construction` in `conftest.py`
retries a failed `tk.Tk()` and logs whether the retry helped, which is
the one question the surviving theories disagree about. `run_tests.py`
gives each GUI file its own process, which limits how far one bad state
can spread.

If it returns, the retry log line is the first thing to read.


## The golden files

`tests/golden/*.json` hold a known set of inputs and the outputs each
calculation produced when its current version was declared in
`core.calculation.METHODS`. `tests/golden_cases.py` holds the inputs and
the function behind each method; `tools/make_goldens.py` writes the
files. They are split that way on purpose: no single edit can move both
an input and the value it is supposed to produce.

This is what makes a version constant mean anything. Without it,
`METHODS` could claim `hall_mobility:1` forever while the formula drifted
underneath, and a stored result would carry a version its numbers never
came from.

When one goes red, it is saying **a formula now returns a different
number for an input it already accepted**. Two legitimate responses:

* it was an accident — revert; the guard did its job;
* it was intended — bump the version in `core.calculation.METHODS`, run
  `uv run python tools/make_goldens.py`, and commit the moved numbers in
  the same change as the formula, so the diff shows what the revised
  correction actually did.

Regenerating the files to clear a red run without reading what moved
turns the guard into a rubber stamp. If the numbers moved and you cannot
say why, that is the finding.

These are not the notebook-parity tests. `test_hall_math.py` and
`test_iv_math.py` ask "is this the right formula"; the golden files ask
"is this still the formula that produced the numbers on disk". A change
can pass one and fail the other.

Comparison is exact — bit for bit — everywhere the arithmetic is pure
`math`. The 4PP chain runs through SciPy's `CubicSpline` and `griddata`
and gets a `1e-12` relative tolerance instead, which is tighter by many
orders of magnitude than the physics supports and loose enough that a
SciPy point release on one of the four CI cells does not produce a red
job that says nothing about this code.


## Driving a run from a test

Two shapes, and the difference matters when a test fails.

`vdp_harness.run_vdp()` and `test_4pp.py`'s `run_sync()` call `_do_run()`
directly on the main thread. That is right for physics, geometry rules,
saving and grouping, and it means those files say **nothing** about
threading, cancellation or ownership — the worker path is never entered.
A green there is not evidence the run lifecycle works.

`test_vdp_lifecycle.py` and `test_4pp_lifecycle.py` go the other way:
they press Run through `run_pressed()`, so the measurement runs on a
background thread exactly as it does at the bench, and then press Stop at
a precisely known instant.

Both drain explicitly afterwards. Work handed back with `app.ui()` is
queued and pumped by a timer the main thread owns, so a committed row is
still sitting in the queue when the assertions run unless it is drained.
A test that asserted on the store the instant the controller went idle
would race the pump and fail about one time in three.

### Choosing the instant, not timing it

`stage_blocking_smu.py` blocks the *instrument* at a named stage and
waits. The test waits for a fact rather than a duration, acts while the
run is parked, then releases. Sleeping and hoping would be a coin toss on
a loaded CI runner and on Windows's 15.6 ms clock, and an intermittently
red matrix teaches everybody to press re-run.

The stages are named after what the worker is doing, not which driver
method is being called, because that is the vocabulary review §8 uses.
Their call indices differ per experiment — 4PP's polarity flip is the
third `set_current_level`, Van der Pauw's is the second, because Van der
Pauw sets no level during configuration. A stage only fires when a test
arms it, so the two never collide.
