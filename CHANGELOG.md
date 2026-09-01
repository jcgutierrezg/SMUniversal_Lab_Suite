# Changelog

Newest first. **Append-only**: a new entry goes on top and existing
entries are not edited.

**What an entry says is what changed and why it matters** — the
conclusion, and what was added or removed. Not how the conclusion was
reached.

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

> **One exception was made, on 2026-08-27.** Every entry above Wave 6e
> was condensed under the rules above, and the file went from roughly
> 1,280 lines to under 900. Nothing was deleted without first checking
> that it lived in the file that owns it, or moving it there. That was a
> deliberate, single break of the append-only rule; the rule holds
> either side of it.

The work up to Wave 7 was organised as numbered waves adopting one code
review. That adoption ended with Wave 7; the numbering continues from
Wave 8 as a plain sequence number for a unit of work.

## The dialog that hung the suite, and the guard for the next one

`test_link_lost_during_a_run.py` reached `messagebox.showwarning`
without having stubbed it. The call is queued by `LabApp.ui()` and
drained from a 10 ms timer, so the outcome depended on the machine:
where the test's event-loop pumping spanned that period the dialog
opened and blocked forever, and where it did not the warning was
discarded and the test passed. The discarded message was the one
telling an operator that a sample may still be energised.

The file now stubs the dialog seam for every test in it, waits on facts
instead of on a fixed number of `root.update()` calls, drains the UI
queue explicitly through `drain_ui_now()`, and asserts that the warning
was raised rather than only that the instrument was blocked.

`_a_gui_test_never_reaches_a_real_dialog` in `tests/conftest.py` fails
any `gui`-marked test that raises a dialog on a seam nobody stubbed,
whether it was shown or left queued. It is the counterpart of the
existing ownership guard, which cannot see this case because an
unclaimed seam has no owner to disagree with. Recorded as
[fault 28](docs/faults/28-a-dialog-nobody-stubbed.md).

Removing the stub now fails the file in about a second, naming the
dialog. Before this it ran to the CI job's limit with an empty log.

## A hung test run can now say what hung

`run_tests.py` announced a group only once it had finished, and
`print()` to a pipe is block-buffered, so under CI nothing reached the
log until the process exited. Nothing bounded a group either. A run that
never finished therefore produced an empty log and ran toward the
platform's six-hour default — a failure that could not be localised even
in principle, in a suite built on the premise that a fault says so.

Each group is now announced before it starts, killed if it exceeds a
budget (`SMU_GROUP_TIMEOUT_S`, default 600 s), and reported as `TIMEOUT`
with whatever output it had produced. A timed-out group does not stop
the ones after it, so one run names all of them. The CI job carries
`timeout-minutes`, and a test refuses a workflow without one.

The pytest subprocess is now started unbuffered, so a group killed for
hanging still hands back how far it got.

No test or driver behaviour changes; this is the harness reporting on
itself.

## The bench pass, run across the fleet

Every instrument now carries a noise/rate envelope and a sub-count floor
in its note, measured 2026-09-01 at 100 uA into 9958 ohm.

The floors divide into two shapes, and the difference decides how far
each instrument can be trusted. The B2901A, GSM-20H10 and 2401 run out
of **resolution**: readings step to zero and stop. The 2611A and 2635B
**drift** - a negative offset grows as the level falls, so the 2611A at
12 nA commanded reads -42 nA on its negative leg, more than three times
the request with the sign still correct. A number that quantises to zero
is obviously unusable; one that is wrong by a factor and still points
the right way is not.

The U2722A is the only instrument whose floor is declared rather than
inferred: deviation 54 refuses the level before energising anything and
names the range that would carry it. The tool used to crash on that
refusal, so it fell over on the one driver that gets this right. A
refusal is now recorded as the floor.

Two things the envelope settles. The 2635B is the fastest instrument
here - 287 Hz at 0.001% RSD. The U2722A's 1 PLC minimum caps it at
14 Hz whatever noise you will accept, and at NPLC 255 a single reading
takes ten and a half seconds; every rung of its envelope is quantised at
a 2 V compliance, so those figures describe its resolution rather than
its noise.

No floor was found for the miniSMU. It still followed the sign at 95 pA,
where the probe stops after descending a millionfold from the bias - the
tool running out of ladder, not the instrument running out of
resolution.

## The bench pass, corrected against its first run

Four faults, all in the tool, found by running it across the bench on
2026-08-28. <!-- lint-ok --> One usable sub-count result came back; the
rest were meaningless and reported confidently.

**The control leg was impossible.** It pinned the widest range and then
ran the control at 100 uA, which on a 1 A range is itself sub-count -
the condition the control exists to rule out. It failed on four
instruments. It now pins the range that suits the bias, which the
compliance requires anyway: 2 V into 10 k caps the current at 200 uA.

**A 1 A range request crashed the miniSMU**, whose ladder stops at
180 mA.

**The verdict had no upper bound.** Requiring only that the readings
separate by more than the commanded level makes the threshold shrink
with the request, so a fixed offset clears it more easily the smaller
the level gets. The GSM reported twenty-one consecutive "sign follows"
rows down to 95 pA on readings pinned at +144 uA and +20 uA, both
positive. The separation must now be about twice the level, bounded
both ways.

**`RSD 0.000%` was quantisation, not quiet.** Every instrument reported
it at its upper rungs, flattening the curve into something that reads
as a perfect result. Rungs where every reading lands on one converter
code are named as such, and a rung whose mean has walked away from the
commanded bias is flagged as possibly clamped - which matters most on
the drivers that cannot report compliance, where nothing else would say
so.

A second run found two more, both also in the tool.

**Both legs must land on opposite sides of zero.** The GSM tracked its
command accurately down to about 1.5 nA and then froze at +1.28 nA and
+0.40 nA, both positive, with four further rows still reported as
following - a fixed offset sitting inside a window that shrinks with the
level. Commanding negative and reading positive is not a commanded sign,
whatever the separation.

**The envelope pins the same range as the sub-count phase.** It had been
putting the level onto whatever range `reset()` left active; the B2901A
then read a mean of 4.3e-7 A against a commanded 1e-4 at every rung. The
run before reported `RSD 0.000%` for that instrument and it looked like
the best on the bench, because there was no mean column to contradict
it.

The tests are built from the readings the bench actually produced, so
the GSM's frozen rows and the B2901A's real result both have to keep
coming out the way they did.

## What the 2026-08-27 bench round found

Every instrument on the bench re-checked. <!-- lint-ok --> The B2901A,
2635B, 2611A, 2401 and miniSMU pass; the U2722A carries its one honest
refusal.

**`D7` is not closed, and the entry saying it was is wrong.** The
U2722A's trace shows `apply_ranges()` putting the shared knob on
`R120mA` and deviation 52 then dragging the compliance from 10 uA up to
12 mA to suit it. The range is not overwritten by the limit; the limit
is overwritten by the range. Deviation 54 turns the consequence into a
named refusal instead of a wrong number, which is why the failure reads
as benign, but the mechanism is untouched.

It is also narrower than originally filed. D7 said the reconciliation
could strand a small request on any instrument. It cannot: the
reconciliation only runs where source and measure share one knob, and
every other driver in the fleet sends two independent range commands.
Confirmed from traces on all of them, not from the flag.

**`:TRACe:FEED` on V1.16 rejects the token the manual gives as its own
example and the token the instrument itself reports.** `SENS` is
accepted; `SENSe1`, `SENS1`, `SENSE1` and `RAW` are refused; `CALCulate1`
is accepted in full long form. The driver's existing probe already
lands on `SENS`, so the `-140`s in every GSM trace are that probe
working. Both manual pages are transcribed with the measured grammar
beside them.

**Console scripts move to `probes/`**, gitignored. Written into the
repository root they made every checkup on that machine report
`dirty: True`, and a provenance flag that is always set is one nobody
reads.

The GSM is re-stamped from a clean 2026-08-28 run: 68 pass, no
timeouts, clean tree.

Its intermittent read timeout is recorded as open, with the two changes
that would make the next occurrence informative. So is a latent defect
in `code_fingerprint()`, which hashes the path string without
normalising it - an absolute path or a Windows separator produces a
digest another machine cannot reproduce.

## One bench pass per instrument

`tools/bench_envelope.py`, to be run after `smu_checkup.py` on the same
connection and the same load. Two phases the fleet owes, on one fixture,
so the answers are comparable.

**The envelope**: at each rung of the NPLC ladder, the achieved sample
rate and the relative standard deviation of a burst. It answers what a
per-reading figure cannot — after the first read, how fast can this
instrument be polled while keeping the noise you can live with. The
first reading of each burst is discarded, since every instrument here
pays a large one-off after `output_on()`.

Relative standard deviation, not the peak-to-peak `timing_scan.py`
reports. Peak-to-peak is right for its own question, where a thirtyfold
change is unmissable; it is set by the single worst sample and grows
with the burst length, so it cannot compare instruments.

**The sub-count floor**: halve the commanded level down from the bias
and ask at each step whether `+X` and `-X` still read differently. Where
they stop differing is the floor on that range. Measured rather than
predicted, because no driver here declares its converter bits — which is
exactly what is unknown.

The verdict requires the two groups to be separated by more than their
own scatter *and* by more than the level asked for. The second is the
load-bearing condition: with a quiet instrument the scatter approaches
zero and any difference clears the first. An offline fake proved that by
manufacturing the signal the check was looking for, because its dither
alternated on the same period as the `+`/`-` loop.

Nothing is predicted from the load resistance. It was measured with one
of these instruments, so using it to judge them is circular; the sign
flip needs no calibration.

**The reading noise is the detection limit and is not the source
floor.** A crossing found below the noise says something about the
measurement, not the converter, and the procedure says to check the two
against each other.

Not run against any instrument yet.

## A desynchronised link could be un-latched by a device clear

**A hole opened by Wave 8a's own mechanism.**

8a made `connected` a property whose setter cleared the desynchronised
latch whenever it became True, so that clearing could not be forgotten.
`NIUSBGPIBTransport.clear()` reopens the adapter and sets that flag on
its way out — so a device clear silently un-desynchronised a poisoned
session, through exactly the kind of unverified recovery the latch
exists to refuse. Whether that reopen realigns a stream has never been
put to hardware.

Clearing is now an explicit `_begin_session()`, called from `connect()`
and nowhere else. `tests/test_transport_desync.py` checks over every
`Transport` subclass that each `connect()` calls it and that `clear()`
does not. A missed call fails in CI; the clever setter failed on a
bench.

**`docs/open/` now holds only what is open.** `direct-gpib-usb-hs.md`
was about four-fifths description of a commissioned transport, so that
part became
[Direct NI GPIB-USB-HS transport](docs/architecture/direct-gpib-usb-hs.md)
and the four questions hardware has not answered became ordinary
technical-debt entries.

`technical-debt.md` loses an item resolved in Wave 7c-i and an account
of a guard that was proposed and rejected. Both left something live
behind, and both went to `tests/README.md`: clear `__pycache__` when
mutating outside the runner, and `pytest -m "not gui"` imports every
module it collects before deselecting any, so a guard that counts
imported GUI modules fails the runner's own pass.

## A documentation accuracy pass

Statements that later work made false, found by reading every page
against the code rather than by tripping over one of them.

Wave 8a left six pages describing a device clear as the recovery for a
timed-out query. There is no recovery; the transport latches and only a
reconnect clears it. Corrected in the architecture page, the 2401 note,
the GSM-20H10's open question - which Wave 8a answered - the
fixed-source experiment page, and `confirm_output_off()`'s own
docstring, which contradicted the code directly beneath it.

`HANDOFF.md` was routing every new session to `driver_checkups`, merged
two waves ago, and naming a bench session that had already happened. It
now names the branch in flight and says the whole fleet is owed a
checkup.

`docs/workflow/delivering-work.md` said patches are applied with
`git apply`. They are applied with `git am`, and the difference is
load-bearing: `git apply` leaves the tree uncommitted, so anything
derived from `git log` still reports pre-patch values and a verification
run that way cannot fail. Its start-of-conversation template also
pointed at `WAVE_PLAN.md`, deleted, and told the reader to download a
tarball, which loses the history that confirming a base commit needs.

Two fault pages both claimed number 21. Code and tests cite 21 for
[Asking about the wrong quantity](docs/faults/21-wrong-quantity.md), so
the GPIB-HS page became 27.

The review document's editorial preface pointed at `WAVE_PLAN.md` and
`PORTING_NOTES.md`, both gone. The review text itself is untouched, as
it says it should be.

`docs/open/technical-debt.md` now deletes a resolved item instead of
marking it closed and leaving it. Closed entries had grown to about half
the page, which is how a file meant to be read before starting work
becomes one nobody reads. The convention is written at the top of the
file it governs. One entry that reads "closed as a crash, open as a
result" stays, because it is still open.

## D7 closed: the miniSMU's current range is a measurement range

`D7` said `RangePlan`'s shared-knob reconciliation could drag a source
axis onto the widest range on any instrument where source and measure
share one. It is closed. No driver setting
`INDEPENDENT_SOURCE_RANGE = False` is in that position: the U2722A stopped
being so on 2026-08-25, when deviation 52 began taking the range from the
compliance limit and forcing it, and the miniSMU never was.

The miniSMU's current range is a **measurement** range. Established from
the commands the vendor library sends - `set_voltage_range` sends
`SOUR1:VOLT:RANGE`, `set_current_range` sends `CH1:IRANGE`, and
`set_autorange` switches range "for the measured current". A source
current is never judged against it, so there is no range for a small
level to sit at the bottom of.

The note recorded on 2026-08-21 said the same reconciliation was harmless
here "because the autorange is real". The conclusion was right and the
reason was wrong, and the wrong reason had been carried into the
instrument note, its front matter, the fault-23 fleet table and the
driver contract ledger. All four now say what was measured.

`_apply_source_current_range()` passes `disable_autorange` explicitly.
The vendor default is True - setting a range turns autoranging off as a
side effect - and none of the three ranging methods this driver uses
appears in the vendor's published API reference, so the default is not
ours to inherit. The fake client refuses an implicit call.

Still open, and narrowed: the sub-count floor on the Keithleys, the
B2901A and the GSM-20H10. Not the miniSMU, where a source current has no
range of its own to fall below.

## Wave 8b

**What a run does about a lost link.**

A run that loses its link de-energises, fails, keeps nothing, and blocks
the instrument until it is reconnected. Runs already in the table
survive untouched, with their unsaved data still unsaved.

That behaviour already worked after Wave 8a, as a consequence of the
transport latch, the uncertain shutdown report and the existing
`report_uncertain_shutdown()` block lining up. Nothing pinned the
combination, so any one of the three could have been changed without a
test going red. `tests/test_link_lost_during_a_run.py` now pins it
end to end through a real experiment, and its mutation round is what
establishes that it can fail.

`ShutdownReport.link_lost` distinguishes a link that stopped answering
from an instrument that reported a fault. Both block the instrument;
only the first needs a reconnect, and the operator message now says so,
along with what happened to the run and what did not happen to the
others.

[A fault injected below the layer under test](docs/faults/26-a-fault-injected-below-the-layer.md)
records the harness mistake found while writing that test: demo mode
fabricates readings without touching a transport, so a fault armed in
the transport let the run complete normally and the test pass.

## Wave 8a

**A link that stops answering stops the work.**

A query whose reply never arrives latches the transport into a refusing
state. Every later query raises `TransportDesynchronised` until the
transport is reconnected. There is no recovery in place.

Two things are wrong once an exchange fails, and either alone is enough
to stop: no later reply can be matched to the question that asked for
it, and the reading that was expected did not happen, so the sweep has a
hole in it and its timing is no longer what was requested.

`write()` stays permitted. A write never reads, so it cannot be one
behind, and every driver's `output_off()` is a write — which is what
lets a poisoned session de-energise its sample.

**`confirm_output_off()` no longer reports CONFIRMED on a link that has
stopped answering.** It did, on the grounds that being unable to ask is
not evidence of a fault. That is right for a dropped reply and wrong
here, in the function that decides whether a run's data may be kept.

The checkup stops at the break instead of warning and continuing.
Results from before it are kept, the report says it did not finish, and
the cleanup output-off still runs.

`clear()` is demoted to teardown housekeeping: its return value says a
device-clear call did not raise, which is a different question from
whether the stream is back in step.

Every broad `except` around a query names the exception and re-raises;
`tests/test_desync_not_swallowed.py` enforces that going forward.

**Driver behaviour changes** where an instrument stops answering during
`reset()`: that now ends the session rather than continuing with a note.
One that answers unusably is unchanged.

## The fleet, commissioned

Every registered driver carries a `bench_code` matching the code that is
running, from the 2026-08-25 round.

The U2722A carries one failure, and it is the driver correctly refusing
a configuration the instrument cannot perform: the checkup probes at
1 µA, which is a seventh of a count on the range that plan lands on. It
will go green when the checkup derives its probe level from each
instrument's envelope instead of a module constant — recorded in
`docs/open/technical-debt.md`, not done.

`Checkup.setup()` now grades each step and records an explicit skip for
checks that depended on a failed one, instead of crashing when a driver
declines a configuration.

## Below a count, the sign is not yours

**Deviation 54.** The U2722A refuses a source level below ten counts of
the active range, before the output is energised, naming the range that
would carry it. Below one count there is no signal, only offset residue,
and its polarity is not commanded.

Ten counts is a decision: one count is where a request first means
anything and the error there is 100%; ten caps it at 10%. It bounds
quantisation error and claims nothing about sign.

**It costs something real.** Nothing below 1.22 mV can be sourced on any
range, so a 1 mV level is refused everywhere. That is in the bench page.

The eleven probes behind it, the output capacitance, the asymmetric
clamp on R1uA and the charge that survives `*RST` are in
[Keysight U2722A](docs/instruments/keysight-u2722a.md).

## The GSM-20H10 was never broken

The 2026-08-24 checkup read as a regression. It was a USB-TMC read
timeout leaving the reply stream one behind, so every query returned the
previous command's answer. Re-run 2026-08-25 at `d332432`: 64 pass,
0 fail, with an identical driver fingerprint across the red and green
runs.

`SOUR:FUNC?` is verified against hardware, which is what the trip-axis
rule needs, and the C1 failure of 2026-08-21 is gone.

Detection and the latency evidence are in
[GW Instek GSM-20H10](docs/instruments/gwinstek-gsm20h10.md); the fix is
Wave 8a.

## The compliance chooses the range

**Deviations 52 and 53.** On the U2722A a compliance is settable only
between a tenth of the active range's full scale and full scale, which
makes the limit very nearly determine the range. The driver stops
treating them as two knobs:

- the range is chosen from the limit
- a range change that would strand a limit is declined, with a console
  line saying so
- a compliance no range can express is refused before the output goes
  on, naming each range's window
- every limit written is read back — the bench watched a 100 µA
  compliance silently become 12 mA on a range move, and a refused limit
  leaves the previous value in force rather than clamping
- a source-function change resolves the sourced quantity's limit to the
  narrowest value the range can hold that clears every level commanded
- the resolution each compliance buys is logged, because the range is
  what 14 bits divide

Two bands this instrument cannot express — below 100 nA, and between
10 mA and 12 mA — are in `bench/choosing-an-smu.md`, where somebody
picking an instrument finds them before the bench does. The per-range
windows and the measured evidence are in
[Keysight U2722A](docs/instruments/keysight-u2722a.md).

Two mutation rounds removed two pieces of code that changed no
observable behaviour, and fixed a fake that answered a query through its
write handler.

**Unverified against hardware** at the time of writing.

## Reports that say what happened

Three gaps the 2026-08-21 round found in the reports rather than in a
driver.

**An error names the commands it could have come from.** The queue is
drained once per group of writes, so a `-222` could not be attributed.
The commands written since the last drain are now listed. It stays a
list rather than a guess: SCPI does not require the error queue to be
ordered against writes.

**The miniSMU is traceable.** A recording proxy sits in front of the
vendor client, so calls appear as `client.set_current_limit(...)` rather
than as an invented SCPI string. It was the one driver whose exchanges
could not be audited from a bench report.

**The dirty flag says what was dirty.** A flag that is sometimes
alarming and sometimes not, with no way to tell which, gets ignored —
and the time it is ignored is the time it was real. Ignored files are
excluded so the tool's own output does not flag itself.

## One trip-axis rule for the SCPI drivers

The compliance trip is always on the quantity you are *not* sourcing, so
the axis to query depends on the source function. The GSM-20H10 was
OR-ing both trips, which adds a failure rather than removing one: a
stale value on the unused axis reads as a clamp that is not happening,
and the checkup's clamping check would have passed on it while the
mechanism the experiments depend on was broken.

The driver now reads `SOUR:FUNC?` and asks the complementary axis. The
B2901A's equivalent stays a separate implementation rather than a shared
helper, because that one is confirmed against hardware and this one is
not.

## Time per reading now means the steady-state cost

Every instrument pays a large one-off on the first reading after
`output_on()` — between 1.3x and 14x the steady figure across this
bench — and the checkup was averaging it into the number it reports.

A warm-up reading is taken and discarded before timing, at both ends of
the aperture fit, and the first read is reported on its own line as the
cost it is: paid once per run, not predictable from the steady figure.
The sweep deadline adds it once rather than per point.

This is not cosmetic. The figure is published as the **Per reading**
column in `bench/choosing-an-smu.md`, it sets the sweep deadline, and it
is one of two points `_aperture_cost()` fits a slope through, so a
first-read offset corrupts both slope and intercept.

The published figures were re-derived from the round's traces rather
than left until the next bench session, since they were overstating
every instrument meanwhile. The miniSMU is the exception and says so:
its transport recorded no command trace at the time.

## The compliance probe tells the truth about both edges

The checkup's compliance probe could not distinguish a working
compliance from an absent one. Two faults, opposite directions, one
cause — a threshold checked on one side. Recorded as
[A bound checked on one side only](docs/faults/25-a-bound-checked-on-one-side.md).

- **It judged an output that was still ramping.** The settle loop now
  polls until two readings agree, and "above the limit and still
  climbing" is expressible, which it was not before.
- **It passed an output beyond its limit**, because a large negative
  reading cleared a floor. An output past its own compliance is now a
  failure, checked before the ramping branch, because it is a fault
  whether it has come to rest there or not.

`COMPLIANCE_FLOOR` and `COMPLIANCE_CEILING` are named and both edges
come from measured hardware. A ceiling at the limit itself would fail a
working instrument.

**Three fakes never clamped**, so the file written to stop this probe
being non-discriminating was itself non-discriminating. All three hold
their limit now.

Tier 2's `compliance_tripped()` no longer goes through `attempt()`,
where a driver returning `None` passed indistinguishably from one
returning an answer. `None` is a skip, `False` a pass, `True` with the
output off a warning.

## The 2026-08-21 commissioning round, and a staleness rule that survives a merge

Every physical instrument re-checked at `7dc6264`, the first reports to
stamp the commit and firmware they describe.

`NOT_SOURCED` is confirmed against hardware from both directions. The
round found no new driver fault and several in the checkup tool.

Two schema changes, because recording the round exposed that the schema
could not:

- **`bench_code` replaces the commit-date comparison.** A commit date is
  rewritten by `git am`, by a rebase and by a squash-merge, so the same
  bytes answered differently depending on when they were merged.
  Staleness now compares a digest of the driver's contents plus its
  shared dependencies. No git is consulted. Recorded as
  [A derived claim resting on something a merge rewrites](docs/faults/24-derived-from-a-rewritable-date.md).
- **`bench_result` replaces the inference that a date means a pass.** A
  failing checkup renders as `failing`, distinct from `stale`: stale
  means nobody has checked recently, failing means somebody has and it
  did not pass.

## Direct GPIB-HS: address picker candidates

Selecting **NI GPIB-HS** left the address combobox empty while a typed
`GPIB0::9::INSTR` connected and ran. The panel now offers
`GPIB0::1::INSTR` through `GPIB0::30::INSTR` with no implicit selection,
and discovery still never claims an instrument occupies a GPIB address.
Recorded as
[Direct GPIB-HS address picker was empty](docs/faults/22-direct-gpib-hs-empty-address-picker.md).

## Direct GPIB-HS: Windows/B2901A commissioned

On 2026-08-18 a genuine NI GPIB-USB-HS (`3923:709b`, revision `0x0101`)
bound to WinUSB drove a Keysight B2901A at GPIB address 9 through
`tools/smu_checkup.py --transport gpib-hs`. Tiers 1, 2 and 3 passed,
without NI-VISA or NI-488.2 installed.

Scope stays narrow: VISA remains the default, direct GPIB-HS is explicit
and optional, and no driver or experiment changed. The bench proves this
adapter revision with this instrument on Windows; it claims nothing
about SRQ, serial poll, secondary addressing or multi-controller
operation. `docs/architecture/direct-gpib-usb-hs.md` remains open for
robustness questions only.

## Direct GPIB-HS: Windows needed an IFC pulse

A genuine adapter opened over WinUSB but returned `NO_BUS` for every
command, including a bare UNL, before any instrument address was
involved. Sending NI USB `IBSIC` to pulse GPIB IFC fixed it — a bench
result, not an inferred workaround.

`NIUSBGPIBTransport` pulses IFC after every controller construction,
including a timeout-recovery reopen. A failed IFC closes the fresh
controller and fails the connection. Offline tests prove the pulse
cannot be removed without a red test. Recorded as
[Direct GPIB-HS opened but returned NO_BUS](docs/faults/27-direct-gpib-hs-missing-ifc.md).

## Optional direct NI GPIB-USB-HS transport

A non-default path for the occasional Windows bench that needs a genuine
NI GPIB-USB-HS without NI-VISA or NI-488.2.

`NIUSBGPIBTransport` wraps `ni-gpib-usb-hs==0.1.0` behind the existing
transport contract, as an optional `direct-gpib` extra imported only at
connect time. VISA stays the default everywhere and this has to be
selected explicitly as **NI GPIB-HS** / `--transport gpib-hs`; there is
no silent fallback. Discovery probes only the USB adapter and never
invents occupied GPIB addresses, and both paths normalise a GPIB
resource to one ownership key so two windows cannot drive it through
different stacks.

**Not commissioned on Windows** at the time of writing — upstream 0.1.0
lists macOS and Linux. `docs/architecture/direct-gpib-usb-hs.md` records the
WinUSB prerequisite, the upstream scope limits, the GPL-2.0-only
dependency note and the bench questions owed. No fault entry was
invented before hardware produced a fault.

## Documentation: the commissioning round as a procedure

No behaviour change. The round produced a way of working that was not
written down, and most of what it cost was learning it.

- **`docs/workflow/commissioning-round.md`** — why every instrument is
  checked in one pass rather than repaired one at a time, and the probe
  habits that ended a week of wrong mechanisms.
- **`docs/plan.md`** describes the round in progress rather than a
  finished wave.
- **`HANDOFF.md`** names the branch in flight, and carries the point the
  round taught: a clean result is not a correct one, and where a check
  reports "none" the question is whether anything looked.

## The compliance readback, and the check that would have saved a week

D5 and D6. Nothing in this suite ever read a compliance back, which is
why the GSM-20H10's silent collapse from 105 µA to 1 nA on a single
ranging command took a week to find.

- **`read_current_limit()` / `read_voltage_limit()` on `BaseSMU`**,
  returning `None` where a driver cannot ask. Implemented for the
  GSM-20H10 and the U2722A.
- **`COMPLIANCE_READBACK_TRUSTED` is three-valued.** `True` means the
  readback was checked at the bench against a value the instrument was
  known to hold; `False` means the driver cannot read one back; `None`
  means it answers and nobody has checked whether it tells the truth. A
  readback an instrument answers dishonestly is worse than none, so
  `verify_compliance()` reports `unverified` rather than `pass`.
- **The checkup gains "compliance survives ranging"**, and deliberately
  sends the limit before the ranges — the order fault 15 exists to
  prevent. That is the point: the question is what ranging does to a
  compliance already in force, and asking it the safe way round lets the
  experiment's own limit paper over the damage. The correct order is
  restored immediately after, and the output is off throughout tier 2.
- **`compliance_readback` in the contract ledger**, so a driver gaining
  it fails the ledger for every other driver until each records where it
  stands.

Still open: `apply_ranges` reports what it sent rather than what was
accepted, and the range half of that is untouched. Most instruments have
no readback implemented, so their clean checkups mean *none observed*.

## Commissioning tools: say which code and which firmware

Three gaps of the same shape, all found by the tools being wrong about
the GSM-20H10 in ways nobody could see.

- **`core/provenance.py`** — reports carry the commit they ran at,
  whether the tree was dirty, and the instrument's firmware from
  `*IDN?`, in both the JSON and the Markdown header from one call so the
  two cannot drift. Written from the seven real `*IDN?` replies rather
  than from the SCPI standard, because two of them do not follow it.
- **`tools/timing_scan.py` checks that its readings are readings.** It
  timed `measure()` without looking at the result, so a `(None, None)`
  was timed exactly like a measurement — which is how it reported a flat
  10.3 ms across a thousandfold NPLC change and printed a conclusion
  from a run where the output was never energised. It now counts blanks
  and refuses to fit when any turn up.
- **It reports noise, not just time.** A reading can return in the same
  wall-clock time whatever the NPLC, so timing alone cannot tell an
  instrument that integrates from one that ignores the request. A
  longer integration that is not quieter is reported plainly: the NPLC
  setting on that instrument is decorative.

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
  contract ledger records which, with the reason beside it — `False`
  means the default was verified harmless on that model, not that nobody
  looked.
- **`RangePlan.widest()`**: an axis carrying nothing no longer wins a
  shared knob.
- **GSM-20H10** sends nothing at all on that axis.

A U2722A driver override was written, passed its tests, and was then
found unreachable by mutation. Removed, with the reason left in its
place: a hook that looks load-bearing and never runs is worse than no
hook.

Still open: `apply_ranges` reports what it sent rather than what was
accepted. The "0 failures" above are *none observed*, not none — nothing
read a compliance back.

## GSM-20H10 commissioning: what the 2026-08-20 bench session found

- **`tools/smu_checkup.py` applied limits before ranges** — the order
  fault 15 exists to prevent — costing three failures and taking tier 3
  with them. No measurement was ever at risk: every experiment already
  ordered it correctly. The tool was producing a failure the application
  cannot produce, and a cascade behind it.
- **A source-autorange command silently resets the compliance.** One
  command, no error, from 105 µA to 1 nA. Written up as
  [A ranging command that silently resets the compliance](docs/faults/23-autorange-resets-compliance.md).
  Runs survive it only because fault 15's ordering puts the experiment's
  own compliance after the ranging block — accidental, not designed.
- **`RangePlan`'s `AUTO` means two different things**, and the second is
  what emits that command. Recorded rather than fixed at the time: a
  rule designed from the instruments looked at so far would have turned
  the rest into exceptions.
- **Three other things the instrument does**, all in its note: a
  measurement range can be refused and silently narrowed; `OUTP?`
  returns 0 with the output physically on; and setting the measurement
  range of the sourced quantity is refused by name.
- **First manual extracts in the repository.**
  `docs/reference/manuals/` now holds the GSM-20H10 factory-defaults
  table and four command entries.
- **A test with hardcoded dates that rotted** now derives them from each
  note, and checks every qualifying note rather than whichever sorted
  first.

## Fixed sourcing vs time: the last sample, and the clock ceiling

Windows CI found an eleven-sample run returning ten; Linux could not
reproduce it. The clock ceiling was pre-empting the sample due at
exactly the duration, because Windows' ~15.6 ms timer granularity puts a
10 ms final wait past the ceiling before that sample is taken.

**The ceiling now has a grace of one interval.** A run may exceed its
requested duration by up to one interval, which is the stated cost of
not dropping the final sample. A run a whole interval behind the agreed
window is still stopped.

Two regression tests, deliberately not timing-dependent: one reproduces
the Windows shape on any platform by making a single reading slow; its
pair asserts the grace did not become an amnesty for a runaway run.

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
  Stop, unchanged. Stop keeping its meaning is the load-bearing half.
  Neither button talks to the instrument.
- **The time column is measured and the schedule aims at absolute
  deadlines**, avoiding
  [Reconstructed x-axes](docs/faults/09-reconstructed-x-axes.md) and
  [Sweep completion slept rather than polled](docs/faults/05-slept-not-polled.md)
  in a new place. Late samples are counted and the achieved mean
  interval is stored beside the requested one.
- **`tools/build_docs.py` no longer asserts that every experiment is a
  port**, which had been rendering "Ported from `New experiment`" — the
  generator making the kind of false claim it exists to prevent.

26 new tests. 22 deliberate mutations; the first round left four
survivors — two real holes in the tests, and two mutations shaped so
they could not fail, which is the same fault as a test that cannot
fail.

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
