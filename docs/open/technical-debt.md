---
type: state
title: "Known technical debt"
---

# Known technical debt

Recorded so it is not rediscovered as a surprise.

**A resolved item is deleted from this file**, once `CHANGELOG.md`
records it. It is not marked "Closed" and left in place. This file
answers *"what is still wrong?"*, and an entry that has been fixed
answers a different question - the changelog already answers that one,
with the date and the reasoning. Closed entries left here had grown to
roughly half the file, which is how a page meant to be read before
starting work becomes a page nobody reads.

The exception is an item whose resolution changed what it is rather than
removing it. Those are rewritten, not deleted, and say what changed.

- **`code_fingerprint()` hashes the path string, so an absolute path
  makes the digest machine-specific.** The path is included
  deliberately - without it, drivers with identical contents would be
  indistinguishable - but nothing normalises it first. A caller that
  passes `/home/someone/repo/drivers/x.py` rather than `drivers/x.py`
  gets a digest nobody else can reproduce, and the symptom is an
  instrument reading stale on another machine with nothing actually
  different. Found 2026-08-28 by calling `code_paths_for()` with an
  absolute source path and spending twenty minutes hunting a divergence
  that was not there. `tools/smu_checkup.py` passes relative paths, so
  no shipped report is affected. Normalise to repo-relative POSIX form
  inside the digest, and the separator question goes away with it -
  `drivers\\x.py` and `drivers/x.py` currently hash differently.

- **The GSM-20H10's intermittent USB-TMC read timeout is not
  explained.** Three runs lost on 2026-08-25, six consecutive on
  2026-08-27, none in four on 2026-08-28 — same backend, same code, no
  configuration change. It predates Wave 8a: the 2026-08-25 bench notes
  record it, and before the latch it cost a run rather than stopping
  one.

  Excluded by probe, not by argument: the command is implemented, it
  answers on an empty queue, `*RST` is not still executing, no single
  command in the reset block is guilty, and the whole session replays
  over the console at machine speed without failing.

  Two things would make the next occurrence informative rather than
  repeating this. **One bounded read after the timeout, before
  latching**, recording whether the reply arrives late, never arrives,
  or is something else entirely — evidence, not recovery, and it would
  have answered this in one run. **And a verified resync** to replace
  the blanket refusal: Wave 8a removed the device clear on evidence
  from `libusb-win32`, where it returned False, and that was never
  measured on USB-TMC. A clear followed by a discriminating query,
  continuing only on proof, keeps the guarantee without generalising
  one backend's measurement to the fleet.

  Also open, from the same traces: the driver asks for `timeout_s=3.0`
  and the failure took 4.01 s every time. `VisaTransport._read()` sets
  `res.timeout = 3000` and restores it, so the value in force was not
  the value requested.

- **`:TRACe:FEED?` is never asked.** The driver probes three tokens and
  caches whichever the instrument accepts, which works. One query would
  replace three writes and three drains, leave no `-140`s in the queue
  for the next reader to misdiagnose, and — the actual reason — say what
  the buffer is *storing*. A buffer left on `CALCulate1` returns math
  results where raw readings are expected, and nothing in the data says
  so. Same readback lesson as D5/D6.

- **Direct GPIB-HS is commissioned but not stress-tested.** The
  B2901A passed all three tiers on 2026-08-18, which covers ordinary
  use. Four narrower questions have never been put to hardware, and the
  transport is described in
  [Direct NI GPIB-USB-HS transport](../architecture/direct-gpib-usb-hs.md):

  - a deliberately large sweep reply, against the upstream synchronous
    read limit and its truncation boundary
  - a deliberately induced timeout: does reopening the adapter, pulsing
    IFC and sending Selected Device Clear realign the stream at all?
    Since Wave 8a the answer does not change what the software does — a
    read timeout latches the transport either way, and `clear()` no
    longer starts a session — but it decides whether that latch is
    conservative or necessary here
  - repeated connect/disconnect, including after a failed connection
  - whether `GPIB0::<addr>::INSTR` locks out a simultaneous VISA
    claimant through the shared ownership key

- **Order-dependent test files.** Eight files share Tk roots and
  fake-driver classes across tests via `global`, preserving the
  behaviour of the original scripts. They cannot be run in isolation and
  would break under `pytest-xdist`. Convert to module-scoped fixtures as
  each experiment is touched in Waves 3 and 5.
- **Two test styles coexist**: converted section tests using the `check`
  fixture, and wrapped collector tests. Documented in
  `tests/README.md`.
- **The miniSMU's traffic bypasses the transport contract.** Its driver
  calls `transport.client.<method>()` directly, so the desync latch in
  `Transport.query()` never sees it. `MiniSMUTransport` carries method
  calls rather than a text request/response stream, so it probably
  cannot desynchronise in the same way — but that is a suspicion, not a
  measurement, and nobody has asked `minismu_py` the question.
  `tests/test_transport_desync.py` exempts it by name.
- **The stage's shutdown confirmation names the dangerous states, not
  the safe ones.** `confirm_pid_off()` treats `HEATING` and `COOLING` as
  driving and everything else as not, so a firmware that grew a third
  driving state would read as confirmed off. The inverse default was
  rejected deliberately - every unrecognised state would then warn on
  every close, and a warning that always fires is one nobody reads - but
  it means the set is a claim about the firmware that nothing checks.
  One line in the firmware's own status enum, compared against this set
  at connect, would close it. Until then the pairing is a convention.

- **`core.driver_registry`** remains as a deprecation shim. Remove once
  nothing external imports it.
- **Five `int(float(...))` call sites remain in the experiments** — 4PP
  points and reversals, IV points, runs and cycles. Wave 2 built the
  validators that replace them but deliberately did not touch an
  experiment file; Waves 3 and 5 swap them over as each experiment is
  wired up. The seven in `drivers/` parse SCPI error codes and are
  correct as they are.
- **`SampleRegistry` is process-local**, like Wave 1's ownership
  manager. If the answer to "can two instances of the app run at once?"
  turns out to be yes, both need revisiting together.

  **Narrowed, not closed.** The part of this that was a live hazard —
  the registry's collision re-draw being the only thing standing
  between two processes and a shared identifier — is gone: the random
  tail is 64 bits, so uniqueness across processes now rests on the
  width rather than on a check that only ever saw one process's
  identifiers. Run identifiers carry a per-process `SESSION_ID` for the
  same reason. What remains is what the entry originally said and is
  not about collisions at all: two instances would each hold their own
  label-to-identifier map, so the *same* physical sample measured in
  both would be minted twice and the carry-over between experiments
  would not be provable. That still needs the ownership manager
  revisited alongside it.
- **Cancellation cannot preempt a reading in progress.** The settle
  delay is handed to the instrument with `set_source_delay()`, so it
  happens inside the driver's blocking `measure()`. The honest bound is
  one reading, and `test_4pp_lifecycle.py` measures the rest of the path
  rather than asserting it. Moving the settle into `run.sleep()` would
  make cancellation near-instant but would change *where the settle
  happens*, which is a measurement parameter and not a UI detail — it
  needs a bench comparison before it goes near real hardware.
- **GUI test files patch `messagebox` on shared modules at import
  time**, so in one pytest process the last file imported wins and the
  others assert against a recorder nothing writes to. `run_tests.py`
  hides this by giving each GUI file its own process. The fix is a
  fixture that patches and restores per test, the way
  `_no_instrument_discovery` already does in `conftest.py` — a
  shared-layer change across every GUI file, so it wants a wave of its
  own and must not ride along with an unverified instrument. It buys no
  speed; it is a correctness change. Deferred deliberately: the hazard
  only fires under plain `pytest`, which is not how this suite is run.
  Measured in [the test suite audit](../reference/test-suite-audit.md).
- **A guard for the above now exists; the fix still does not.**
  `_dialog_recorder_belongs_to_this_file` in `tests/conftest.py` fails
  any GUI test whose dialog seam is owned by another test file, so a
  hand-run `pytest tests/` reports the contamination instead of a
  meaningless green. It does not make those files independent — that is
  still per-test patch-and-restore in each of them.

  It checks ownership by identity at the moment a GUI test runs. Two
  files that install their recorder inside a fixture rather than at
  import are not covered, and do not need to be.
- **A seam nobody claimed is a separate hazard, now also guarded.**
  `_a_gui_test_never_reaches_a_real_dialog` fails a GUI test that
  raises a dialog on a seam no test has stubbed — shown or merely left
  in the UI queue. Ownership cannot catch that case: with no owner
  there is nothing to disagree with. See
  [fault 28](../faults/28-a-dialog-nobody-stubbed.md).

  This too is a guard rather than a fix. The fix remains per-test
  patch-and-restore in every GUI file, which would make the question
  moot.
- **The Keithley 2450 has no dedicated driver test file**, alone among
  the text-dialect drivers, and is covered only by the registry-driven
  contract files. A mutation confirmed the practical effect: changing one
  of its output spellings turned exactly one generic test red. Not
  urgent, and not obviously wrong given the contract files — but it
  should be a decision rather than an accident, and it belongs to
  whichever wave next touches that driver.
- **`test_4pp.py` still drives `_do_run()` on the main thread.** Its
  green says nothing about threading; that is `test_4pp_lifecycle.py`'s
  job. Left as-is deliberately: churning a 434-line passing test file is
  where a real regression hides.
- **The generated indices record `file:line`.** `deviation-index.md` and
  `review-index.md` cite source line numbers, so *any* edit that shifts
  a line makes them stale and fails `test_generated_pages_match_a_fresh_build`.
  `uv run python tools/build_docs.py` therefore belongs in every patch
  that touches code, not only in documentation patches.

  The scan is now over tracked files only
  ([fault 35](../faults/35-derived-from-whatever-is-lying-around.md)),
  which removes the untracked-junk half of this but adds a smaller
  consequence in its place: a **new** module contributes no citation
  until it is `git add`-ed. Deliberate — these pages are committed
  artifacts and should describe the commit — but it will read as a
  missing row to somebody who has not staged their work yet.

  Related, and mildly misleading when it happens: that test writes the
  fresh build before asserting, so a failure leaves the working tree
  dirty and an isolated re-run passes against the files the failed run
  just regenerated. It looks like order-dependence and is not. Restoring
  on failure would make the second run tell the truth.

- **The operational log transcribes `metadata` verbatim**, by design -
  an operator note belongs in the log. Nothing in `core/event_log.py`
  can stop a caller putting a measurement value in it, so §26's
  boundary holds there by convention rather than by construction.
  `experiments/base_experiment.py` passes `context.metadata`, which
  today holds parameters and notes and never readings. Worth a
  narrowing rule - an allowed key list, or a numeric-value refusal - if
  a future experiment starts putting richer things in metadata.

- **Several drivers still cannot be asked what range they are on.** The
  readback *contract* is no longer the gap — `core/readback.py` gives
  range, compliance and power limit a five-state answer, and a
  disagreement on any of them is a loud failure whether or not the
  readback itself has been verified (see
  [fault 33](../faults/33-a-setting-never-read-back.md)). What remains
  is per-driver spellings.

  Implemented: the 2611A and 2635B on all four axes (TSP attribute
  reads, the same mechanism those drivers already use for
  `localnode.linefreq`), and the GSM-20H10 on both measurement axes —
  where `SENS:CURR:DC:RANG?` is the query the bench itself read
  `1.050000E-05` from on 2026-08-20, which is the observation the whole
  item was written for.

  Still `unsupported`, and recorded as such in the contract ledger with
  the reason: the **2401, 2450, B2901A and miniSMU**. Nobody has
  confirmed a query spelling on any of them, and the U2722A's
  `SOUR:CURR:RANG?` is an open question in its own note rather than a
  fact. Guessing is not the conservative option — an unrecognised
  *command* is logged and ignored, but an unrecognised *query* is never
  answered, times out, and latches the transport. So a guess costs a run
  rather than a line in a report.

- **No range readback anywhere is verified.** `RANGE_READBACK_TRUSTED`
  is False on every driver, so an agreement reports `unverified` — a
  warning, never a pass. A *disagreement* is still a failure, which is
  what closes the GSM-20H10 case above. Closing the rest is one bench
  step per instrument: set a range from the front panel, ask for it over
  the bus, confirm the answer names the range that is physically
  selected.

- **Most compliance readbacks are unimplemented.** `compliance_readback`
  in the contract ledger records which. Only the GSM-20H10 (verified
  2026-08-20) and the U2722A (verified 2026-08-24, including the case of
  a limit the instrument had refused) both implement it and have it
  checked; the other six report `unsupported`. So a clean checkup on
  those instruments still means *none observed*, not *none*. Closing it
  is one bench session per instrument: set a distinctive compliance,
  read it back, confirm it agrees.

- **A stateful fake gives a different answer to a second `Checkup`.**
  Not fixed, and probably not fixable in general — recorded because it
  cost a mutation round. A fake that consumes state as it is read (a
  ramp, a queue, a one-shot fault) has already spent it by the time a
  second run starts, so an assertion made against run two can pass while
  the behaviour under test is broken. Take every result from one run.

- **`limitp` on the 2635B is watched now, and the watching is
  unverified.** `read_power_limit()` sends
  `print(smua.source.limitp)` and the checkup compares it against the
  0 the driver writes; a nonzero value is a loud failure, because a
  power ceiling overrides whichever of the three limits is lower and
  `limitv` reports the programmed value rather than the effective one.

  What is left is the same one bench step as every other readback here:
  `POWER_LIMIT_READBACK_TRUSTED` is False, so an agreement reports
  `unverified` rather than `pass`. This instrument has never been on a
  bench at all, so that flag cannot move until it has.

## Found by the 2026-08-25 U2722A probe round

- **A sub-count source level is unguarded everywhere except the
  U2722A.** Deviation 54 refuses a level below ten counts of the active
  range on that instrument, after the bench established that below one
  count the output is offset residue whose *sign is not commanded* —
  `-1 µA` and `+1 µA` produced the same output on R120mA, and during the
  commissioning round the residue pointed the wrong way and drove the
  output to the range rail.

  Nothing about that mechanism is specific to the U2722A. Any
  fixed-range converter has a bottom count, so a small level on a wide
  range is possible on any of them. What differs is whether anything
  puts it there.

  **`D7` is closed.** It said `RangePlan`'s shared-knob reconciliation
  could drag a source axis onto the widest range on any shared-knob
  instrument. Every driver setting `INDEPENDENT_SOURCE_RANGE = False`
  was checked, and none is in that position:

  - **U2722A** — was, and is not since 2026-08-25. Deviation 52 takes
    the range from the compliance limit and forces it, and deviation 54
    re-checks it before every level write, so whatever `apply_ranges()`
    picks is overwritten before anything is sourced. The `-222` trace
    D7 was named for cannot recur.
  - **miniSMU** — never was. Its current range is a **measurement**
    range, established 2026-08-27 from the vendor library's wire
    commands: the voltage range sends `SOUR1:VOLT:RANGE` and the current
    range sends `CH1:IRANGE`, and `set_autorange` switches range "for
    the measured current". A source level is never judged against it.
    The 2026-08-21 note calling this the same defect was reasoning by
    analogy from the U2722A. See the instrument note.

  **What is still open is the sub-count floor**, which is a different
  claim: below one count of whatever range is active, is the output
  residue with uncommanded sign, as it is on the U2722A? Only that
  instrument refuses it. Unmeasured on the Keithleys, the B2901A and the
  GSM-20H10.

  It is now *declared* rather than merely absent. Every driver carries
  `SUB_COUNT_LEVELS` per axis with one of three values — `refused`,
  `unmeasured`, `not applicable` — the contract ledger forces the
  decision, and the checkup raises a **warning** on every `unmeasured`
  axis rather than passing over it. So every instrument but the U2722A
  now carries a standing warning per axis, and each one is closed by a
  measurement rather than by an edit: command plus and minus a small
  fraction of a count on a wide range, and see whether the output
  follows the sign.

  The mechanism for refusing is in `BaseSMU` (`source_level_floor()` and
  `guard_source_level()`), so a driver that measures its converter
  declares a floor and gets the refusal, instead of reimplementing the
  U2722A's. **No fleet-wide floor was invented**, deliberately: a
  refusal threshold on an instrument nobody has measured would be a
  number with no bench behind it, refusing levels that may be perfectly
  good.

  Not the miniSMU, though. A source current there has no range of its
  own to fall below, so the question does not arise in the same form and
  should not be asked in the same way — that axis is declared
  `not applicable`, and its voltage axis `unmeasured` like the rest of
  the fleet. What a sub-count source level means on an instrument with
  no source current range is itself unmeasured.

  **Also open: whether the two range flags describe this instrument.**
  `INDEPENDENT_SOURCE_RANGE = False` claims a source and measure range
  share a knob; on the miniSMU there is no source current range at all.
  The resulting behaviour is correct and the driver is commissioned
  against it, so the flags are deliberately left alone. Changing them
  changes `apply_ranges()` on a working driver and needs its own wave.

  Deliberately not folded into the deviation 54 patch: one concern per
  wave, and a fleet-wide level floor is a different concern from one
  instrument's.

- **The checkup can now pass on the U2722A, and has not yet been run on
  it.** The tool no longer probes at a module-wide `1e-6`: the nominal
  levels are clamped into each model's declared envelope, and after the
  ranging plan has been carried out the driver is asked what its floor
  is *on the range that is now active* and the level is raised to it. On
  the U2722A that lands at ten counts of R120mA — the range the
  shared-knob reconciliation puts the current axis on — instead of a
  seventh of one count. See
  [fault 34](../faults/34-a-probe-the-instrument-cannot-express.md).

  What remains is a bench fact rather than a code one. The 2026-08-25
  report on that instrument records `bench_result: fail` for exactly
  this reason, and it stands until somebody runs the checkup again
  against the hardware. Whether it *does* pass is not something this
  repository can assert.

## Lint rules deliberately left off, with their counts

Review A-09 configured the first automated quality gate this project has
had. The criterion for a rule being in `pyproject.toml`'s `select` is
not "is it a good idea" but **"is it green on this tree today"**, because
only a green gate can be required to stay green - a run with every rule
enabled produces about 12,800 findings here, and a job that starts
12,800 in the red is how a real failure gets waved through.

These are the rules that did not meet that bar. Each is a scoped task
rather than a rediscovery; adopting one means fixing its findings and
deleting its line from `ignore`.

- **`B905` (23): `zip()` without an explicit `strict=`.** The most
  valuable of these, and the one that most needs a person. A silently
  truncated zip of readings against labels is exactly the class of fault
  this project keeps finding. It is deferred because the fix is a
  per-site judgement and getting it wrong is not neutral: `strict=True`
  on a pair that legitimately differs turns a working measurement into a
  crash at the bench, and `strict=False` everywhere is a rubber stamp
  that makes the rule permanently useless. It wants a pass with the data
  in front of you, one call site at a time.

- **`S110` (74) and `S112` (3): `try/except/pass` and
  `try/except/continue`.** Not deferred for effort - deferred because a
  linter cannot answer the question. A suppression in a `close()` path
  is correct and one on a data-preservation path is
  [fault 29](../faults/29-a-shutdown-that-fails-open.md), and the two
  are spelled identically. [House rule 13](../rules/13-exceptions-are-not-suppressed-silently.md)
  states the policy and `tests/test_exception_policy.py` enforces the
  half that can be enforced mechanically.

- **`BLE001` (209): a bare `except Exception`.** The superset of the
  above and the same argument, with the difference that most of these
  handlers *do* something. Worth revisiting only after the guarded
  surface below is complete.

- **`E402` (416): an import that is not at the top of its module.**
  Almost all of these are the deliberate `pytestmark = [pytest.mark.gui]`
  before the imports, and imports after a `sys.path` insert in the
  tools. Adopting it means a `per-file-ignores` entry per file, which
  buys a rule that would then be ignored in every file it fires in.

- **`RUF100` (35): a `# noqa` that suppresses nothing.** It fires on
  every `# noqa: E402` in the tree, and those are correct - they mark an
  import that deliberately follows a path insert, and they are
  load-bearing documentation whether or not `E402` is switched on.
  Deleting 35 of them to satisfy a rule about stale suppressions would
  delete the explanation rather than the staleness. This becomes worth
  enabling the day `E402` and `BLE001` are.

- **`E741` (54): an ambiguous variable name (`l`, `I`, `O`).** Renaming
  54 variables across the drivers and the maths modules is real churn on
  files whose diffs are read closely; it belongs to whichever wave next
  touches each file.

- **`DTZ005` (19): `datetime.now()` with no timezone.** These write
  local naive timestamps into CSV headers and file names. Changing them
  changes the stored data format, which is a schema decision and not a
  lint fix.

- **`ANN` (6,140) and the pylint convention, refactor and warning
  categories (816, of which `PLE` is 0 and is enabled).**
  The noise the audit measured. Type annotations are being adopted at
  the boundaries instead - see `[tool.mypy]` in `pyproject.toml` - and
  the complexity findings are a design conversation rather than a gate.

- **The exception policy covers a named surface, not the tree.** 55 of
  the 62 blind suppressions in production code had no stated reason when
  house rule 13 was written. The fourteen files in
  `tests/test_exception_policy.py`'s `GUARDED` list were given one; the
  drivers, transports, panels and tools were not. Doing all 55 in one
  change would produce 55 sentences nobody had time to mean, so it is a
  per-area pass, and adding a file to `GUARDED` is how each area is
  closed.

- **Coverage is not measured.** A-09 asks for coverage tracked by risk
  area - failure paths for close/shutdown, generated docs, driver
  readbacks - rather than a global percentage, and Wave A added
  substantial tests in exactly those areas. Nothing reports on it yet.
  The obstacle is `run_tests.py`: coverage over thirty separate pytest
  processes needs `coverage combine` and a parallel-mode configuration,
  which is a change to the runner and wants its own wave. Enforcing a
  global threshold remains explicitly out of scope.
