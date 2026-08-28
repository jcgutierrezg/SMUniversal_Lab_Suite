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

- **`apply_ranges` still reports what it sent, not what was accepted.**
  Partly addressed 2026-08-20: `verify_compliance()` and the checkup's
  *compliance survives ranging* check cover the **limit**, which is the
  half that can hurt a sample. The **range** half is still open — the
  GSM-20H10 will refuse a measurement range and silently leave a
  narrower one in force (`SENS:CURR:DC:RANG?` reading `1.050000E-05`
  after `1E-4` was asked for), and nothing notices.

  Left open deliberately rather than bundled in. Reading a range back
  needs its own per-driver spelling and its own bench verification, and
  the compliance readback already showed why that matters: on the
  GSM-20H10 `OUTP?` answers dishonestly, so a readback is only worth
  having where somebody has checked it against a value the instrument
  was known to hold.

- **Most compliance readbacks are unimplemented, and the U2722A's is
  unverified.** `compliance_readback` in the contract
  ledger records which. Until a driver both implements it *and* has it
  checked at the bench, the checkup's new check reports `skip` or
  `unverified` rather than `pass` — so a clean checkup on those
  instruments still means *none observed*, not *none*. Closing this is
  one bench session per instrument: set a distinctive compliance, read
  it back, confirm it agrees.

- **A stateful fake gives a different answer to a second `Checkup`.**
  Not fixed, and probably not fixable in general — recorded because it
  cost a mutation round. A fake that consumes state as it is read (a
  ramp, a queue, a one-shot fault) has already spent it by the time a
  second run starts, so an assertion made against run two can pass while
  the behaviour under test is broken. Take every result from one run.

- **`limitp` on the 2635B is a ceiling nothing watches.** Power
  compliance applies whichever of the three limits is lower, and reading
  `limitv` back reports the programmed value rather than the effective
  one. It resets to disabled, but `Recall setup` can carry a nonzero one
  into a session, and a checkup would not notice. One query after
  connect would.

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

  Not the miniSMU, though. A source current there has no range of its
  own to fall below, so the question does not arise in the same form and
  should not be asked in the same way. What a sub-count source level
  means on an instrument with no source current range is itself
  unmeasured.

  **Also open: whether the two range flags describe this instrument.**
  `INDEPENDENT_SOURCE_RANGE = False` claims a source and measure range
  share a knob; on the miniSMU there is no source current range at all.
  The resulting behaviour is correct and the driver is commissioned
  against it, so the flags are deliberately left alone. Changing them
  changes `apply_ranges()` on a working driver and needs its own wave.

  Deliberately not folded into the deviation 54 patch: one concern per
  wave, and a fleet-wide level floor is a different concern from one
  instrument's.

- **The checkup cannot pass on the U2722A while it probes at 1 µA.**
  Closed as a crash, open as a result. The tool asks for `PROBE_CURRENT
  = 1e-6` and the U2722A now refuses it, correctly - the configuration
  is impossible on the range the plan lands on. So the report will carry
  one honest failure rather than one wrong one, which is better and not
  clean.

  Fixing it properly means the checkup choosing a probe level from each
  instrument's own envelope rather than from a module constant, which is
  a third concern and was not folded in.
