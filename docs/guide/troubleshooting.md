---
type: guide
title: "Troubleshooting"
---

# Troubleshooting

Symptoms first, with the usual causes and what to do. When the suite
refuses something it says why in a message. Those messages are worded to
be acted on, and are worth reading in full before looking here.

## Starting and connecting

**The suite does not start.** A failed start says so in a dialog, with
details in `%LOCALAPPDATA%\SMUniversal_Lab_Suite\launcher.log`. Running
`uv sync` in the suite's folder repairs an incomplete install. See
[Getting started](getting-started/index.md#if-it-will-not-start).

**The measurement cards are greyed out.** Another measurement window
already holds the instruments. Close it with its own close button. Only
**Plot saved data** stays available meanwhile.

**The instrument is not in the address list.**

- Check that it is switched on, then press **Refresh**.
- Check the **Connection** matches how it is attached. The GPIB
  instruments use **VISA**. The Keysight U2722A, if it goes missing, uses
  **VISA (pyvisa-py)**. The miniSMU must use **miniSMU**, not Serial.
- On a laptop without National Instruments' GPIB software, a GPIB
  instrument needs **NI GPIB-HS**: see
  [Connecting a GPIB instrument from a laptop](instruments/index.md#connecting-a-gpib-instrument-from-a-laptop).
- Tick **All addresses** to see everything the scan found, including
  ports that are not instruments.
- Run `uv run tools/visa_doctor.py` in the suite's folder. It says why an
  instrument cannot be seen.

**"Connection failed" or "Unrecognised instrument".** Nothing answered at
that address, or something answered that the suite does not recognise.
The dialog offers **Run demo instead** or a driver to choose by hand.
Choose one by hand only if you know what is on the other end.

**"Wrong instrument for this tab".** The instrument answered, and it
cannot do this measurement. The electronic load, for example, cannot
run Van der Pauw, Hall or the four-point probe, because it cannot source.
The [Instruments](instruments/index.md) table shows what runs where.

**The miniSMU connects, then every command fails.** It was connected as
**Serial**. Disconnect, set the connection to **miniSMU**, and connect
again.

## Running

**Run is refused before anything switches on.** The settings ask for
something the connected instrument cannot do, or something that does not
make sense. The message names it. Common ones:

- a level or compliance outside the instrument's limits, including its
  power limit at high voltage;
- on the Keysight U2722A, a compliance below 100 nA or between 10 mA and
  12 mA, or a level too small for it to source;
- on Van der Pauw and Hall, a sweep that does not cross zero: one end
  of it has to be negative and the other positive;
- on the Keysight U2722A, a Van der Pauw or Hall sweep through zero at
  all: it cannot source the small currents near zero. Use two points at
  ±75 µA or more, or another instrument;
- on the 4-point probe, a long side **L** shorter than the short side
  **W**, or an odd number of reversals above 1;
- a thickness or current that could not be read. Type units as shown,
  such as `100u`, `100 µA` or `180 nm`.

**The output will not turn on above about 20 V (Keithley 2611A or
2635B).** Their 200 V range needs the interlock line held. See the
instrument's page under [Instruments](instruments/index.md).

**The run is flagged for compliance, or the curve goes flat.** The
instrument hit the limit you set, and the flat part is the limit, not
the sample. Raise the compliance, if the sample tolerates it, or narrow
the sweep. On the miniSMU, a curve that flattens at about 50 mA with no
compliance set there means it is on USB power: plug in its 12 V adapter.

**Readings are noisy.** Raise the integration time (**NPLC**). 1 NPLC
averages over a whole mains cycle and cancels mains hum. Check the leads
and contacts too: noise that changes as a lead is moved is the wiring.

**Each point looks like the one before, or a sweep lags.** The sample or
leads have not settled before each reading. Raise the delay. This is
most common on high-resistance samples and on the Keysight U2722A.

**The first reading of a run is slow.** That is normal on most
instruments after a change of settings, and on the Keithley 2635B it can
take over half a second.

**Stop threw my data away.** Stop cancels and discards, in every window.
On Fixed sourcing vs time, **Finish and save** keeps what has been
collected. On a periodic IV run, let the current cycle finish rather than
pressing Stop.

## Results and calculations

**Copy ticked → Calc refuses.** It needs exactly the right runs ticked:

- **Van der Pauw:** one run at position A and one at B.
- **Hall:** C and D, each at + and − field.
- **4-point probe:** exactly one run.

Tick with the box at the left of each row.

**Take Rs from VdP refuses.** The Van der Pauw tab has not been
calculated yet, or something it was calculated from has changed since:
its runs, thickness or sample name. Press **Calculate** on the Van der
Pauw tab again. The sheet resistance can only come from the same window
session.

**A result disappears or is marked stale.** An input changed after it was
calculated. Press **Calculate** again. A stale result is never saved.

**The Hall carrier type is the opposite of what the sample should be.**
The most likely causes are a swapped pair of contacts, a switch-box
position that did not match the one selected in the window, or a field
direction entered the wrong way round. The window cannot see the switch
box or the magnet, and records what you selected.

**The same sample reads differently on different days or instruments.**
Open both files in **Plot saved data** and compare their settings on the
**Compare** tab. Integration time, 2- or 4-wire sensing and compliance
explain most differences. Then measure a known resistor on both: see
[Getting started](getting-started/index.md#your-first-measurement-a-known-resistor).

## Saving and files

**Nothing was saved.** Nothing saves automatically. Press **Save
snapshot → CSV**, and closing a window with unsaved runs asks first. Files
go into a folder named for today's date inside the one chosen with **Save
path...**.

**A file will not open in Plot saved data.** It is listed with the
reason, and the rest still open. Only files saved by the suite can be
read.

**A saved file needs explaining.** Every column is described in
[Reading your data](good-data/reading-your-data.md).

## Help in the window

**No hover help appears.** Tick **Show tooltips**, top right of the
window. Help appears when the pointer rests on a control, not while it
moves.
