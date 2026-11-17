---
type: instrument
title: "Multicomp Pro MP710772"
driver_class: MulticompProMP710772
idn: "MP710772 V1.14 SN:0000023205"
idn_confirmed: true
physical: true
maintenance: active

# --- bench facts: hand-written, and the schema requires them -------------
bench_ever: true
last_bench: 2026-11-17
bench_notes: "2026-11-17 checkup at 4e3b56d (14:23) on COM6 with a 5 V supply, writes paced 150 ms: 24 pass, 3 warn, 0 fail, 1 skip. 0.2 A asked, -0.1999 A measured at 5.039 V. The warnings are the missing error queue, the unmeasured headroom floor, and a burst check that answered 10 of 10 unpaced against the declared pause. First checkup at 993d50e (14:07), unpaced and on :FUNCtion: 22 pass, 2 warn, 3 fail. Dialect probe at e81feeb95b7f - checkups/20261117/bench_MP710772_20261117_124656.md"
bench_code: "1849c492b7c0"
bench_result: pass
bench_result_note: null
bench_revalidated: null
reading_time: "about 10 ms per query (probe, 2026-11-17). Two queries per point, and at least 0.5 s settling"
resolution: "0.1 mA on the 3 A ceiling, 1 mA on 40 A (current); 0.1 mV on 18 V, 1 mV on 150 V. From the specification table; three decimals were seen on the 40 A and 150 V ceilings"
best_for: "solar cells and other sources above 3 A, up to 40 A and 500 W - it only sinks, it cannot source"
connection: "USB serial"

# --- generated from code by tools/build_docs.py: do not hand-edit
driver: drivers/multicomp_mp710772.py
model_ids: "['MP710772']"
max_voltage_v: 150
max_current_a: 40
voltage_ranges_n: 2
current_ranges_n: 2
power_envelope_n: 0
sweep_kind: software
nplc_min: null
nplc_max: null
high_z_off: false
ovp: false
ovp_trip: false
remote_sense_control: false
compliance_trip: false
fleet: load
# --- end generated ---
---

# Multicomp Pro MP710772

A 500 W DC electronic load: 0-150 V, 0-40 A. The second load in the
suite after the [72-13200](multicomp-72-13200.md), and the same
maker underneath - both are Korad designs. They share one driver base,
`drivers/korad_load.py`, and this model's file holds only its identity,
its envelope and what was measured on it.

## Why it is here

More current and more power than the 72-13200: 40 A against 30 A, and
500 W against 150 W, at a lower headroom floor - so more of a large
cell's curve is reachable.

## What this means for your data

Everything in the 72-13200's note about measuring a solar cell on a
load applies here, because it is the same kind of instrument and the
same dialect:

- **Isc is not measured**, and **Voc is read with the input off**.
- **The current ceiling sets your noise floor**: 1.35 mA on 3 A,
  18 mA on 40 A. The voltage ceiling likewise: 4.5 mV on 18 V,
  37.5 mV on 150 V. The run picks both from the sweep's own span.
- **A run refuses anything below 0 V, and any CV level below 0.1 V.**
- **Delay is at least 0.5 s a point.**

What differs, as far as is known:

- **It reaches lower voltages at a given current.** At 2 A and 4 A it
  followed the setpoint all the way down to the 0.1 V commanding floor,
  where the 72-13200 stops at 43 mΩ × I. So its saturation resistance
  is at most 25 mΩ. That is a bound, not a measurement, and the driver
  does not refuse anything on headroom grounds until the floor is
  found.
- **Wire it four-wire and switch Remote Comp on** in the front panel's
  Config page (user manual 9.4). Nothing over the bus sets or reports
  it.

## How it was written

**From a probe, not a manual.** Nothing documents its commands. The
documents in `manuals/MP710772/` cover the front panel, the LAN settings
and the USB driver. The one community driver for the family
(mayermakes/lab_UI, `mp71077x.py`) agrees with the 72-13200 everywhere
but the mode, which it sets with `:MODE CC|CV`.

So [`tools/bench_mp710772.py`](../architecture/tools.md#bench_mp710772py--a-dialect-before-there-is-a-driver)
asked the instrument before any driver existed, on 2026-11-17 at
firmware V1.14. Every spelling the driver sends was confirmed there by a
readback that moved from A to B and came back to A. The command table
it found is in [MP710772 command summary](../reference/manuals/mp710772-commands.md).

## What the probe found

**It speaks the 72-13200's dialect.** `:FUNC CV|CC`, read back
with `:FUNC?`, and the screen agreed. The probe used the short header
and waited 150 ms after every write; see the first checkup for why both
matter. `:MODE` - the community
driver's spelling - is ignored in silence and `:MODE?` never answers:
that driver would sweep in whatever mode the front panel was left in.
`VOLT|CURR` is ignored too, as on the 72-13200.

**The same peculiarities, measured again rather than inherited:**

| | |
|---|---|
| Unit suffix | mandatory: `:CURR 0.123` ignored, `:CURR 0.234A` lands; long headers work |
| CV floor | 0.1 V, clamped silently; `:VOLT:LOW?` reports it |
| Ceilings | writable, and a setpoint above one clamps to it; 5 A lands too |
| `*RST` | accepted, changes nothing |
| Error queue | none: `:SYST:ERR?`, `*STB?`, `*ESR?` never answer |
| Input | `:INP 1/0`, `:INP ON/OFF` and `:INPut ON/OFF` all work; screen agreed |
| Sign | a sink reads positive, `00.199A`, against 0.2 A on the supply's display |

**And what is its own:**

- `*IDN?` is `MP710772 V1.14 SN:0000023205` - no brand.
- The USB bridge reports **`0416:5011`, the 72-13200's ids**. The
  address list therefore calls such a port "72-13200 or MP710772" until
  a connect asks `*IDN?`; after that it is named by what answered.
- Readings are **zero-padded** (`05.034V`), three decimals on the 40 A
  and 150 V ceilings. Setpoint and ceiling readbacks carry five digits
  (`40.000A`, `150.00V`).
- About **10 ms a query**, twice the 72-13200.
- `:STATus?` answers `1,4,0,0,0,0`. Undocumented, and unused.
- **`:SYST:DEVINFO?` answers on seven lines.** Read as one, its second
  line became the reply to the next query (`:SYST:BAUD?` "answered"
  `IP:192.168.1.198`), and the rest sat in the buffer until the probe's
  look for stray bytes after a write drained it. The driver never asks
  it.

**Settling**, from a 10 ms poll, to within 2% of the step: CC
0.2 → 1 A 454 ms, 1 → 0.2 A 341 ms; CV 3 → 2 V 354 ms at 2 A and 323 ms
at 4 A. `SETTLING_S` is 0.5 s.

**Headroom**, with a supply current-limited at 2 A and then 4 A and the
CV setpoint walked down: the terminal voltage followed to within 4 mV
all the way to 0.15 V, and stopped at 0.100 V - the commanding floor,
not the headroom one. 0.1 V / 4.027 A puts the saturation resistance at
25 mΩ or less.

## The first checkup

2026-11-17, on the driver as the probe left it, with the 5 V supply
attached (`checkups/20261117/checkup_MulticompProMP710772_20261117_140715.md`):
22 pass, 2 warn, 3 fail.

- **The mode did not take.** `:FUNCtion CC` read back CC, and
  `:FUNCtion CV` straight after read back CC too.
- **A setpoint did not take.** With the input switched on and 0.2 A
  commanded straight after, the load sank 0 A at 5.04 V. Both sink
  checks failed on that one reading.
- **An earlier run that day never finished.** The same mode readback
  disagreed in tier 3, where the checkup let the refusal escape: a
  traceback and no report. The checkup now records it as a failure and
  carries on.

The driver had sent two things the probe never did: the long header
`:FUNCtion`, which only the 72-13200 has been seen to take, and writes
with nothing between them. The probe waited 150 ms after every write
and lost none. So the driver now does both the probe's way:
`FUNCTION_HEADER = ":FUNC"` and `WRITE_DELAY_S = 0.15`. The 72-13200 is
unchanged.

**`:FUNCtion` is ignored on this unit.** Sent by hand in the SCPI
console the same day, `:FUNCtion CV` left `:FUNC?` where it was. Long
headers do work for `:CURRent` and `:INPut`, so on this firmware the
long form has to be confirmed header by header. That accounts for the
mode. It does not account for the 0 A, which is why the pause stays.

**The re-run passed**, paced and on `:FUNC`: 24 pass, 3 warn, 0 fail.
Both modes read back. 0.2 A asked, -0.1999 A measured at 5.039 V. The
burst check answered 10 of 10 unpaced. It grades whether queries are
answered, not whether setpoints land, so it neither confirms the pause
nor rules it out.

## Open questions

1. **Where is the headroom floor?** Below 0.1 V up to 4 A. A sitting at
   10 A or more, where 25 mΩ × I passes 0.1 V, finds it - and two
   currents a factor of two apart make it a resistance, as on the
   72-13200.
1. **How often does the reading refresh?** At 1 mA resolution it did
   not change once in 3 s of polling. The 3 A ceiling, at 0.1 mA, should
   show the refresh in the last digit.
1. **Does the 3 A / 18 V ceiling give the fourth decimal?** The
   specification says 0.1 mA and 0.1 mV there; only the wide ceilings
   were read.
1. **Is the 150 ms pause needed?** The long header explains the lost
   mode. Nothing yet explains the setpoint that sank 0 A in the first
   checkup. A checkup with a shorter `WRITE_DELAY_S`, or none, that
   still sinks 0.2 A says how much of it to keep. It costs that much on
   every sweep point.
