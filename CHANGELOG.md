# Changelog

Newest first. Append-only: entries are not edited once written, because
this is the record of *why something changed and when* — the record of
what is true *now* lives in `docs/`.

The work so far was organised as numbered waves adopting one code
review. That adoption ended with Wave 7; the numbering continues from
Wave 8 as a plain sequence number for a unit of work.

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

A query whose reply never arrives now latches the transport into a
refusing state. Every later query raises `TransportDesynchronised`
until the transport is reconnected. There is no recovery in place.

Two things are wrong once an exchange fails, and either alone is enough
to stop: no later reply can be matched to the question that asked for
it, and the reading that was expected did not happen — so the sweep has
a hole in it and its timing is no longer what was requested.

`write()` is deliberately still permitted. A write never reads, so it
cannot be one behind. Every driver's `output_off()` is a write, which is
what lets a poisoned session de-energise its sample.

**`confirm_output_off()` no longer reports CONFIRMED on a link that has
stopped answering.** It returned CONFIRMED when the error queue could
not be read — correct for a dropped reply, wrong here, and it is the
function that decides whether a run's data may be kept. This is a fault
in shipped code, not a consequence of the change: before this, a run
that lost its link reported its shutdown as confirmed when nothing had
confirmed it.

The checkup stops at the break instead of warning and continuing. On
2026-08-25 it ran 1386 further queries against a stream it had already
declared unrecoverable. Results taken before the break are kept and the
report says it did not finish; the cleanup output-off still runs.

`clear()` is now teardown housekeeping. As a recovery path it reported
that a device-clear call had not raised, which is a different question
from whether the stream is back in step.

Every broad `except` around a query would have swallowed this, so each
names the exception and re-raises it first.
`tests/test_desync_not_swallowed.py` is what stops the next one being
added without it — the obligation is checked by a machine because it is
too spread out to remember.

Driver behaviour changes where an instrument stops answering during
`reset()`: that now ends the session rather than continuing with a note.
An instrument that answers unusably is unchanged, which is the case the
original rule was written for.

## The fleet, commissioned

Every registered driver now carries a `bench_code` matching the code
that is running. The 2026-08-25 round, in full: miniSMU, B2901A, 2635B,
2611A and 2401 clean; the GSM-20H10 clean once its USB stream stopped
desynchronising; the U2722A carrying one failure that is the driver
declining a configuration the instrument cannot perform.

That last one is worth being plain about, because a red line in a report
invites somebody to reopen it later. The checkup probes at 1 uA. On the
U2722A the shared-knob reconciliation puts the current axis on R120mA,
where one count is 7.32 uA. Deviation 54 refuses the level before the
output is energised, and the trace ends with the output off. Nothing is
wrong. The check will go green when the checkup derives its probe level
from each instrument's envelope instead of a module constant, which is
recorded and not done.

The run also confirmed `Checkup.setup()` against hardware rather than a
fake: the refusal arrives as a graded failure naming the step, with the
driver's own message, and the two checks that depended on it recorded as
skips. Tiers 1 and 2 completed around it.

## Below a count, the sign is not yours

The U2722A's remaining checkup failure read as a compliance fault: the
output reached −2 V against a 1 V limit that had been verified by
readback two commands earlier. It was not a compliance fault. Eleven
probes established that `SOUR:VOLT:LIM` is genuine bipolar compliance —
two ranges, both polarities, two limit values, leads on and off, always
clamping about 0.05% below the value set.

What failed is that the level was never sourced at all. On R120mA one
count is 7.32 µA, and the checkup asked for 1 µA — a seventh of a count.
Commanding `-1 µA` and `+1 µA` on that range produces **the same
output**: below a count there is no signal, only offset residue, and its
polarity is not under anyone's control. It sat positive through every
probe and clamped harmlessly; it sat negative during the commissioning
run and walked the output to the range rail.

So the driver now refuses a source level below ten counts of the active
range, before the output is energised, naming the range that would carry
it. Ten counts is a decision — one count is where a request first means
anything and the error there is 100%, ten caps it at 10% — and it is one
constant. It bounds quantisation error and claims nothing about sign;
proving that would need a known load.

**It costs something real.** R2V's count is 122 µV, so the instrument's
absolute voltage floor becomes 1.22 mV and a 1 mV level is refused on
every range. That is in the bench page, not buried here.

Three things nobody went looking for, now recorded: the negative clamp
on R1uA regulates a hundred times more loosely than the positive one
(134 mV of spread against 1 mV); the bare output looks like about 36 pF,
so at 100 nA it ramps a volt per second and needs twenty readings to
mean anything; and charge survives `*RST`, output-off and the gap
between runs, so an early reading is the previous measurement's residue.

**The checkup had to learn that a refusal is an answer.** Its
configuration calls were made bare while every check was graded, so the
first driver to decline a configuration crashed the tool instead of
being reported by it. `setup()` now grades each step, stops at the first
failure rather than burying it under consequences, and records an
explicit skip for the checks that depended on it. The U2722A will report
one honest failure where it used to report one wrong one.

That last one is why this took eleven probes. Three wrong conclusions
were drawn along the way — that the limit was one-sided, that it did
nothing at all, that the leads or the 4-wire sense loop or deviation
53's own `CURR:LIM` write were responsible — and every one of them came
from reading a value before it had arrived.

## The GSM-20H10 was never broken

Its 2026-08-24 checkup read as a regression: `measure()` returning
nothing, the instrument insisting the output was off after an `OUTP 1`
that had queued no error. None of it was real.

A USB bulk-in read had timed out, and a timed-out read on USB-TMC leaves
the reply stream **one behind** — every query afterwards returns the
previous command's answer. The instrument had been saying so all along,
with `-230, "Data corrupt or stale"`, and the timing made it certain:
query latency collapsed from ~20 ms to 1.3 ms across 1381 queries,
because every reply was already sitting in the buffer before it was
asked for.

Re-run on 2026-08-25 at `d332432`: **64 pass, 0 fail**, with a 20 ms
median throughout and no collapse. The driver fingerprint is identical
across the red runs and the green one, so nothing in the code moved
between them. `SOUR:FUNC?` is verified against hardware at last — it
answers `VOLT` and `CURR` and tracks a source-function change, which is
what P4's trip-axis rule needs — and the C1 failure of 2026-08-21 is
gone.

The fault is intermittent, roughly one run in two or three, and only on
this instrument: it is the only one in the fleet reached over USB-TMC
through libusb-win32 rather than over Prologix.

Recorded rather than fixed. The checkup already detects the desync and
warns that everything below it is suspect; what it does not do is stop,
and that is the next wave.

## The compliance chooses the range

The 2026-08-24 commissioning round left the U2722A failing four checks
with `-222, "Data out of range"`. Seven probe snippets characterised
what the Programmer's Reference states only as "the maximum depends on
the range": a limit is settable **between a tenth of the active range's
full scale and full scale**, measured directly on R100uA and R20V.

That makes the compliance very nearly determine the range. 5 µA is
settable on R10uA and nowhere else, and 100 µA cannot exist on R120mA at
all. So the driver stops treating them as two knobs: the range is chosen
from the limit, a range change that would strand a limit is declined
with a console line saying so, and a compliance no range can express is
refused before the output goes on — naming each range's window,
including the real gap between 10 mA and 12 mA where the decade spacing
of the current ranges breaks.

**Every limit written is now read back.** The bench watched a 100 µA
compliance become 12 mA on a move to R120mA with a clean error queue —
the protection around a sample widening 120-fold in silence. And a limit
the instrument *refuses* leaves the previous value in force rather than
clamping, so a run continues against whatever was already there. The
refusal does reach the error queue, but only `start_linear_sweep()` ever
reads it, and a bias-hold run never looks.

**A source-function change gives the sourced quantity's own limit back
to that quantity.** `SOUR:CURR:LIM` is the compliance while sourcing
voltage; while sourcing current it applies to the thing the operator is
commanding, and a value carried over from a previous run is at best
meaningless. It now resolves to the narrowest limit the range can hold
that still clears every level commanded — the range floor until a level
exceeds it, then twice the largest, capped at full scale. Full scale
alone would never cap a level either, but it is the weakest value in the
window and would trade a tight fallback for none. The doubling keeps the
write off the per-point path, where it would have cost two round trips a
point. Protection during the run comes from `SOUR:VOLT:LIM`, which is
what the experiment sets.

**The compliance now also picks the resolution**, because on this
instrument the compliance determines the range and the range is what
14 bits divide. Typing 90 µA instead of 9 µA costs a decade of it, with
nothing on the panel to say so, so the driver logs the resolution each
compliance buys and the bench page carries the table. The two bands this
instrument cannot express — below 100 nA, and between 10 mA and 12 mA —
are in `choosing-an-smu.md`, where somebody picking an instrument will
find them before the bench does.

Two mutation rounds. The first found that the special case making `AUTO`
defer to a known compliance changed no observable behaviour — the
stranding guard already declines the widest-range request — and that the
window check inside the readback could not fire, because the range is
always the one the limit chose. Both removed rather than left as
decoration. It also found the fake instrument answering `SOUR:CURR:LIM?`
through its `SOUR:CURR:LIM` *write* handler, the same shape as the
GSM-20H10 fake's `SOUR:FUNC?` fault, which made the readback silently
return nothing; the fake now refuses to change state when questioned,
and a test says so.

**Unverified against hardware.** The driver changed, so `checkup-owed`
will report this instrument as owing a session until one is run.

## Reports that say what happened

Three gaps the 2026-08-21 round found in the reports themselves, none of
them in a driver.

**An error now names the commands it could have come from.** The error
queue is drained once per group of writes, so the U2722A's four `-222`
failures each arrived after three commands and nothing could say which
one the instrument refused. The commands written since the last drain
are already recorded for the trace, so listing them costs nothing —
where draining after every write is a round trip each and would roughly
double a run. It stays a list rather than a guess: SCPI does not require
the error queue to be ordered against writes.

**The miniSMU is traceable.** `install_trace` wraps `write` and `query`,
which is everything for a text instrument; `MiniSMUTransport` carries
method calls on `transport.client` and answers only `*IDN?`, so
`--trace` produced a report with one line in it. A recording proxy now
sits in front of the client, so calls appear as
`client.set_current_limit(0.0001, channel=2)` — formatted as the call
the driver made, since pretending it was a SCPI string would invent a
wire format this instrument does not have. It was the one driver whose
exchanges could not be audited from a bench report, which is how a
driver sending another instrument's dialect gets caught.

**The dirty flag says what was dirty.** A checkup came back `dirty:
True` from a tree its operator had just hard-reset and believed clean,
and neither of us could tell from the report whether it mattered. It was
scratch files from a debugging session sitting beside the code — but a
modified driver would have looked exactly the same, and that would have
made the whole report unattributable. A flag that is sometimes alarming
and sometimes not, with no way to tell which, gets ignored, and the time
it is ignored is the time it was real. Ignored files are excluded, so
the tool's own output in `checkups/` does not flag itself.

## One trip-axis rule for the SCPI drivers

`compliance_tripped()` on the GSM-20H10 queried both protection trips
and returned True if either was set. Both instrument manuals state the
rule these queries follow, word for word — `:CURRent:PROTection:
TRIPped?` reports the compliance state of the **V-Source**, and
`:VOLTage:PROTection:TRIPped?` the **I-Source** — so the limit is always
on the quantity you are not setting, and the axis to ask depends on what
is being sourced.

Against that, OR-ing added a failure rather than removing one: on a
voltage source the voltage trip describes an I-Source that is not
running, and a value left on it from an earlier run reads as a clamp
that is not happening. The checkup's clamping check would have passed on
that stale flag while the mechanism the experiments depend on was
broken.

The driver now reads `SOUR:FUNC?` and asks the complementary axis, which
is what the B2901A already did under its own spellings. They stay two
implementations rather than one shared helper, because the B2901A's is
confirmed against hardware and this one is not; the contract ledger
catches drift between them.

`MEMory` is a third source mode on this model, and in it neither trip
query describes what the instrument is doing. That returns None — "cannot
say" — rather than a False nobody measured.

Two faults in the test fake surfaced with it. Its trip reply was a
single flag for both axes, so it could not tell the two candidate rules
apart; and `SOUR:FUNC?` matched its *write* handler, so asking the fake
what mode it was in silently reset it to voltage. A real instrument does
not answer a question by changing its own state.

**Unverified against hardware.** `SOUR:FUNC?` has never been sent to
this instrument — the write form is all that appears in any trace — so
the next checkup is the first time that query runs.

## Time per reading now means the steady-state cost

Every instrument in the registry pays a large one-off on the first
reading after `output_on()`, and the checkup was averaging it into the
figure it reports. Measured across the 2026-08-21 round:

| | first read | steady | reported | overstated |
|---|---|---|---|---|
| B2901A | 173.2 ms | 4.8 ms | 38.6 ms | 8x |
| 2635B | 1098.4 ms | 17.1 ms | 233.6 ms | 14x |
| GSM-20H10 | 318.9 ms | 14.3 ms | 75.3 ms | 5.2x |
| 2611A | 70.8 ms | 15.9 ms | 26.9 ms | 1.7x |
| 2401 | 91.7 ms | 37.0 ms | 48.0 ms | 1.3x |

It is not autoranging, which was the first guess — the B2901A's ranges
were fixed before its 173 ms read and it still paid 36x its steady
state.

The figure is not cosmetic: it is published as the **Per reading**
column in `bench/choosing-an-smu.md` where someone plans a run from it,
it sets the sweep deadline, and it is one of two points
`_aperture_cost()` fits a slope through — so a first-read offset that
differs between the two integration times corrupts both the slope and
the intercept.

A warm-up reading is now taken and discarded before timing, at **both**
ends of the aperture fit, and the first read is reported on its own line
as the cost it is: paid once per run, not predictable from the steady
figure, and spanning a factor of two hundred across this bench. The
sweep deadline adds it once rather than per point — which was making the
deadline accidentally generous, and would have made it accidentally
tight on any instrument whose first read is quicker than its steady
state, arriving as `sweep completes: fail` with nothing to say why.

The published figures were re-derived from the round's traces rather
than left until the next bench session, since they were overstating
every instrument in the meantime. The miniSMU is the exception and says
so: its transport records no command trace, so its 6.0 ms cannot be
split from the report and will be split by the next checkup instead.

## The compliance probe tells the truth about both edges

The 2026-08-21 round found that the checkup's own compliance probe could
not distinguish a working compliance from an absent one. Two faults,
opposite directions, same cause — a threshold checked on one side.

- **It judged an output that was still ramping.** The settle loop left
  the moment a reading passed 80% of the limit, without asking whether
  it was still climbing. On the GSM-20H10 that stopped at 0.9151 V of a
  1 V limit, still rising 0.23 V per poll after 1.294 s of a 6 s budget,
  then asked whether the instrument was clamping and recorded the
  correct answer `False` as a failure. It now polls until two readings
  agree, and `_ramping` is decided by the last pair rather than by where
  they landed — so "above the limit and still climbing" is expressible,
  which it was not before.

- **It passed an output beyond its limit.** The U2722A sat at −2.0 V
  against a 1 V compliance, the limit having been refused for being
  below 10% of the active range, so the range rail bounded the output
  instead — and the probe recorded a pass, because −2.0 clears a 0.8
  floor. An output past its own compliance is now a **failure**, checked
  before the ramping branch, because it is a fault whether it has come
  to rest there or not. Recorded as
  `docs/faults/25-a-bound-checked-on-one-side.md`.

`COMPLIANCE_FLOOR` and `COMPLIANCE_CEILING` are named, and both edges
come from measured hardware: the miniSMU's healthy 1.023× overshoot and
the U2722A's 2.0×. A ceiling at the limit itself would fail a working
instrument.

**The fakes never clamped.** Found by C7 rather than by reading them:
`Keithley2635BTransport`, `TSPTransport` and `B2901ATransport` computed
`V = I x R` with no limit, so `test_checkup_compliance_probe.py` — the
file written to stop this probe being non-discriminating — was
asserting against 1e6 V measured against a 1 V limit, while the same
fake reported that output as in compliance. All three hold their limit
now.

Tier 2's `compliance_tripped()` no longer goes through `attempt()`,
where a driver returning `None` passed indistinguishably from one
returning an answer. `None` is a skip, `False` is a pass with the value
recorded, and `True` with the output off is a warning — a latched flag
and a query on the inactive axis both look like that.

Re-running any instrument's checkup against this is expected to change
its result. The U2722A should report a second, different failure with
the same underlying cause.

## The 2026-08-21 commissioning round, and a staleness rule that survives a merge

Every physical instrument was re-checked at `7dc6264`, the first set of
reports to stamp the commit and firmware they describe. Two results:

- **`NOT_SOURCED` is confirmed against hardware.** The GSM-20H10 passes
  *compliance survives ranging* — 100 µA held across the ranging
  sequence on the instrument where source autorange used to reset it.
  The U2722A confirms the same fix from the other direction: its
  voltage-sourcing case now selects `R100uA` rather than the widest
  range, and the limit is accepted.
- **The round found no new driver fault, and several in the checkup
  tool.** Recorded as C1 and C5–C9 in `docs/open/technical-debt.md`.
  The one that matters most is C7: the compliance probe tests only a
  floor, so it passed the U2722A at −2 V against a 1 V limit — an
  output beyond its compliance, which means the compliance was not in
  force. C1 makes a working instrument look broken; C7 makes a broken
  one look fine.

The U2722A's four `-222` failures are `D7`, not a regression: when
current is the sourced quantity, the measure axis arrives as `AUTO` and
takes the shared knob to R120mA, where a 100 µA compliance is below that
instrument's 10%-of-range floor. Its note now says so, and its bench
page says not to source current on it until D7 lands.

Alongside it, two schema changes, because recording the round exposed
that the schema could not:

- **`bench_code` replaces the commit-date comparison.** Staleness was
  `git log -1 --format=%cs` against `last_bench`, and a commit date is
  rewritten by `git am`, by a rebase, and by a squash-merge — so the
  same bytes answered differently depending on when they were merged,
  and the generated pages disagreed with a fresh build on an unchanged
  tree. It now compares a digest of the driver's contents plus its
  shared dependencies, computed in `core/provenance.py` and printed in
  every report header. No git is consulted, which also removed a
  shallow-clone guard that was silently skipping the check that catches
  a hand-edited page. Recorded as
  `docs/faults/24-derived-from-a-rewritable-date.md`.
- **`bench_result` replaces the inference that a date means a pass.**
  A failing checkup now renders as its own status, `failing`, distinct
  from `stale`: stale means nobody has checked recently, failing means
  somebody has and it did not pass. Under the previous schema the
  U2722A would have rendered `Verified: yes`.

## Direct GPIB-HS: address picker candidates

The first normal `main.py` run after Windows/B2901A commissioning exposed a
GUI-only fault: selecting **NI GPIB-HS** left the address combobox empty, while
manually typing `GPIB0::9::INSTR` connected and completed a run.

- Direct discovery remains conservative and still never claims that an
  instrument occupies a GPIB address.
- The connection panel now treats valid manual candidates separately and offers
  `GPIB0::1::INSTR` through `GPIB0::30::INSTR`, with no implicit selection.
- A dedicated offline regression test guards both the candidate range and the
  distinction between zero discovered resources and populated GUI choices.
- The observed fault is recorded in
  `docs/faults/22-direct-gpib-hs-empty-address-picker.md`.

## Direct GPIB-HS: Windows/B2901A commissioned

The optional direct NI GPIB-USB-HS path has completed its first full Windows
bench commissioning. On 2026-08-18 a genuine NI GPIB-USB-HS (`3923:709b`,
revision `0x0101`) bound to WinUSB drove a Keysight B2901A at GPIB address 9
through `tools/smu_checkup.py --transport gpib-hs`; Tiers 1, 2 and 3 all
passed.

- Tier 1 identified the B2901A through the normal suite transport/driver path.
  Tier 2 exercised the non-sourcing configuration path and instrument error
  checks. Tier 3 completed the checkup's controlled sourcing path. This closes
  the basic Windows commissioning owed by the two entries below.
- The bench result depends on the IFC compatibility fix found during the same
  commissioning: upstream `ni-gpib-usb-hs==0.1.0` opened the adapter but
  returned `NO_BUS` until the transport sent NI USB `IBSIC` to pulse GPIB IFC.
  With that pulse in the transport, the full checkup passes without NI-VISA or
  NI-488.2 installed.
- Scope stays deliberately narrow: VISA remains the default, direct GPIB-HS is
  explicit and optional, and no instrument driver or experiment changed. The
  bench proves this genuine adapter/revision with the B2901A on Windows; it
  does not claim unsupported upstream features such as SRQ, serial poll,
  secondary addressing or multi-controller operation.
- `docs/open/direct-gpib-usb-hs.md` now records the full checkup as complete.
  It remains open only for robustness/stress questions such as deliberately
  induced timeout recovery and large-reply framing, not for basic Windows
  operation.

## Direct GPIB-HS: Windows needed an IFC pulse

The first real Windows bench run found the fault the open-state note was waiting
for. A genuine NI GPIB-USB-HS opened over WinUSB/libusb, but every command — even
a bare UNL — returned `NO_BUS` before an instrument address or SCPI command was
involved. The same Keysight B2901A and IEEE-488 cable were known good under NI's
driver.
- Re-applying USB configuration did not help. Sending the NI USB `IBSIC`
  interface-clear operation did: UNL succeeded immediately afterwards and the
  B2901A at address 9 returned its `*IDN?`. That is the causal bench result, not
  an inferred workaround.
- `NIUSBGPIBTransport` now pulses IFC after every controller construction,
  including a timeout-recovery reopen. A failed or malformed IFC transaction
  closes the fresh controller and fails the connection.
- The workaround remains inside the explicitly selected direct transport; VISA,
  instrument drivers and experiments are unchanged. Offline tests pin the USB
  request/response seam and prove the pulse cannot be removed without a red test.
- The observed failure and recovery are recorded in
  `docs/faults/21-direct-gpib-hs-missing-ifc.md`. Full Tier 1/2/3 checkup
  commissioning remains open.

## Optional direct NI GPIB-USB-HS transport

A deliberately non-default path for the occasional Windows bench that needs a
genuine NI GPIB-USB-HS without NI-VISA/NI-488.2.
- `NIUSBGPIBTransport` wraps `ni-gpib-usb-hs==0.1.0` behind the existing
  transport contract. The package is an optional `direct-gpib` extra and is
  imported only at connect time.
- VISA remains the connection-panel default and the checkup tool's inferred
  transport for a GPIB resource. Direct USB control has to be selected as
  **NI GPIB-HS** / `--transport gpib-hs`; there is no silent fallback.
- Discovery probes only the USB adapter and never invents occupied GPIB
  addresses. VISA and direct paths normalise the same GPIB resource to one
  ownership key so two windows cannot drive it through different stacks.
- The adapter honours per-query read timeouts through the pinned 0.1.0 API and
  implements timeout recovery by reopening the USB controller and sending
  Selected Device Clear. Offline tests cover those seams without hardware; a
  separate policy test guards that the backend stays optional, VISA-default, and
  unprobed until explicitly selected.
- `smu_checkup.py --trace` can exercise this transport directly, starting with
  Tier 1 before any sourcing.

**Not commissioned on Windows.** Upstream 0.1.0 lists macOS/Linux rather than
Windows, so `docs/open/direct-gpib-usb-hs.md` records the WinUSB prerequisite,
the upstream scope limits, GPL-2.0-only dependency note, and the exact bench
questions still owed. No fault entry was invented before hardware produced a
fault.

## Documentation: the commissioning round as a procedure

No behaviour change. The August 2026 round produced a way of working
that was not written down anywhere, and most of what it cost was
learning it.

- **`docs/workflow/commissioning-round.md`** — checking every
  instrument in one pass rather than repairing them one at a time, and
  why a subset is not enough. The argument in one line: the 2401, the
  B2901A and the GSM-20H10 send a byte-identical command and only the
  GSM is damaged by it, so a rule written from any subset turns the
  rest into exceptions.

  Also the habits that ended a week of wrong mechanisms — ask for the
  manual instead of reasoning from a plausible story, build a probe
  whose *interesting* answer is the correct one, put a control leg on
  every probe, and check a query works before believing it.

- **`docs/plan.md`** now describes the round in progress rather than a
  finished wave: what has landed on `driver_checkups`, what triggered
  it, the next four steps in order, and the one decision waiting (D7,
  the measure axis of the sourced quantity).

- **`HANDOFF.md`** says that `main` is not the whole picture and names
  the branch, because the next useful step is a bench session and a
  reader arriving at `main` would not know that. It also gains the
  point the round taught: a clean result is not a correct one, and
  where a check reports "none" the question is whether anything looked.

## The compliance readback, and the check that would have saved a week

D5 and D6 from the commissioning round. Nothing in this suite ever read
a compliance back, which is why the GSM-20H10's collapse — 105 uA to
1 nA from a single ranging command, silently, with a clean error queue
— took a week to find and surfaced only because a later innocent
command tripped over the collapsed value.

- **`read_current_limit()` / `read_voltage_limit()` on `BaseSMU`**,
  returning `None` where a driver cannot ask. Implemented for the
  GSM-20H10 and the U2722A.

- **`COMPLIANCE_READBACK_TRUSTED` is three-valued**, and the third
  value is the point. `True` means the readback was checked at the
  bench against a value the instrument was known to hold. `False` means
  the driver cannot read one back. `None` means it answers and nobody
  has checked whether it tells the truth.

  `None` exists because of `OUTP?` on the GSM-20H10, which returns 0
  with the output on and 10 V flowing. At least one state query on that
  instrument lies, and five rounds of reasoning were built on believing
  it. A compliance readback that an instrument answers dishonestly is
  worse than none: it produces confident reassurance about the exact
  thing it exists to verify. So `verify_compliance()` reports
  `unverified` rather than `pass`, and the checkup skips rather than
  claims.

- **The checkup gains "compliance survives ranging"** — and it
  deliberately sends the limit *before* the ranges, which is the order
  fault 15 exists to prevent and which this tool was fixed last week to
  stop using. That is the point: the question is what ranging does to a
  compliance already in force, and asking it the safe way round lets
  the experiment's own limit arrive afterwards and paper over the
  damage. A probe whose interesting answer is not the correct one
  proves nothing. The correct order is restored immediately after, and
  the output is off throughout tier 2.

  A mutation confirming this: reordering that block to the "safe" order
  makes the check miss a collapse entirely.

- **`compliance_readback` in the contract ledger**, so a driver gaining
  it fails the ledger for every other driver until each records where
  it stands.

Six mutations, all caught.

Still open: `apply_ranges` reports what it *sent* rather than what was
accepted, and the **range** half of that is untouched — the GSM-20H10
will refuse a measurement range and leave a narrower one in force with
nothing noticing. And most instruments have no readback implemented yet, so
their clean checkups still mean *none observed*.

## Commissioning tools: say which code and which firmware

Three gaps of the same shape, all found by the tools being wrong about
the GSM-20H10 in ways nobody could see.

- **`core/provenance.py`** — checkup reports now carry the commit they
  ran at, whether the tree was dirty, and the instrument's firmware
  from `*IDN?`. In both the JSON and the Markdown header, from one
  call, so the two cannot drift.

  The commit gap cost five rounds of hypotheses: a GSM-20H10 checkup
  was clean on 2026-08-06 and had six failures on 2026-08-18, and
  working out that ranging had entered the checkup in between meant
  bisecting git by hand. A dirty flag rides along because a sha alone
  would be a lie by omission — a report from a modified tree describes
  code that exists nowhere else.

  The firmware gap has not cost anything yet and is about to. Every
  finding in the GSM-20H10's note is a claim about `V1.16`; GW Instek
  publish `V1.30` with no release notes; and `checkup-owed.md` watches
  the code, not the instrument. Upgrading would have invalidated the
  note silently. The note now says which firmware it describes.

  Written from the seven real `*IDN?` replies rather than from the SCPI
  standard, because two of them do not follow it — the 2401's fourth
  field is a firmware revision with a build date welded on, and the
  U2722A's starts with an `R`. A parser expecting a bare dotted version
  would have dropped both, which are the two oldest instruments on the
  bench.

- **`tools/timing_scan.py` now checks that its readings are readings.**
  It called `measure()`, discarded the result and timed the call, so a
  `(None, None)` was timed exactly like a measurement. That is how it
  reported 10.3 ms flat across a thousandfold NPLC change on the
  GSM-20H10, fitted a straight line through it, and printed a
  conclusion that the driver's declared aperture was "6493x too long" —
  from a run where the output was never energised. The checkup, same
  instrument and same NPLC, measures 75.2 ms.

  It now counts blanks and refuses to fit when any turn up: a timing
  figure taken from failed reads is worse than no figure.

- **And it reports noise, not just time.** A reading can come back in
  the same wall-clock time whatever the NPLC — a free-running
  conversion, a cached value — so timing alone cannot tell an
  instrument that integrates from one that ignores the request. A
  genuine 10 PLC reading is roughly thirty times quieter than a 0.01
  PLC one. If the scan finds a longer integration that is not quieter,
  it says so plainly: the NPLC setting on that instrument is decorative
  and every file records an integration time it may not have got.

Six deliberate mutations, all caught.

## RangePlan: an axis that is not being sourced is not the same as AUTO

The fix the 2026-08-18 commissioning round was gathered for.

`RangePlan.for_sourcing()` put `AUTO` on the source axis of the
quantity a run is *not* sourcing. `AUTO` asks the instrument to choose
a range; the intent was "nothing is coming out of this axis, so there
is nothing to choose". Drivers could not tell the two apart.

Across the whole bench that was harmless on most and damaging on two,
in opposite directions — the GSM-20H10's compliance collapsed to
the instrument's floor, and the U2722A's became unsettable, failing
four checks including the sweep. On the 2611A and 2635B the same axis
is the compliance's *own* range and must keep being sent, which is why
a blanket rule would have broken one pair to fix the other.

- **`NOT_SOURCED`**, a sentinel distinct from `AUTO`.
  `BaseSMU._render_not_sourced` turns it back into `AUTO` by default,
  so the five unharmed instruments keep the behaviour they were
  commissioned with, and only a driver checked at the bench overrides
  it. `renders_not_sourced` in the contract ledger records which, with
  the reason beside it — a `False` there means the default was
  verified harmless on that model, not that nobody looked.
- **`RangePlan.widest()`**: an axis carrying nothing no longer wins a
  shared knob. That, rather than any driver change, is what fixes the
  U2722A — the current range now follows the compliance instead of
  going to the instrument's widest.
- **GSM-20H10** sends nothing at all on that axis.
- **A U2722A driver override was written, passed its tests, and was
  then found unreachable by mutation** — `INDEPENDENT_SOURCE_RANGE` is
  False there, so `widest()` resolves the marker before any hook sees
  it. Removed, with the reason left in its place: a hook that looks
  load-bearing and never runs is worse than no hook.
- One new test guarding the shared-knob path was **vacuous on its first
  mutation round** — it asserted a hook never receives the raw marker,
  which `_render_not_sourced` guarantees regardless of the
  reconciliation. Rewritten to assert the *value* the hook receives.
  Fault 19, in a test written to guard against that class of thing.

Seven deliberate mutations, all caught after the two corrections above.

Still open, and deliberately a separate wave: `apply_ranges` reports
what it *sent* rather than what the instrument accepted, and the
checkup has no "does the compliance survive ranging" check. Both need
`read_current_limit()` / `read_voltage_limit()` on `BaseSMU` with a
ledger entry per driver. Five of the seven "0 failures" above are
"none observed", not "none" — nothing read a compliance back, and the
GSM's collapse raised no error either.

## GSM-20H10 commissioning: what the 2026-08-20 bench session found

Six checkup failures on 2026-08-18, none on 2026-08-06. The window
between them is where `RangePlan` entered the checkup.

- **`tools/smu_checkup.py` applied limits before ranges** — the order
  fault 15 exists to prevent. On the GSM-20H10 that cost three of the
  six failures and took tier 3 with them: the instrument would not
  energise afterwards, so `measure()` returned `(None, None)` and the
  readings, the sweep and the timing figure all failed behind it.
  Reordering took the instrument to three failures with tier 3 green —
  `measure()` returning `(0.1000629, -8.5e-09)` at 0.1 V, compliance
  trips reported correctly, and 75.2 ms per reading at NPLC 0.01. No
  measurement was ever at risk: every experiment already ordered it
  correctly. The tool was producing a failure the application cannot
  produce, and a cascade behind it.

- **A source-autorange command silently resets the compliance.** One
  command, no error: `SOUR:CURR:RANG:AUTO ON` takes the current
  compliance from 105 µA to **1 nA**, and `SOUR:VOLT:RANG:AUTO ON`
  takes the voltage compliance from 21 V to **200 µV**. Repeatable, in
  both source functions. Written up as fault 23. The two error codes
  that led us there — `+824 Cannot exceed compliance range` and `+826
  Attempt to exceed power limit` — are *consequences* of the collapsed
  compliance landing on innocent commands, which is why `+826` fired on
  a microwatt and never made sense.

  Runs survive it only because fault 15's ordering puts the
  experiment's own compliance after the ranging block. That recovery is
  accidental, not designed.

- **`RangePlan`'s `AUTO` means two different things**, and the second
  one — "I am not sourcing this quantity" — is what emits that command.
  On the U2722A the same construct instead wins a shared-knob
  reconciliation and costs an order of magnitude of resolution. One
  construct, two unrelated harms, on every instrument examined so far.
  Recorded in `docs/open/technical-debt.md` rather than fixed: a rule
  designed from the instruments looked at so far would very likely turn
  the rest into exceptions, so the remaining checkups are being
  gathered first.

- **Three other things the instrument does**, all now in its note:
  a measurement range can be refused and silently narrowed, with
  `apply_ranges` reporting what it *sent* rather than what was
  accepted; `OUTP?` and `OUTP:STAT?` return 0 with the output
  physically on and 10 V flowing; and setting the measurement range of
  the *sourced* quantity is refused by name with `+823 Invalid with
  source read-back on` — the instrument confirming that the axis
  `RangePlan.for_sourcing()` makes unrepresentable really is
  unrepresentable.

- **First manual extracts in the repository.**
  `docs/reference/manuals/` was advertising itself as empty. It now
  holds the GSM-20H10 factory-defaults table and the `:OUTPut`,
  `:SOURce:CLEar`, `:INITiate` and `:ROUTe:TERMinals` entries. The
  defaults table is what identified `OUTP:ENAB` as already disabled at
  reset, killing a hypothesis that had already cost two bench runs.

- **`test_a_pages_content_does_not_depend_on_when_the_code_last_moved`
  had hardcoded dates that rotted.** It simulated commit dates of
  2026-08-15 and 2027-03-01, chosen when the newest `last_bench` in the
  repo was 2026-08-14. A bench session on 2026-08-20 put a checkup date
  between them, so one render was stale and the other was not, and the
  test went red on correct data. The dates are now derived from each
  note, and it checks *every* qualifying note rather than whichever
  sorted first.

Three faults were proposed and disproved before the real one: the
rear-panel interlock, source auto-clear, and an ambiguous channel
suffix on `:OUTPut`. Each was written from a plausible mechanism rather
than from a probe, and one reached the instrument note as a statement
of fact before being retracted. Fault 19 is about probes; it applies to
hypotheses too.

## Fixed sourcing vs time: the last sample, and the clock ceiling

Windows CI, after the merge. A well-behaved eleven-sample run returned
ten; Linux could not reproduce it.

- **The clock ceiling was pre-empting the sample due at exactly the
  duration.** That sample is inside the window the operator agreed to,
  but any lateness in the final wait puts elapsed past the ceiling
  before it has been taken. Windows' default timer granularity is about
  15.6 ms, so a 10 ms final wait overshoots by 5 ms — enough. The run
  looked healthy, was one sample short, and sat well inside the
  shortfall floor that would otherwise have refused it.
- **The ceiling now has a grace of one interval**, so a run may exceed
  its requested duration by up to one interval. That is the stated cost
  of not dropping the final sample, and it does not weaken what the
  ceiling is for: a run a whole interval behind the agreed window is the
  runaway case and is still stopped there.
- This is the float-division fault from the previous entry arriving
  through a second door — a comparison sitting exactly on a boundary,
  and the last sample of a healthy run quietly vanishing. Both are fixed
  by deciding what the boundary is *for* rather than by nudging a
  number.
- Two regression tests, deliberately not timing-dependent: one makes a
  single reading slow enough to put the clock past the duration before
  the final sample is due, reproducing the Windows shape on any
  platform; its pair asserts that the grace did not become an amnesty
  for a runaway run. The second's bound is derived from the stated
  contract rather than picked — a rounder one survived the mutation that
  widened the grace.

## Fixed sourcing vs time

The first experiment in this suite that is not a port. It holds one
source level and samples the other quantity against the clock —
leakage, bias stress, relaxation, self-heating — and it is the first
whose independent variable is time.

- **No driver changed.** Everything it needs was already on `BaseSMU`:
  `measure()` returns both quantities on every registered driver, so the
  experiment sits entirely on the existing contract. That was checked
  before the design was agreed rather than discovered afterwards.
- **Duration is authoritative and the loop is bounded by the clock**,
  not by its position on the nominal grid. The timer exists so nobody
  walks away from a live fixture, so a slow instrument must deliver
  fewer samples in the same window rather than the same samples over a
  longer one. A 60 s run at 5 ms on a 50 ms instrument would otherwise
  have held the output on for ten minutes.
- **`RunContext.expect()` cannot be used here** — an exact expected
  count would fail every honest run on a slow instrument. A conditional
  floor replaces it: half the nominal count for a run that reached its
  duration, two samples for one the operator ended or a read error cut
  short.
- **Two stop controls, because they are two operations.** "Finish and
  save" commits what was collected; "Stop and discard" is the house
  Stop, unchanged. Stop keeping its meaning is the load-bearing half —
  an operator who has pressed it a hundred times on Van der Pauw must
  not lose a run discovering it means something else here. Neither
  button talks to the instrument; both set a flag and the worker
  de-energises on the thread that owns the session, which is the
  discipline W6-2 established.
- **The time column is measured and the schedule aims at absolute
  deadlines.** `i * interval` would be
  [Reconstructed x-axes](docs/faults/09-reconstructed-x-axes.md) in a new place, and sleeping the
  interval between readings would be
  [Sweep completion slept rather than polled](docs/faults/05-slept-not-polled.md) in a new place. Late samples
  are counted and the achieved mean interval is stored beside the
  requested one.
- **A float-division fault, found while writing the tests.**
  `0.3 / 0.1` is `2.9999999999999996`, so a plain `int()` gave three
  samples where four were asked for and the sampling loop dropped the
  one due at t = 0.3. A 60 s run at 0.1 s lost its last sample the same
  way. Both the loop and the nominal count now carry a tolerance — and
  the reason it survived a first reading is that the two disagreed by
  computing the same wrong division, so they agreed with each other.
- **`tools/build_docs.py` no longer asserts that every experiment is a
  port.** The template said "Ported from `<origin>`" unconditionally,
  which rendered as "Ported from `New experiment`" — the generator
  making a false claim, which is the thing the generator exists to
  prevent. Non-port origins now render honestly.
- 26 new tests across `tests/test_fixed_source.py` (what the run
  records) and `tests/test_fixed_source_lifecycle.py` (the threaded
  route, and the two stop controls at the same boundary). 22 deliberate
  mutations run against them; the first round left four survivors —
  two real holes in the tests, two mutations shaped so they could not
  fail, which is the same fault as a test that cannot fail.

**Not commissioned.** Nothing here has met hardware. The first bench
session is expected to find something; commissioning a new path always
has.

## Wave 7g

- `uv.lock` regenerated. Wave 7e added `[build-system]` to make the
  project installable, which changes how uv classifies the project
  itself - `source = { virtual = "." }` became
  `source = { editable = "." }` - and the lockfile was never rebuilt.
  CI runs `uv sync --locked`, so both jobs failed at the first step with
  an error naming neither what had changed nor why.
- `tests/test_lockfile.py` holds `uv.lock` to `pyproject.toml`: the
  project name and version, the dependency list, the Python floor, and
  whether the project is a buildable package at all. Deliberately
  offline - `uv lock --check` would be complete but needs an index, and
  a suite that cannot pass without the network is one that fails on a
  bench machine for reasons unrelated to the code.
- It catches a dependency added or removed, a version bumped, the floor
  moved, or a build backend introduced. It cannot catch an upstream
  package changing its own requirements; `--locked` in CI still covers
  that.

## Wave 7f

A fix to Wave 7c, found by Windows CI.

- `lock_directory()` created what it returned. A function named for a
  question had a side effect, so *asking* where the lock lives made
  directories - for every caller, including `default_log_path()` in
  `core/event_log.py`, which meant constructing an `EventLog` or
  printing a diagnostic created a tree nobody asked for. It is now a
  pure query; `SingleInstance.acquire()` creates what it needs, as
  `EventLog.record()` already did.
- On Linux this was invisible: the directories were real, writable and
  unremarked. It took a Windows job, and a path under `C:\Users` whose
  ACL refuses `mkdir`, to turn a silent side effect into a
  `PermissionError` - which is what "Windows CI is load-bearing" means
  in practice.
- The test that exposed it named a real system location it did not own
  (`C:\Users\test\AppData\Local`) instead of `tmp_path`. Corrected,
  and `test_asking_where_the_lock_lives_creates_nothing` now guards
  both halves: the query creates nothing, and acquiring still does.

Review issues: none.
- `lock_directory()` takes `platform`, `environ` and `home` so both
  branches run on either operating system. This is the more important
  half: the fault reached CI because the only test of the Windows
  branch opened with `if sys.platform != "win32": skip`, so on the
  machine where the code was written it never ran at all. A branch that
  can only be tested on the platform you cannot run is a branch nobody
  tests. There are no skips left in that file.
- Mutation testing then found a second hole, in both writers. With
  `mkdir` moved out of the query, `SingleInstance.acquire()` and
  `EventLog.record()` each have to create their own parent - and every
  test handed them a `tmp_path` that already existed, so deleting those
  lines broke nothing. That is the first-run path on every bench
  machine. For the event log it would have been silent: `record`
  swallows its own errors by design, so the symptom would have been a
  log that was simply always empty.

## Wave 7e

Packaging (§42), and the close of the wave numbering.

- `[build-system]` added: the project can be built and installed. Before
  this, `import core` worked only when the working directory happened to
  be the checkout, so §42's acceptance criterion failed at *import* -
  several steps before it reached a resource file. Verified end to end:
  installed into a clean 3.14 environment, imported from `/tmp`,
  resolving to `site-packages`, with the 4PP diagram present.
- Layout stays flat. A `src/` layout stops the source shadowing the
  installed copy, which matters for a library and much less for an
  application with one entry point - and an *editable* `src/` install
  would not have caught a missing data file anyway. Checking the built
  artifact does; `tests/test_build_artifact.py` does that.
- `tests/test_build_artifact.py` enumerates non-Python files from the
  tree and requires each in a genuinely built wheel, so a new image is
  covered when it is added rather than when somebody remembers a rule.
  The declared package list is checked against the tree too.
- The first build configuration carried `artifacts = ["**/assets/**"]`
  with a comment asserting it was essential. It did nothing - that key
  is for files version control excludes, and the asset was already
  included. Mutation testing found it; the line is gone and the
  reasoning is in `docs/workflow/packaging.md`.

Review issues: §42.
- The launcher body moved to `core/launcher.py` and `main.py` became a
  shim that calls it. `pyproject.toml` declares a console script,
  `smu-lab-suite`, so after `uv pip install -e .` the application opens
  from any directory - which is what "ship it as an `.exe`" was mostly
  asking for, without bundling an interpreter or making a second copy
  of the repo that `git pull` cannot update.
- The entry point names `core.launcher`, never `main`: a console script
  target must be importable, and a top-level `main` module in
  site-packages collides with every other package's idea of that name.
  Both properties are tested, and the target is resolved the way an
  installed script resolves it rather than pattern-matched.

## Wave 7d

Operational event log (review §26).

- Every run now leaves a record of how it ended - completed, cancelled
  or failed - in a JSON Lines file in per-machine state. Previously a
  cancelled run's only trace was a console line that vanished with the
  window, so "nothing was saved" and "somebody stopped it because the
  probe slipped" were indistinguishable afterwards.
- **It records that a run happened, never what it measured.** §26's
  boundary; guarded by a test that puts a distinctive value in a run's
  readings and asserts it appears nowhere in the log, so a leak through
  any field - including one added later - goes red.
- One line per run, not per state transition: a run is the unit of
  investigation, and transitions are already on the operator console.
- JSON Lines rather than CSV, because the field list will grow. A new
  key is invisible to an old reader; a new CSV column shifts everything
  after it, which is the shape of the Wave 4 sentinel fault.
- Wired at `RunController._record`, the single choke point every
  terminal status passes through, so a future terminal path cannot skip
  logging. The controller takes a *callable*, not a path, so run control
  keeps no dependency on the filesystem.
- A log that cannot be written never fails a run: it complains once to
  the console and stays silent thereafter.
- Two defects found by the new tests, both silent: the parameter
  fingerprint used `repr()`, which renders an ordinary object as its
  memory address, so two identically configured runs produced different
  digests - a field full of plausible hex that answered nothing. And a
  line torn by a power cut would have had the *next* run's event glued
  onto it, losing both.
- Stored beside the single-instance lock in per-machine state rather
  than beside the application: a frozen `.exe` under `Program Files`
  sits where ordinary users cannot write, and one on a shared drive
  would pool every bench's runs into one file.

Review issues: §26.
- `test_no_reading_value_reaches_the_operational_log` was rewritten
  after a mutation round: the first version defined a marker value,
  never put it anywhere the log could reach, and then checked the file
  did not contain it - true whether or not the code was correct. It is
  now two tests, for two different properties: readings are cleared
  before the sink is called at all, and parameters are fingerprinted
  rather than transcribed.

## Wave 7c-ii

- Only one copy of the application may run per machine. `main.py` takes
  a lock before building any window and refuses with a dialog
  otherwise. Two copies would each open the same instruments and each
  believe it controlled the output state.
- The lock is held by the **operating system** - `msvcrt.locking` on
  Windows, `fcntl.flock` elsewhere - rather than being a file whose
  existence means "running". The OS releases it when the process ends
  however it ends, so a crash or a kill cannot leave the bench locked
  out of its own software. `tests/test_single_instance.py` proves that
  by killing a holder outright.
- The lock file lives in per-machine state (`%LOCALAPPDATA%`, or
  `$XDG_STATE_HOME`), never beside the application: advisory locks over
  SMB and NFS are unreliable, and a lock beside an application on a
  shared drive would be shared between benches.
- Consequence worth knowing at the bench: a second copy is refused even
  when it would have driven a different SMU.

Review issues: none directly; prerequisite for §26.

## Wave 7c-i

- `run_tests.py` passes `PYTHONDONTWRITEBYTECODE=1` to every pytest
  subprocess. CPython validates a cached `.pyc` on the source's mtime
  and size, so a same-length edit inside one mtime tick leaves stale
  bytecode running - which silently invalidates mutation testing, the
  technique most of this project's real defects were found by. Cost
  three mutation rounds in Wave 7b before it was spotted.
- `tests/test_bytecode_staleness.py` demonstrates the mechanism rather
  than trusting it, pinning both mtimes with `os.utime` so the
  condition is reproduced deterministically.

Review issues: none.

## Wave 7b-ii

Save semantics: option A, immutable snapshot, made legible on disk.

- Every stored file declares `schema` (`core.run_store.FILE_SCHEMA`, now
  1) and `app_version`, plus `save_kind: snapshot` and a `save_id`
  shared by every file one press of Save writes. Combining two
  snapshots is `drop_duplicates(subset="record_id")`.
- `core/version.py` is the single source of truth for the application
  version; `pyproject.toml` mirrors it and `tests/test_version.py`
  fails if they drift. Not read from packaging metadata:
  `importlib.metadata` needs an installed distribution, and neither a
  checkout nor the intended frozen `.exe` is one.
- The Save button reads **Save snapshot → CSV** in all four
  experiments, and the confirmation says the runs stay in the table.
- Option B - export only new runs - was rejected and the reasoning
  recorded in house rule 3: the `#` header carries calculated results
  derived from every run in the store, so a new-runs-only file would
  state a sheet resistance computed from readings it does not contain.
- `tests/test_shared_controls.py` found the header row by position
  (`splitlines()[5]`); it now finds it by content. Four new header
  lines would have aimed it at a `#` comment, where each `in` check is
  trivially false.

Review issues: §25.

## Wave 7b-i

Run identity, ahead of the save-semantics change that needs it.

- The IV sweep bound each stored run to whatever the sample-name box
  said when the *sweep finished*, read from the worker thread. Retyping
  the box mid-run re-filed the remaining sweeps, and a periodic run
  could split its cycles across two samples with nothing logged. It now
  captures a frozen `SampleRef` at the Run press, like the other three
  experiments, and records `run_id`, `sample_id` and `sample_label`.
- `Run` mints its own `record_id`, written as the first CSV column.
  `run_id` identifies a lifecycle run and `record_id` a stored row -
  not the same thing, because one periodic IV run commits several
  records sharing a `run_id`. De-duplicating on `run_id` would delete
  real cycles.
- `tests/test_iv_identity.py` adds the thread-affinity check the IV
  sweep alone never had; 4PP has had one since Wave 3.

Review issues: §17, §25.

## Wave 7a

Tooling guards, ahead of the persistence work. No production code.

- `tests/test_docs.py`: every Markdown table must have a header, a
  separator and at least one body row, with square columns. `plan.md`'s
  status table had been truncated to a header and a bare `|` since the
  documentation rebuild, and rendered as an empty grid rather than as
  damage.
- `tests/test_docs.py`: `plan.md`'s "complete through Wave N" is checked
  against `CHANGELOG.md`'s wave headings, so the status line cannot fall
  behind the work by omission.
- `tests/conftest.py`: a GUI test whose dialog recorder has been stolen
  by another test file in the same process now fails, instead of passing
  its absence-of-dialog assertions against a recorder nothing writes to.
- `docs/plan.md`: status restored, Wave 7 split into 7a-7e, and both
  open decisions recorded as answered - save semantics A, and no second
  instance.

Review issues: none directly; §25 and §26 scoped.

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
