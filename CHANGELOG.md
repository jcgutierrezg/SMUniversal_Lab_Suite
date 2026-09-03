# Changelog

Newest first. **Append-only**: a new entry goes on top and existing
entries are not edited.

**What an entry says is what changed and why it matters** — the
conclusion, and what was added or removed. Not how the conclusion was
reached, and not the incident that led to it.

The reasoning is not thrown away; it is put where it will be found
again. A measured fact about an instrument goes in
`docs/instruments/<name>.md`. A mistake worth not repeating goes in
`docs/faults/`. A design constraint goes in `docs/architecture/` or
`docs/rules/`. Anything that survives none of those tests was working
material, and carrying it here costs more than it pays.

**A retracted hypothesis never appears.** Read back cold, an account of
a wrong mechanism is indistinguishable from a finding, and this file has
misled its own authors that way. See
[A probe asked where the answer is already known](docs/faults/19-non-discriminating-probe.md).

> **Two exceptions have been made to append-only.** On 2026-08-27 every
> entry above Wave 6e was condensed under the rules above, and on
> 2026-09-03 every entry above Wave 7g was. Nothing was deleted without
> first checking that it lived in the file that owns it, or moving it
> there — the second pass moved incident narrative into the fault notes,
> which is where it belongs and where it is now in a comparable shape.
> Both were deliberate, single breaks of the rule; the rule holds either
> side of them.

The work up to Wave 7 was organised as numbered waves adopting one code
review. That adoption ended with Wave 7; the numbering continues from
Wave 8 as a plain sequence number for a unit of work.

## The suite can use the whole machine, and mostly should not

`run_tests.py` takes `--jobs` (or `SMU_JOBS`). The default leaves
`RESERVED_CORES` free; `--jobs 1` is unchanged from what this runner
has always done, and is what CI passes.

The budget is **split rather than shared**, because the two kinds of
group behave in opposite ways. Non-GUI files are CPU-bound and divide
the work, so they are dealt across shards. GUI files pump a Tk event
loop and waiting does not divide, so they are capped at `GUI_WORKERS`
however wide `--jobs` is.

Measured with `--all` on one 16-core machine:

| | wall clock | GUI machine-time | slowest GUI group |
|---|---:|---:|---:|
| `--jobs 1` | 836 s | 647 s | 52 s |
| one pool of 12 | 558 s | 4,781 s | 455 s |
| split, 9 + 3 | 440 s | 1,089 s | 110 s |

A single pool of twelve cost 7.4x the machine time to run the same
tests and returned 1.5x for it. It also took `test_combined_window`
from 52 s to 455 s against a 600 s `GROUP_TIMEOUT_S` — a passing test
one slower machine away from being killed and reported as a hang, which
is the failure this runner exists to make impossible.

Tests that assert an **upper** bound on elapsed time now carry a
`timing` marker: deselected from the parallel phase and run afterwards,
alone. `elapsed < 0.26` is a claim about the machine as much as about
the code, and contention has twice sent someone here to investigate a
result that meant nothing. Lower bounds are not marked — contention can
only make those more true.

## The documents stop keeping their own chronology

Audit finding A-10. Records were carrying history in places that are
read for current fact, so a reader had to date a sentence before
trusting it.

**The code review is deleted.**
`LAB54_DEVELOPMENT_REVIEW_AND_WORKFLOW.md` was 1,953 lines, scheduled
for deletion once Wave 7 closed, and still present two waves later — and
about 210 source comments cited it as `review §N` or `group B3`. For
several modules that citation was the only recorded reason the module
existed. Every one was replaced with the house rule, architecture page
or fault note that actually holds the fact, before the file was removed.
Where a cited section held something nothing else recorded, that fact
moved first: the driver state-transition traces are now
[house rule 12](docs/rules/12-configure-before-energising.md), and the
CI shape and the interpreter-source constraint are in
[delivering work](docs/workflow/delivering-work.md).
`tests/test_docs.py` refuses a new citation, so one cannot come back
pointing at nothing.

`docs/reference/review-index.md` and the `review_citations()` /
`REVIEW_CARRIED_BY` machinery in `tools/build_docs.py` go with it. That
index existed to make the deletion safe; it has now done its job.

**The fault catalog has one shape.** All forty notes are
Symptom / Cause / Risk / Detection / Prevention / Status / Evidence, so
two can be compared without reading both end to end. `Detection` and
`Prevention` are separate because most of these faults were survivable
once somebody knew to look, and the looking is the transferable part.
`Status` is new and says what is closed and on what — "closed on the
GSM-20H10, open on the rest of the fleet" is the common case here, and a
note that does not say so reads as closed. No finding, reproduction
detail or bench measurement was dropped; discovery narrative was.

Faults 22 and 23 were missing from `docs/faults/_index.md` and are back
in it.
[A document holding state that git already owns](docs/faults/40-a-document-holding-state-git-owns.md)
is new: `HANDOFF.md` named a branch that had been merged and deleted on
the remote, and three readers of the same repository disagreed about
whether it existed, all reading unpruned tracking refs. The fix is to
remove the dependency, not to update the value.

**`docs/open/technical-debt.md` is a table**, graded by impact —
safety, data, evidence, correctness, maintenance — with evidence, next
action, validation needed and status per row. It was two dozen prose
items of a page each, which is unprioritisable. Every open item
survived; several were split where one bullet held two separable
problems, and the items Wave A and Wave B closed are gone from it,
because this file answers *what is still wrong* and the changelog
already answers the other question.

**`pyproject.toml` and the CI workflow keep their constraints and lose
their stories.** 398 lines to 262 and 134 to 111; comment share 68% to
52% and 43% to 31%. The Python floor, the packaging `packages` list, the
wheel force-include, the exact `ni-gpib-usb-hs` pin, the
`--strict-markers` rationale and every Ruff rule's reason all stay. What
left: the account of the bench machine that installed 3.11 and turned
the goldens red, now in
[fault 18](docs/faults/18-accidental-accuracy.md) with the rule it
taught — *a constraint nothing tests is not a constraint*; and the
Windows `TclError` under a uv-managed interpreter, now in
[delivering work](docs/workflow/delivering-work.md).

**`Wave N` framing is out of the source comments.** A comment saying
when something changed dates itself; one stating the invariant does not.
Every one now says what is true rather than which wave made it so.

<!-- The parallel documentation-truth work (audit finding A-10, the
     onboarding and router documents) belongs in this entry. Its
     summary goes here at merge. -->

## Generated files no longer depend on the machine that made them

Audit finding A-06. One rule underneath four defects: **what a tool
writes must be determined by the repository, and by nothing else about
the machine.**

`tools/build_docs.py` walked `ROOT.rglob("*.py")`, so a `.uv-cache`
inside the checkout and agent worktrees under `.claude/` both fed a
generated page from files no commit contains. `tests/test_docs.py`,
`test_packaging.py` and `test_build_artifact.py` walked the same tree.
All now use `build_docs.owned_files()`, which lists tracked files, with
a filtered walk as the fallback where git cannot answer. Recorded as
[fault 35](docs/faults/35-derived-from-whatever-is-lying-around.md).

Generated pages were written with CRLF on Windows and staleness was
judged with `read_text`, which decodes both forms identically — so every
`--check` that should have caught it passed. Writes go through
`write_lf` and staleness is judged on **bytes**. Measurement CSVs had
the same disagreement: the builders set `lineterminator="\n"` and
`write_atomic()` translated it. **Decided as LF** by preserving what the
builder produced; no schema bump. Recorded as
[fault 36](docs/faults/36-two-ends-disagreeing-about-newlines.md) and in
[the stored-file schema](docs/reference/schema.md).

`.claude/` is now ignored, without a trailing slash, so a symlink of
that name cannot be swept into a patch the way `.venv` once was.

Each fix is proven against a constructed failure rather than a tidy
tree, and the newline fixes are asserted on bytes read back from a file.

## A quality gate that is green, and an install only as wide as the machine

Audit findings A-09 and A-11.

**The lint gate.** Ruff with every rule enabled reports about 12,800
findings here, and a job that starts 12,800 in the red is how a real
failure gets waved through — so the criterion for enabling a rule was
"is it green on this tree today". On: `E9`, `F`, `I`, the comparison
mistakes that read as correct, `E722`, `B`, `S`, `PLE` and `T10`. 93
findings were fixed to get there. Ruff and mypy run as their own CI job.
The valuable-but-noisy rules are listed with counts and reasons in
[technical debt](docs/open/technical-debt.md).

Two findings were defects rather than untidiness, both in the tree since
the first import: `BaseSMU.measure()` was not abstract and returned
`None`, so a driver could omit the one method every experiment calls and
produce a full-length trace of blank readings that commits and saves
([fault 38](docs/faults/38-a-contract-method-that-was-not-abstract.md));
and `FourPointProbeExperiment.delete_ticked()` overrode the base without
calling it, losing both the confirmation and the provenance
invalidation
([fault 39](docs/faults/39-an-override-that-dropped-its-guard.md)).

**The exception policy.**
[House rule 13](docs/rules/13-exceptions-are-not-suppressed-silently.md):
safety, data-preservation and provenance paths do not suppress. `S110`
is deliberately not enabled — a linter sees the shape and not the path,
so it flags a correct `after_cancel` cleanup and a wrong shutdown
identically. `tests/test_exception_policy.py` does what a linter cannot,
over fourteen named modules, checking that a reason was **written**;
no test can check that it is true.

**Types at the boundaries.** `uv run mypy` checks seven files: the
transport protocol, the driver contract, run control, the parameter
snapshots, the ranging plan, the per-model envelope and the readback
answer. It found `nplc`, `high_z`, `ovp` and `voltage_range_v` declared
as bare types with a `None` default, where `None` means "leave the
instrument alone" rather than "send a default". They are `| None` now.

**Optional extras.** `minismu`, `usb`, `direct-gpib` and `bench`.
`uv sync --extra bench` reproduces exactly what a plain `uv sync`
installed before, so the bench workflow is one flag longer and nothing
else. Each extra has a named failure message and a test that provokes
it.

**A dependency audit that does not block.** `pip-audit` runs weekly
against the locked environment, and on demand. Blocking a merge on an
advisory published today would fail whoever opens the next PR for
something they did not do. Nothing found on 2026-09-01.

## Closing the window no longer fails open

Two defects on the same stretch of `core/base_app.py`, both of the shape
where a failure on the exit path produced no symptom.

**The de-energise could not fail**, and could not have reported success
if it had: the stage firmware never acknowledges a command.
`TemperatureController.confirm_pid_off()` now returns a
`StageShutdownReport`, confirmed against a status line broadcast
**after** the OFF, and anything else raises a modal naming the stage.
Recorded as
[fault 29](docs/faults/29-a-shutdown-that-fails-open.md).

**The unsaved-measurement guard reported "nothing to lose" when it
broke.** `unsaved_state()` now returns a count plus the experiments it
could not read. An unknown state, a dialog that raises, and a dialog
that answers with nothing all leave the window open with a diagnostic on
screen. Recorded as
[fault 30](docs/faults/30-a-guard-that-fails-to-all-clear.md).

**`on_close()` is an explicit bounded sequence**: refuse new runs, cancel
every controller, wait for idle while draining the UI queue,
de-energise, disconnect, destroy. The wait is bounded by
`CLEANUP_TIMEOUT_S`, and expiry names the tab in a modal.
`Experiment.on_close()` now cancels the run instead of being an empty
hook, and `LabApp` cancels every controller directly so the guarantee
does not depend on a subclass remembering `super()`.

`tests/test_shutdown_safety.py` injects each failure in turn.

## A setting is a request until something reads it back

`apply_ranges()` reported what it *sent*, and so did every compliance
setter. A refused setting raises nothing on any instrument here, so a
successful write is evidence that the link works and nothing else.

`core/readback.py` gives the compliance, all four ranges and any
applicable power limit a five-state answer — `unsupported`,
`unreadable`, `unverified`, `confirmed`, `mismatched` — of which only
`confirmed` renders as a pass, and only where a bench session has
verified the readback itself. **A `mismatched` is a failure whether or
not the readback is verified**: trust governs what agreement is worth
and nothing else.

Implemented where the spelling is attested: all four axes on the 2611A
and 2635B, both measurement axes on the GSM-20H10. The rest stay
`unsupported` and say so, because an unrecognised query is never
answered, times out and latches the transport. No `*_READBACK_TRUSTED`
flag is set by this change; every one is a claim about a physical
measurement. `limitp` on the 2635B is now watched.

Recorded as [fault 33](docs/faults/33-a-setting-never-read-back.md);
what remains open is in
[technical debt](docs/open/technical-debt.md).

## The checkup probes at levels the instrument can express

`tools/smu_checkup.py` sourced a module-wide `PROBE_CURRENT = 1e-6` at
every instrument, which on the U2722A is a seventh of a count — so the
tool was **structurally unable to pass on a working instrument**.

Nominal levels are now clamped into each model's declared envelope, and
after the ranging plan has been carried out the driver is asked what its
floor is *on the range that is now active*. Every report's tier 1
carries a *probe levels* row saying which levels ran and why.

Sub-count behaviour is declared per axis on every driver — `refused`,
`unmeasured` or `not applicable` — and the checkup **warns** on each
`unmeasured` axis rather than passing over it. No fleet-wide floor was
invented; the refusal mechanism moved to `BaseSMU` so the next driver to
measure its converter declares a floor instead of reimplementing one.

The fakes now select the range that *contains* a written value and
report that range's full scale, because a readback check is untestable
against a model that echoes what was written.

**Nothing here changes what any instrument has been measured to do.**
Recorded as
[fault 34](docs/faults/34-a-probe-the-instrument-cannot-express.md).

## Stored records now identify the build that made them, and cannot collide

**A version that never moved.** `app_version` was `0.1.0` in every
stored file across many waves of behaviour change. Every file now also
carries `build_id` — the release with the commit welded on, `.dirty` on
a modified tree, `+unknown` where no build can be determined. A frozen
build reads a baked-in constant, so correctness does not depend on `git`
being on PATH. `unknown` is written rather than the key omitted.
Stored-file `schema` is 2. Recorded as
[fault 31](docs/faults/31-a-stamp-that-never-moves.md).

**Identifiers narrower than the claim beside them.** The random tail was
32 bits, chosen from a docstring's arithmetic that was wrong by a factor
of forty and quoted the wrong population. The tail is 64 bits now, and
run identifiers carry this process's `SESSION_ID` — a restart inside one
second, or a second bench machine, produced the identical first run
identifier, and `run_id` is the join key between stored rows and the
event log. Old widths still parse. Recorded as
[fault 32](docs/faults/32-arithmetic-in-a-docstring.md).

**Tagged releases, answered** in
[packaging](docs/workflow/packaging.md): the right mechanism for frozen
builds, nothing for the clone model, not adopted because the freeze has
never been run.

## The dialog that hung the suite, and the guard for the next one

A GUI test reached `messagebox.showwarning` without stubbing it, and the
outcome depended on the machine: pumping that spanned the 10 ms timer
opened a window that blocked forever, and pumping that did not discarded
the warning and passed. The discarded message was the one telling an
operator that a sample may still be energised.

`_a_gui_test_never_reaches_a_real_dialog` in `tests/conftest.py` fails
any `gui`-marked test that raises a dialog on a seam nobody stubbed,
shown or merely queued. Removing the stub now fails in about a second,
naming the dialog; before, it ran to the CI limit with an empty log.
Recorded as
[fault 28](docs/faults/28-a-dialog-nobody-stubbed.md).

## A hung test run can now say what hung

`run_tests.py` announced a group only once it had finished, and `print()`
to a pipe is block-buffered, so a run that never finished produced an
empty log and ran toward the platform's six-hour default.

Each group is now announced before it starts, killed if it exceeds
`SMU_GROUP_TIMEOUT_S` (default 600 s), and reported as `TIMEOUT` with
whatever output it had. A timed-out group does not stop the ones after
it. The pytest subprocess runs unbuffered. The CI job carries
`timeout-minutes`, and a test refuses a workflow without one.

No test or driver behaviour changes; this is the harness reporting on
itself.

## The bench pass, run across the fleet

Every instrument now carries a noise/rate envelope and a sub-count floor
in its note, measured 2026-09-01 at 100 uA into 9958 ohm. The floors
divide into two shapes and the difference decides how far each
instrument can be trusted: the B2901A, GSM-20H10 and 2401 run out of
**resolution**, while the 2611A and 2635B **drift**. The U2722A's floor
is declared rather than inferred, and a refusal is now recorded as the
floor rather than crashing the tool.

The 2635B is the fastest instrument here at 287 Hz and 0.001% RSD; the
U2722A's 1 PLC minimum caps it at 14 Hz. No floor was found for the
miniSMU — the probe ran out of ladder, not the instrument out of
resolution. Full figures in each instrument note.

## The bench pass, corrected against its first run

Six faults, all in the tool, found by running it across the bench on
2026-08-28 and again after. <!-- lint-ok -->

The control leg was itself sub-count, so it failed on instruments that
were working. A 1 A range request crashed the miniSMU. The verdict had
no upper bound, so a fixed offset cleared a threshold that shrank with
the request — the GSM reported twenty-one consecutive "sign follows"
rows on readings that were both positive. `RSD 0.000%` was quantisation
rather than quiet, and flattened every curve into something that read as
a perfect result. Both legs must now land on opposite sides of zero. And
the envelope now pins the same range as the sub-count phase, without
which the B2901A read a mean of 4.3e-7 A against a commanded 1e-4 at
every rung and looked like the best on the bench.

The tests are built from the readings the bench actually produced, so
the GSM's frozen rows and the B2901A's real result both have to keep
coming out the way they did. The general lesson is
[A bound checked on one side only](docs/faults/25-a-bound-checked-on-one-side.md).

## What the 2026-08-27 bench round found

Every instrument re-checked. <!-- lint-ok --> The B2901A, 2635B, 2611A,
2401 and miniSMU pass; the U2722A carries its one honest refusal. The
GSM is re-stamped from a clean 2026-08-28 run: 68 pass, no timeouts,
clean tree.

**`D7` is not closed, and the entry saying it was is wrong.** On the
U2722A the limit is overwritten by the range, not the other way round.
It is also narrower than filed: the reconciliation only runs where
source and measure share one knob. Confirmed from traces on every
driver, not from the flag.

**`:TRACe:FEED` on V1.16 rejects the token the manual gives as its own
example.** `SENS` is accepted; `SENSe1`, `SENS1`, `SENSE1` and `RAW` are
refused. The driver's existing probe already lands on `SENS`, so the
`-140`s in every GSM trace are that probe working. Both manual pages are
transcribed with the measured grammar beside them.

**Console scripts move to `probes/`**, gitignored — written into the
repository root they made every checkup report `dirty: True`, and a
provenance flag that is always set is one nobody reads.

The GSM's intermittent read timeout and a latent defect in
`code_fingerprint()` are recorded in
[technical debt](docs/open/technical-debt.md).

## One bench pass per instrument

`tools/bench_envelope.py`, run after `smu_checkup.py` on the same
connection and load, so the answers are comparable.

**The envelope**: at each rung of the NPLC ladder, the achieved sample
rate and the relative standard deviation of a burst. The first reading
is discarded, since every instrument here pays a large one-off after
`output_on()`. Relative standard deviation rather than peak-to-peak,
which is set by the single worst sample and grows with burst length.

**The sub-count floor**: halve the commanded level down from the bias
and ask at each step whether `+X` and `-X` still read differently.
Measured rather than predicted, because no driver here declares its
converter bits. The verdict requires separation greater than the scatter
*and* greater than the level asked for — an offline fake proved the
second is load-bearing by manufacturing the signal the check was looking
for.

Nothing is predicted from the load resistance: it was measured with one
of these instruments, so using it to judge them is circular. **The
reading noise is the detection limit and is not the source floor.**

## A desynchronised link could be un-latched by a device clear

Wave 8a made `connected` a property whose setter cleared the
desynchronised latch, and `NIUSBGPIBTransport.clear()` sets that flag on
its way out — so a device clear silently un-desynchronised a poisoned
session, through exactly the kind of unverified recovery the latch
exists to refuse.

Clearing is now an explicit `_begin_session()`, called from `connect()`
and nowhere else. `tests/test_transport_desync.py` checks over every
`Transport` subclass that each `connect()` calls it and that `clear()`
does not.

**`docs/open/` now holds only what is open.** The commissioned parts of
the direct-GPIB note became
[Direct NI GPIB-USB-HS transport](docs/architecture/direct-gpib-usb-hs.md);
the questions hardware has not answered stayed as debt entries.

## A documentation accuracy pass

Statements that later work made false, found by reading every page
against the code rather than by tripping over one of them.

Six pages described a device clear as the recovery for a timed-out
query. There is no recovery; the transport latches and only a reconnect
clears it. `docs/workflow/delivering-work.md` said patches are applied
with `git apply`; they are applied with `git am`, and the difference is
load-bearing, because `git apply` leaves the tree uncommitted so
anything derived from `git log` still reports pre-patch values.

Two fault pages both claimed number 21; the GPIB-HS page became 27.

`docs/open/technical-debt.md` now deletes a resolved item instead of
marking it closed and leaving it. Closed entries had grown to about half
the page.

## D7 closed: the miniSMU's current range is a measurement range

No driver setting `INDEPENDENT_SOURCE_RANGE = False` can have a source
axis dragged onto the widest range. The U2722A stopped being so on
2026-08-25, and the miniSMU never was: its current range is a
**measurement** range, established from the commands the vendor library
sends. A source current is never judged against it.

The 2026-08-21 note said the same reconciliation was harmless here
"because the autorange is real". The conclusion was right and the reason
was wrong, and the wrong reason had been carried into four places. All
four now say what was measured.

`_apply_source_current_range()` passes `disable_autorange` explicitly,
because none of the three ranging methods this driver uses appears in
the vendor's published API reference, so the default is not ours to
inherit.

Still open and narrowed: the sub-count floor on the Keithleys, the
B2901A and the GSM-20H10.

## Wave 8b

**What a run does about a lost link.** A run that loses its link
de-energises, fails, keeps nothing, and blocks the instrument until it
is reconnected. Runs already in the table survive untouched, with their
unsaved data still unsaved.

That behaviour already worked as a consequence of three separate
mechanisms lining up, and nothing pinned the combination.
`tests/test_link_lost_during_a_run.py` now pins it end to end through a
real experiment, and its mutation round is what establishes it can fail.

`ShutdownReport.link_lost` distinguishes a link that stopped answering
from an instrument that reported a fault. Both block the instrument;
only the first needs a reconnect, and the operator message says so.

The harness mistake found while writing that test is
[fault 26](docs/faults/26-a-fault-injected-below-the-layer.md).

## Wave 8a

**A link that stops answering stops the work.** A query whose reply
never arrives latches the transport into a refusing state, and every
later query raises `TransportDesynchronised` until it is reconnected.
There is no recovery in place: no later reply can be matched to the
question that asked for it, and the reading that was expected did not
happen.

`write()` stays permitted — a write never reads, so it cannot be one
behind, and every driver's `output_off()` is a write, which is what lets
a poisoned session de-energise its sample.

**`confirm_output_off()` no longer reports CONFIRMED on a link that has
stopped answering.** The checkup stops at the break instead of warning
and continuing. `clear()` is demoted to teardown housekeeping: its
return value says a device-clear call did not raise, which is a
different question from whether the stream is back in step.

Every broad `except` around a query names the exception and re-raises.
A driver whose instrument stops answering during `reset()` now ends the
session rather than continuing with a note.

## The fleet, commissioned

Every registered driver carries a `bench_code` matching the code that is
running, from the 2026-08-25 round.

The U2722A carries one failure, and it is the driver correctly refusing
a configuration the instrument cannot perform. `Checkup.setup()` now
grades each step and records an explicit skip for checks that depended
on a failed one, instead of crashing when a driver declines a
configuration.

## Below a count, the sign is not yours

**Deviation 54.** The U2722A refuses a source level below ten counts of
the active range, before the output is energised, naming the range that
would carry it. Below one count there is no signal, only offset residue,
and its polarity is not commanded.

Ten counts is a decision: one count is where a request first means
anything and the error there is 100%; ten caps it at 10%.

**It costs something real.** Nothing below 1.22 mV can be sourced on any
range. The probes behind it, the output capacitance, the asymmetric
clamp on R1uA and the charge that survives `*RST` are in
[Keysight U2722A](docs/instruments/keysight-u2722a.md).

## The GSM-20H10 was never broken

The 2026-08-24 checkup read as a regression. It was a USB-TMC read
timeout leaving the reply stream one behind, so every query returned the
previous command's answer. Re-run 2026-08-25 at `d332432`: 64 pass,
0 fail, with an identical driver fingerprint across the red and green
runs.

`SOUR:FUNC?` is verified against hardware, which is what the trip-axis
rule needs. Detection and latency evidence are in
[GW Instek GSM-20H10](docs/instruments/gwinstek-gsm20h10.md); the fix is
Wave 8a.

## The compliance chooses the range

**Deviations 52 and 53.** On the U2722A a compliance is settable only
between a tenth of the active range's full scale and full scale, which
makes the limit very nearly determine the range. The driver stops
treating them as two knobs: the range is chosen from the limit, a range
change that would strand a limit is declined, a compliance no range can
express is refused before the output goes on, and every limit written is
read back — the bench watched a 100 µA compliance silently become 12 mA
on a range move.

Two bands this instrument cannot express — below 100 nA, and between
10 mA and 12 mA — are in `bench/choosing-an-smu.md`, where somebody
picking an instrument finds them before the bench does. The per-range
windows are in
[Keysight U2722A](docs/instruments/keysight-u2722a.md).

**Unverified against hardware** at the time of writing.

## Reports that say what happened

Three gaps the 2026-08-21 round found in the reports rather than in a
driver.

**An error names the commands it could have come from.** The queue is
drained once per group of writes, so a `-222` could not be attributed.
The commands written since the last drain are now listed — a list rather
than a guess, because SCPI does not require the error queue to be
ordered against writes.

**The miniSMU is traceable.** A recording proxy sits in front of the
vendor client, so calls appear as `client.set_current_limit(...)` rather
than as an invented SCPI string.

**The dirty flag says what was dirty.** A flag that is sometimes
alarming and sometimes not, with no way to tell which, gets ignored —
and the time it is ignored is the time it was real.

## One trip-axis rule for the SCPI drivers

The compliance trip is always on the quantity you are *not* sourcing, so
the axis to query depends on the source function. The GSM-20H10 was
OR-ing both trips, which adds a failure rather than removing one: a
stale value on the unused axis reads as a clamp that is not happening.

The driver now reads `SOUR:FUNC?` and asks the complementary axis. The
B2901A's equivalent stays a separate implementation, because that one is
confirmed against hardware and this one is not. The general shape is
[fault 21](docs/faults/21-wrong-quantity.md).

## Time per reading now means the steady-state cost

Every instrument pays a large one-off on the first reading after
`output_on()` — between 1.3x and 14x the steady figure across this
bench — and the checkup was averaging it into the number it reports.

A warm-up reading is taken and discarded before timing, at both ends of
the aperture fit, and the first read is reported on its own line as the
cost it is: paid once per run, not predictable from the steady figure.
The sweep deadline adds it once rather than per point.

Not cosmetic: the figure is published as the **Per reading** column in
`bench/choosing-an-smu.md`, it sets the sweep deadline, and it is one of
two points `_aperture_cost()` fits a slope through. The published
figures were re-derived from the round's traces rather than left until
the next bench session.

## The compliance probe tells the truth about both edges

The checkup's compliance probe could not distinguish a working
compliance from an absent one. Two faults, opposite directions, one
cause — a threshold checked on one side. Recorded as
[fault 25](docs/faults/25-a-bound-checked-on-one-side.md).

- **It judged an output that was still ramping.** The settle loop now
  polls until two readings agree, and "above the limit and still
  climbing" is expressible, which it was not before.
- **It passed an output beyond its limit**, because a large negative
  reading cleared a floor. An output past its own compliance is now a
  failure, checked before the ramping branch.

`COMPLIANCE_FLOOR` and `COMPLIANCE_CEILING` are named and both edges
come from measured hardware. Three fakes never clamped, so the file
written to stop this probe being non-discriminating was itself
non-discriminating; all three hold their limit now.

Tier 2's `compliance_tripped()` no longer goes through `attempt()`,
where a driver returning `None` passed indistinguishably from one
returning an answer.

## The 2026-08-21 commissioning round, and a staleness rule that survives a merge

Every physical instrument re-checked at `7dc6264`, the first reports to
stamp the commit and firmware they describe. `NOT_SOURCED` is confirmed
against hardware from both directions. The round found no new driver
fault and several in the checkup tool.

- **`bench_code` replaces the commit-date comparison.** A commit date is
  rewritten by `git am`, by a rebase and by a squash-merge, so the same
  bytes answered differently depending on when they were merged.
  Staleness now compares a digest of the driver's contents plus its
  shared dependencies, and consults no git at all. Recorded as
  [fault 24](docs/faults/24-derived-from-a-rewritable-date.md).
- **`bench_result` replaces the inference that a date means a pass.**
  Stale means nobody has checked recently; failing means somebody has
  and it did not pass.

## Direct GPIB-HS: address picker candidates

Selecting **NI GPIB-HS** left the address combobox empty while a typed
`GPIB0::9::INSTR` connected and ran. The panel now offers
`GPIB0::1::INSTR` through `GPIB0::30::INSTR` with no implicit selection,
and discovery still never claims an instrument occupies a GPIB address.
Recorded as
[fault 22](docs/faults/22-direct-gpib-hs-empty-address-picker.md).

## Direct GPIB-HS: Windows/B2901A commissioned

On 2026-08-18 a genuine NI GPIB-USB-HS (`3923:709b`, revision `0x0101`)
bound to WinUSB drove a Keysight B2901A at GPIB address 9 through
`tools/smu_checkup.py --transport gpib-hs`. Tiers 1, 2 and 3 passed,
without NI-VISA or NI-488.2 installed.

Scope stays narrow: VISA remains the default, direct GPIB-HS is explicit
and optional, and no driver or experiment changed. It claims nothing
about SRQ, serial poll, secondary addressing or multi-controller
operation.

## Direct GPIB-HS: Windows needed an IFC pulse

A genuine adapter opened over WinUSB but returned `NO_BUS` for every
command, including a bare UNL. Sending NI USB `IBSIC` to pulse GPIB IFC
fixed it — a bench result, not an inferred workaround.

`NIUSBGPIBTransport` pulses IFC after every controller construction,
including a timeout-recovery reopen. A failed IFC closes the fresh
controller and fails the connection. Recorded as
[fault 27](docs/faults/27-direct-gpib-hs-missing-ifc.md).

## Optional direct NI GPIB-USB-HS transport

A non-default path for the occasional Windows bench that needs a genuine
NI GPIB-USB-HS without NI-VISA or NI-488.2.

`NIUSBGPIBTransport` wraps `ni-gpib-usb-hs==0.1.0` behind the existing
transport contract, as an optional `direct-gpib` extra imported only at
connect time. VISA stays the default and this must be selected
explicitly; there is no silent fallback. Discovery probes only the USB
adapter and never invents occupied GPIB addresses, and both paths
normalise a GPIB resource to one ownership key so two windows cannot
drive it through different stacks.

**Not commissioned on Windows** at the time of writing.
[Direct NI GPIB-USB-HS transport](docs/architecture/direct-gpib-usb-hs.md)
records the WinUSB prerequisite, the upstream scope limits, the
GPL-2.0-only dependency note and the bench questions owed.

## Documentation: the commissioning round as a procedure

No behaviour change. The round produced a way of working that was not
written down, and most of what it cost was learning it.
[A commissioning round](docs/workflow/commissioning-round.md) records
why every instrument is checked in one pass rather than repaired one at
a time, and the probe habits that ended a week of wrong mechanisms.

## The compliance readback, and the check that would have saved a week

D5 and D6. Nothing in this suite ever read a compliance back, which is
why the GSM-20H10's silent collapse from 105 µA to 1 nA on a single
ranging command took a week to find.

- **`read_current_limit()` / `read_voltage_limit()` on `BaseSMU`**,
  returning `None` where a driver cannot ask. Implemented for the
  GSM-20H10 and the U2722A.
- **`COMPLIANCE_READBACK_TRUSTED` is three-valued.** `None` means the
  driver answers and nobody has checked whether it tells the truth. A
  readback an instrument answers dishonestly is worse than none.
- **The checkup gains "compliance survives ranging"**, and deliberately
  sends the limit before the ranges — the order fault 15 exists to
  prevent. That is the point: asking it the safe way round lets the
  experiment's own limit paper over the damage. The correct order is
  restored immediately after, and the output is off throughout tier 2.
- **`compliance_readback` in the contract ledger**, so a driver gaining
  it fails the ledger for every other driver until each records where it
  stands.

## Commissioning tools: say which code and which firmware

Three gaps of the same shape, all found by the tools being wrong about
the GSM-20H10 in ways nobody could see.

- **`core/provenance.py`** — reports carry the commit they ran at,
  whether the tree was dirty, and the instrument's firmware from
  `*IDN?`, in both the JSON and the Markdown header from one call so the
  two cannot drift. Written from the real `*IDN?` replies rather than
  from the SCPI standard, because two of them do not follow it.
- **`tools/timing_scan.py` checks that its readings are readings.** It
  timed `measure()` without looking at the result, so a `(None, None)`
  was timed exactly like a measurement. It now counts blanks and refuses
  to fit when any turn up.
- **It reports noise, not just time.** A longer integration that is not
  quieter is reported plainly: the NPLC setting on that instrument is
  decorative.

## RangePlan: an axis that is not being sourced is not the same as AUTO

`RangePlan.for_sourcing()` put `AUTO` on the source axis of the quantity
a run is *not* sourcing. `AUTO` asks the instrument to choose a range;
the intent was "nothing is coming out of this axis". Drivers could not
tell the two apart — harmless on most of the bench and damaging on two,
in opposite directions.

- **`NOT_SOURCED`**, a sentinel distinct from `AUTO`.
  `BaseSMU._render_not_sourced` turns it back into `AUTO` by default, so
  instruments already commissioned keep their behaviour and only a
  driver checked at the bench overrides it. `renders_not_sourced` in the
  contract ledger records which — `False` means the default was verified
  harmless on that model, not that nobody looked.
- **`RangePlan.widest()`**: an axis carrying nothing no longer wins a
  shared knob.
- **GSM-20H10** sends nothing at all on that axis.

A U2722A driver override was written, passed its tests, and was then
found unreachable by mutation. Removed, with the reason left in its
place: a hook that looks load-bearing and never runs is worse than no
hook.

## GSM-20H10 commissioning: what the 2026-08-20 bench session found

- **`tools/smu_checkup.py` applied limits before ranges** — the order
  fault 15 exists to prevent — costing three failures and taking tier 3
  with them. No measurement was ever at risk: every experiment already
  ordered it correctly.
- **A source-autorange command silently resets the compliance.** One
  command, no error, from 105 µA to 1 nA. Written up as
  [fault 23](docs/faults/23-autorange-resets-compliance.md). Runs
  survive it only because fault 15's ordering puts the experiment's own
  compliance after the ranging block — accidental, not designed.
- **Three other things the instrument does**, all in its note: a
  measurement range can be refused and silently narrowed; `OUTP?`
  returns 0 with the output physically on; and setting the measurement
  range of the sourced quantity is refused by name.
- **First manual extracts in the repository.**
  `docs/reference/manuals/` now holds the GSM-20H10 factory-defaults
  table and four command entries.

## Fixed sourcing vs time: the last sample, and the clock ceiling

Windows CI found an eleven-sample run returning ten; Linux could not
reproduce it. The clock ceiling was pre-empting the sample due at
exactly the duration, because Windows' ~15.6 ms timer granularity puts a
10 ms final wait past the ceiling before that sample is taken.

**The ceiling now has a grace of one interval**, which is the stated
cost of not dropping the final sample. A run a whole interval behind the
agreed window is still stopped.

Two regression tests, deliberately not timing-dependent: one reproduces
the Windows shape on any platform by making a single reading slow; its
pair asserts the grace did not become an amnesty for a runaway run — and
that pair was later rewritten to bound instrument-side work rather than
wall clock, which is
[fault 37](docs/faults/37-a-test-that-measured-the-machine.md).

## Fixed sourcing vs time

The first experiment in this suite that is not a port. It holds one
source level and samples the other quantity against the clock —
leakage, bias stress, relaxation, self-heating — and it is the first
whose independent variable is time.

- **No driver changed.** Everything it needs was already on `BaseSMU`,
  checked before the design was agreed rather than discovered after.
- **Duration is authoritative and the loop is bounded by the clock**,
  not by its position on the nominal grid. The timer exists so nobody
  walks away from a live fixture, so a slow instrument delivers fewer
  samples in the same window rather than the same samples over a longer
  one.
- **`RunContext.expect()` cannot be used here**; an exact expected count
  would fail every honest run on a slow instrument. A conditional floor
  replaces it.
- **Two stop controls, because they are two operations.** "Finish and
  save" commits what was collected; "Stop and discard" is the house
  Stop, unchanged. Neither button talks to the instrument.
- **The time column is measured and the schedule aims at absolute
  deadlines**, avoiding
  [fault 9](docs/faults/09-reconstructed-x-axes.md) and
  [fault 5](docs/faults/05-slept-not-polled.md) in a new place.

26 new tests. 22 deliberate mutations; the first round left four
survivors — two real holes in the tests, and two mutations shaped so
they could not fail.

**Not commissioned** at the time of writing.

## Wave 7g

`uv.lock` regenerated. Wave 7e's `[build-system]` changed how uv
classifies the project itself and the lockfile was never rebuilt, so CI
failed at `uv sync --locked` with an error naming neither what had
changed nor why.

`tests/test_lockfile.py` holds `uv.lock` to `pyproject.toml` — project
name and version, dependency list, Python floor, and whether the project
is a buildable package. Deliberately offline: `uv lock --check` would be
complete but needs an index, and a suite that cannot pass without the
network fails on a bench machine for reasons unrelated to the code. It
cannot catch an upstream package changing its own requirements;
`--locked` in CI still covers that.

## Wave 7f

`lock_directory()` created what it returned — a function named for a
question with a side effect, so *asking* where the lock lives made
directories, including for anything that merely constructed an
`EventLog`. It is now a pure query; the writers create what they need.

Invisible on Linux, where the directories were real and writable. It
took a Windows path whose ACL refuses `mkdir` to turn a silent side
effect into a `PermissionError`.

`lock_directory()` now takes `platform`, `environ` and `home` so both
branches run on either operating system. **This is the more important
half.** The fault reached CI because the only test of the Windows branch
opened with `if sys.platform != "win32": skip`, so on the machine where
the code was written it never ran. A branch that can only be tested on
the platform you cannot run is a branch nobody tests.

Mutation testing then found a second hole in both writers: every test
handed them a `tmp_path` that already existed, so deleting the `mkdir`
broke nothing. That is the first-run path on every bench machine, and
for the event log it would have been silent.

## Wave 7e

Packaging.

- **`[build-system]` added**: the project can be built and installed.
  Before this, `import core` worked only when the working directory
  happened to be the checkout. Verified end to end into a clean 3.14
  environment.
- **Layout stays flat.** A `src/` layout stops source shadowing the
  installed copy, which matters for a library and much less for an
  application with one entry point — and an editable `src/` install
  would not have caught a missing data file anyway. Checking the built
  artifact does, and `tests/test_build_artifact.py` does that.
- **`tests/test_build_artifact.py`** enumerates non-Python files from
  the tree and requires each in a genuinely built wheel, so a new image
  is covered when it is added rather than when somebody remembers a
  rule.
- **The launcher body moved to `core/launcher.py`** and `pyproject.toml`
  declares a `smu-lab-suite` console script, so the application opens
  from any directory. The entry point names `core.launcher`, never
  `main`: a top-level `main` in site-packages collides with every other
  package's idea of that name.

The first build configuration carried `artifacts = ["**/assets/**"]`
with a comment asserting it was essential. It did nothing. Mutation
testing found it; the reasoning is in `docs/workflow/packaging.md`.

## Wave 7d

Operational event log.

Every run leaves a record of how it ended — completed, cancelled or
failed — as JSON Lines in per-machine state. Previously a cancelled
run's only trace was a console line that vanished with the window, so
"nothing was saved" and "somebody stopped it because the probe slipped"
were indistinguishable afterwards.

- **It records that a run happened, never what it measured.** Guarded by
  a test that puts a distinctive value in a run's readings and asserts
  it appears nowhere in the log, so a leak through a field added later
  goes red.
- One line per run, not per state transition: a run is the unit of
  investigation.
- JSON Lines rather than CSV, because the field list will grow. A new
  key is invisible to an old reader; a new CSV column shifts everything
  after it, which is the shape of the Wave 4 sentinel fault.
- Wired at `RunController._record`, the single choke point every
  terminal status passes through, so a future terminal path cannot skip
  logging. The controller takes a callable, not a path, so run control
  keeps no dependency on the filesystem.
- A log that cannot be written never fails a run.
- Stored beside the single-instance lock rather than beside the
  application: a frozen `.exe` under `Program Files` sits where ordinary
  users cannot write, and one on a shared drive would pool every bench's
  runs into one file.

Two silent defects found by the new tests: the parameter fingerprint
used `repr()`, so two identically configured runs produced different
digests from an object's memory address; and a line torn by a power cut
would have had the next run's event glued onto it, losing both.

## Wave 7c-ii

Only one copy of the application may run per machine. Two copies would
each open the same instruments and each believe it controlled the output
state.

The lock is held by the **operating system** — `msvcrt.locking` on
Windows, `fcntl.flock` elsewhere — rather than being a file whose
existence means "running". The OS releases it however the process ends,
so a crash cannot leave the bench locked out of its own software;
`tests/test_single_instance.py` proves that by killing a holder
outright.

The lock file lives in per-machine state, never beside the application:
advisory locks over SMB and NFS are unreliable, and a lock on a shared
drive would be shared between benches.

**Worth knowing at the bench:** a second copy is refused even when it
would have driven a different SMU.

## Wave 7c-i

`run_tests.py` passes `PYTHONDONTWRITEBYTECODE=1` to every pytest
subprocess. CPython validates a cached `.pyc` on the source's mtime and
size, so a same-length edit inside one mtime tick leaves stale bytecode
running — which silently invalidates mutation testing, the technique
most of this project's real defects were found by. Cost three mutation
rounds in Wave 7b before it was spotted.

`tests/test_bytecode_staleness.py` demonstrates the mechanism rather
than trusting it, pinning both mtimes with `os.utime`.

## Wave 7b-ii

Save semantics: immutable snapshot, made legible on disk.

- Every stored file declares `schema` and `app_version`, plus
  `save_kind: snapshot` and a `save_id` shared by every file one press
  of Save writes. Combining two snapshots is
  `drop_duplicates(subset="record_id")`.
- `core/version.py` is the single source of truth for the application
  version; `pyproject.toml` mirrors it and `tests/test_version.py` fails
  if they drift. Not read from packaging metadata, because
  `importlib.metadata` needs an installed distribution and neither a
  checkout nor the intended frozen `.exe` is one.
- The Save button reads **Save snapshot → CSV**, and the confirmation
  says the runs stay in the table.

Exporting only new runs was rejected, and the reasoning is in house
rule 3: the `#` header carries results derived from every run in the
store, so a new-runs-only file would state a sheet resistance computed
from readings it does not contain.

`tests/test_shared_controls.py` found the header row by position; it now
finds it by content, since four new header lines would have aimed it at
a `#` comment where each `in` check is trivially false.

## Wave 7b-i

Run identity, ahead of the save-semantics change that needs it.

The IV sweep bound each stored run to whatever the sample-name box said
when the *sweep finished*, read from the worker thread. Retyping the box
mid-run re-filed the remaining sweeps, and a periodic run could split
its cycles across two samples with nothing logged. It now captures a
frozen `SampleRef` at the Run press, as the other experiments
already did.

`Run` mints its own `record_id`, written as the first CSV column.
`run_id` identifies a lifecycle run and `record_id` a stored row — not
the same thing, because one periodic IV run commits several records
sharing a `run_id`, and de-duplicating on `run_id` would delete real
cycles.

## Wave 7a

Tooling guards, ahead of the persistence work. No production code.

- Every Markdown table must have a header, a separator and at least one
  body row, with square columns. `plan.md`'s status table had been a
  header and a bare `|` since the documentation rebuild, rendering as an
  empty grid rather than as damage.
- `plan.md`'s wave status is checked against `CHANGELOG.md`'s headings,
  so it cannot fall behind the work by omission.
- A GUI test whose dialog recorder has been stolen by another test file
  in the same process now fails, instead of passing its
  absence-of-dialog assertions against a recorder nothing writes to.

## Documentation rebuild

Five patches replacing four root documents that had grown to carry a
plan, a changelog and a reference manual at once — and had begun
disagreeing with the code and with themselves.

- `docs-skeleton-v1` — vault tree, frontmatter schema, generators, guards
- `docs-instruments-v1` — one note per driver, deviations rehomed
- `docs-experiments-v1` — one note per measurement, script archaeology
- `docs-architecture-v1` — house rules, faults, the `core/` map
- `docs-retire-v1` — bench pages, the review index, the old files deleted

What it corrected on the way through is listed in
`docs/reference/migration-status.md`. The mechanism that stops it
recurring: **a documentation claim a machine can check is not written by
a human.** Driver envelopes, commissioning status, deviation numbers and
the review index are all generated, and `tests/test_docs.py` fails if a
committed copy disagrees with a fresh build.

## Wave 6d-ii

Adopt `apply_ranges()` in the experiments and the checkup; delete `set_current_range` / `set_voltage_range`.

Review issues: fault 16.

## Wave 6d-i

Ranging contract: `RangePlan`, `apply_ranges()`, per-axis hooks on every driver. Capability only - nothing adopts it.

Review issues: fault 16.

## Wave 6e

Reconnect after transport failure — delivered with 6c.

Review issues: §33.

## Wave 6c

Sweep traces: hardware sweep setup and completion, arming vs stepping, error-queue drain, abort spelling.

Review issues: §33.

## Wave 6b

Per-driver command traces; dialect hygiene; cross-experiment enforcement of house rule 12.

Review issues: §33, C4.

## Wave 6a

IV run lifecycle + standby/sweep contract + sweep ownership.

Review issues: A7, A8, §19, §20.

## Wave 5c-ii

Per-sample summary file + the save-collision pre-flight.

Review issues: §16, §17.

## Wave 5c-i

In-memory Rs handoff: `UpstreamResult`, the provider seam, the CSV load path deleted.

Review issues: §16, §17.

## Wave 5b

Combined VdP + Hall window, tabbed shell.

Review issues: operator feedback.

## Wave 5a-ii

Rollout: Hall, same pattern.

Review issues: Milestone 3.

## Wave 5a-i

Rollout: Van der Pauw onto the run lifecycle + calculation layer.

Review issues: Milestone 3.

## Wave 4

Calculation integrity: `core/calculation.py`, provenance, method versions, golden files; 4PP pilot.

Review issues: B5–B8, §16–18, §27–28.

## Wave 3

Pilot integration: 4PP only.

Review issues: A4, A6, A8 in situ.

## Wave 2

Typed inputs & identity.

Review issues: B1, B3, B4, §14, §15, §24, §54.

## Wave 1

Run-control core + instrument ownership + connection health; `LabApp` constructor injection.

Review issues: A1, A2, A3, A5, A9, A10, C3.

## Wave 0b

miniSMU dependency, `driver_registry` → `drivers/registry.py`, orphaned VdP `temp_panel.py` deleted, MIT licence, rename, GitHub Actions.

Review issues: C1, D1, D3, D5, D7.

## Wave 0a

pytest conversion: 25 scripts → 166 tests, `check()` as a soft-assert fixture, `run_tests.py` process isolation.

Review issues: C6.
