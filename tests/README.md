# Test suite

## Running

```bash
uv sync
uv run python run_tests.py --all
```

That is the suite command. **Do not use plain pytest as a substitute**, even
for a change that looks non-GUI: collection in one process changes Tk and
messagebox state in ways the runner exists to isolate. A change is not green
until `run_tests.py --all` is green.

On Linux without a display, prefix the same runner with `xvfb-run -a`. On
Windows it runs directly. CI uses this process-isolated path on both systems.

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

## Shared state: assert through the widget, not around it

`test_combined_window.py` guards the Wave 5b window, where two
experiments share one sample name, one thickness, one counter and one
temperature stage. Every failure it covers is silent — a window that
gets this wrong does not crash, it goes on looking right while one tab
reads a number belonging to the other.

The lesson from writing it is worth not rediscovering. The first guard
asserted that both experiments and the app agreed on *which variable
object* holds the sample name. That is necessary and not sufficient, and
a mutation proved it: putting a private `tk.StringVar` back into the Van
der Pauw setup panel and assigning it over `exp.app.sample_name_var`
leaves all three readers agreeing perfectly. The only thing stranded is
the box the operator types into — which then does nothing, while every
reader sees `sample` forever and nothing raises.

So the question is not "do the readers agree" but "is the box the
operator types in wired to the variable the readers read". The tests
drive the `Entry` the way a finger does, and
`core.gui.session_strip.bound_variable()` checks the wiring directly,
for every session widget in every window shape.

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

## The Wave 6 files, and what each is for

These were added as Wave 6 rolled the run lifecycle and the ranging
contract across the suite. They overlap deliberately in subject and not
at all in method, so a fault shows up in exactly one of them.

| File | Question it answers |
|---|---|
| `test_sweep_ownership.py` | Can two software sweeps write into one buffer? (They could. The first sweep came back as `[100.0, 1.0, 2.0, 3.0, 4.0]`.) |
| `test_iv_lifecycle.py` | Does Stop discard, and is anything configured while the sample is live? |
| `test_house_rule_12.py` | The same question for Van der Pauw, Hall and 4PP — by running them, not by reading them |
| `test_range_before_limit.py` | Are ranges widened before compliances are set? |
| `test_dialect_hygiene.py` | Does any driver speak another driver's dialect? |
| `test_transition_traces.py` | Exact output-transition spellings, and whether a driver defers configuration past an output-on |
| `test_range_plan.py` | The ranging contract: every axis stated, and the one axis no plan may set |
| `test_sweep_traces.py` | Arming versus stepping; abort spelling; error-queue drain |
| `test_reconnect.py` | What the application does when the connection breaks |

Two habits in these files are worth copying rather than reinventing.

**Ordering is tested by running the thing.** Ordering is not a property
of any single method — every call can be individually correct and the
sequence still put a compliance after the output came on. So the
experiment is driven through a recording proxy and the resulting command
order inspected. Checking each method alone cannot see it, and a
hand-check of the four experiments during Wave 6a said they complied
when two of them did not.

**Every check has a control.** "The output was actually turned on",
"the instrument was actually configured", "the queue reports a known-bad
header". Without them a test that examined nothing passes, which has
happened here twice: once with a count that reset already satisfied,
once with a test asserting state the fake's own reset had set.

A mutation round found a third case in Wave 6a: deleting the
cancellation checkpoint from the sweep poll left every test green,
because the commit gate refuses a cancelled run anyway and the results
table ends up empty either way. Empty-table was not a discriminating
assertion. What separates the two is whether the sweep was abandoned or
read out first.

## A new test has to prove it can fail

A first-time green assertion is not enough. For every new guarantee, mutate the
production code so that guarantee is false, run `uv run python run_tests.py --all`,
and require a red result. Revert that one mutation before trying the next. This
is part of adding the test, not a later audit step: several past mutation rounds
found holes in the test rather than in the code.

Where the guard is a golden file or byte-for-byte equality check, regenerate the
golden under the mutation before running the suite. Otherwise the stale fixture
can be the thing that fails and falsely make an unrelated test look
discriminating.

The suite must also leave the checkout exactly as it found it. Capture
`git status --porcelain` immediately before and after the full runner and compare
the outputs. A test that writes a generated file owns its cleanup/restoration,
including on failure.

Timing is not evidence. Wait on facts/events and drain queues explicitly; never
add a sleep whose only job is to hope the worker has reached the expected state.
The cancellation harness above is the pattern to copy.

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

A one-process pytest invocation can execute the tests, but it is not the
repository suite command and is not reliable on Windows. The reason is not in
this repository.

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
uv run python run_tests.py --all
```

Use that command for local validation and CI. The runner is not merely a
Windows workaround; using a one-process pytest invocation gives a different
test environment and is therefore not accepted as evidence that the suite is
green.

### A group that stops making progress

Each group is announced before it starts and killed if it exceeds a
budget; `SMU_GROUP_TIMEOUT_S` overrides the budget in seconds. A run
names every group that hung rather than stopping at the first.

Both halves matter, and neither is about speed. A run under CI hung and
produced a log containing nothing at all, because the runner printed
only on completion and `print()` to a pipe is block-buffered — a whole
run's output fits inside one buffer, so it was still sitting there when
the job was cancelled. An empty log is the same log whether the first
group hung or the last, so the fault could not be localised even in
principle.

Reaching the budget is a finding, not an obstacle. Raise it for a
machine slower than any seen so far; do not raise it for a group that
has started taking longer than it used to.

### The second reason, which is not about Windows

Process isolation is load bearing for a reason unrelated to Tcl, and it
would still be load bearing if the Windows fault never came back.

Most GUI files monkeypatch `messagebox` on `core.base_experiment` and
`core.base_app` at import time. pytest imports every module during
collection, so in one process the **last file imported wins**, and every
earlier file's dialog recorder is never written to. A deliberately forced
one-process pytest run reports sixteen errors from this on Linux, Python 3.14 —
all of them refusal tests reporting an empty recorder.

The errors are loud. The same mechanism in the other direction is not:
an assertion that *no* dialog was shown passes against a stolen recorder
whether or not the code is right, and `test_rs_handoff.py` contains
several. Do not silence those sixteen errors by relaxing assertions; they
are the canary. Measured in
[the test suite audit](../docs/reference/test-suite-audit.md).


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


## The suite does not look for instruments

`_no_instrument_discovery` in `conftest.py` is autouse: it stubs
`list_available()` and `scan_summary()` on every registered transport,
for every test that does not carry the `instrument_discovery` marker.

It exists because `build_connection_panel()` populates the address
dropdown as soon as it is built - right at the bench, wrong in a test.
Every `LabApp(...)` construction was walking three VISA backends, and
pyvisa-py's TCPIP discovery **scans the network**. Every GUI test here
connects a `NullTransport` and touches no instrument, but before this it
first asked the lab's network what was plugged in, and on CI asked
GitHub's. A test that reaches outside its own process for something it
does not use can fail for reasons that have nothing to do with the code.

It surfaced as speed. On Windows, files building an app per test ran at
5-7 seconds each against 0.5 for files building none, and each app
construction emitted two pyvisa-py `UserWarning`s about missing `psutil`
and `zeroconf`. Warnings tracked app constructions exactly; time tracked
warnings. Installing those two packages would have silenced the warnings
by making the scan *wider* - `psutil` is what lets pyvisa-py enumerate
every network interface rather than just the default.

`test_no_network_in_tests.py` asserts the stub is in force. An autouse
fixture is invisible, and an invisible fixture that silently stops
working leaves nothing behind but a slow suite and a dependency nobody
can see.

`test_visa_backends.py` opts out with the marker, because it *is* the
test of `list_available()`. It substitutes its own fake pyvisa, so it
reaches no network either.

Nothing here stops the application or `tools/smu_checkup.py` scanning.
The stub is scoped to the test session.


## Mutating outside the runner

`run_tests.py` passes `PYTHONDONTWRITEBYTECODE=1` to every pytest
subprocess, because CPython validates a cached `.pyc` on the source's
mtime and size — so a same-length edit inside one mtime tick leaves
stale bytecode running. That silently invalidates mutation testing,
which is the technique most of this project's real defects were found
by, and it fails in both directions: a mutation can persist after it is
reverted, or be masked so the test that should have caught it appears
not to.

The runner protects itself. **A bare `python -c`, a hand-run script or
an editor's test runner still caches**, so clear `__pycache__` when
mutating outside `run_tests.py`.

`tests/test_bytecode_staleness.py` demonstrates the mechanism rather
than trusting it, pinning both mtimes with `os.utime`.

## A guard that counts imported GUI modules will fail this runner

`pytest -m "not gui"` **imports every module it collects before
deselecting any of them.** So a guard phrased as "fail if more than one
GUI module is imported into this process" fails the runner's own non-GUI
pass, where importing all of them is correct.

`_dialog_recorder_belongs_to_this_file` in `conftest.py` therefore
checks ownership by identity at the moment a GUI test runs, not how many
modules were imported. Worth knowing before writing a similar guard:
collection-time imports are not evidence of what a test touches.
