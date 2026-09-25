---
type: guide
title: "Van der Pauw + Hall"
---

# Van der Pauw + Hall

Two measurements on one mounted sample, in one window with a tab each.
**Van der Pauw** measures the film's sheet resistance from four contacts
at its edges. **Hall** then puts the sample in a magnetic field and
measures the carrier density, mobility and carrier type, using that sheet
resistance. Run them in that order, on the same mounting, in the same
session: the sheet resistance passes from one tab to the other inside
the window, not through a file.

![The Van der Pauw tab after positions A and B and a calculation](../../assets/screens/vdp_hall/window-van-der-pauw-light.png#only-light)
![The Van der Pauw tab after positions A and B and a calculation](../../assets/screens/vdp_hall/window-van-der-pauw-dark.png#only-dark)

## What it can run on

Any SMU the suite knows, with one exception and one limitation:

- **The electronic load** cannot run it, since it can only sink current,
  and it is refused at Connect.
- **The Keysight U2722A cannot sweep through zero.** On its widest range
  it will not source below about 73 µA, because below that it cannot
  command the sign of its output. So the default sweep is refused before
  anything switches on. It can still take the two-point form: set
  **Points** to `2` and the sweep to at least ±75 µA, and it measures
  once at −I and once at +I. Any other SMU gives you a proper sweep.

See [Instruments](../instruments/index.md).

## The sample and the switch box

Four contacts at the edges of the film, wired to the SMU through a
**switch box**. The box chooses which contacts carry the current and
which sense the voltage, and has four positions, labelled on the box:

| Box position | Used by | What it measures |
|---|---|---|
| **A** (VdP 1) | Van der Pauw | the horizontal resistance |
| **B** (VdP 2) | Van der Pauw | the vertical resistance |
| **C** (Hall 1) | Hall | current along one diagonal, voltage across the other |
| **D** (Hall 2) | Hall | the two diagonals the other way round |

The suite cannot see the box, so **you set it by hand, and tell the window
which position it is in**. The contact diagram above the position buttons
is drawn as the box is: the current contacts (Hi and Lo) in orange and the
sensing contacts (Sense Hi and Sense Lo) in green. Check it against the box
before every run.

**Thickness and sample name** sit in the strip across the top of the
window and are shared by both tabs. Type the thickness with its unit
(`180 nm`, `1.5 µm`); a bare number is read as nanometres.

## Each run is a sweep

A run sweeps the current from **Start** to **Stop**, like the IV sweep,
reading the voltage at each point. The sweep has to cross zero, and the
default is −1 µA to +1 µA in 80 points, 100 ms per point. Its negative and
positive halves are the two current polarities: averaging them cancels
the contacts' thermoelectric offsets, which is what reversing the current
is for. Both calculations take the halves exactly as they took the two
polarities before, so none of the arithmetic changed.

## Van der Pauw: the sheet resistance

1. **Connect** the SMU (see [Every window](every-window.md#the-usual-order)).
2. **Check the setup**: the sweep (typed with units: `-1u` to `1u`), the
   voltage limit **VLIM**, the points and the delay per point.
3. **Position A.** Set the switch box to A, select **A** in the window,
   and press **Run**.
4. **Position B**, the same way. You need both: A gives the horizontal
   resistance and B the vertical one. The box has no separate settings
   for the two reversed arrangements the old scripts also measured,
   because swapping current and voltage contacts gives the same
   resistance.
5. **Tick the two runs** and press **Copy ticked → Calc**. It takes
   exactly one run at A and one at B, and refuses anything else.
6. **Press Calculate.** The sheet resistance (Ω/□) and, with the
   thickness, the resistivity appear.

**Reading the runs.** Each run is plotted as its sweep, voltage against
current, with a straight line through it. The slope is the resistance,
and the table shows it as **R(fit)** beside the average of the two halves,
**R(ave)**. On a good ohmic contact the two agree closely. A sweep that
bends, or points that scatter off the line, means that position's
contacts are suspect: re-seat and run it again before copying it.

![The Hall tab after the four field and position combinations](../../assets/screens/vdp_hall/window-hall-effect-light.png#only-light)
![The Hall tab after the four field and position combinations](../../assets/screens/vdp_hall/window-hall-effect-dark.png#only-dark)

## Hall: carrier density and mobility

Hall uses the two diagonals, positions **C** and **D**, at both
directions of the magnetic field. That is four runs: C and D, each with
the field **+** and **−**.

1. **Switch to the Hall tab.** The instrument, sample name and thickness
   come with you.
2. **Check the sweep** in the setup panel, as on Van der Pauw.
3. **Position C, field +.** Set the switch box and the magnet, select
   **Pos C** and **+**, and press **Run**.
4. **The other three combinations:** C with −, then D with + and with −.
   The window records the field direction you selected with each run. It
   cannot see the magnet, so what you select is what the calculation
   believes.
5. **Tick the four runs** and press **Copy ticked → Calc**. It takes
   exactly C and D at + and −, one run each.
6. **Fill in the rest of the calculation.**
    - **B (T):** the magnetic field. It starts at this lab's magnet,
      0.487597 T; change it if the field is different.
    - **Take Rs from VdP:** fills the sheet resistance from the Van der
      Pauw tab. It refuses if that calculation is out of date, and warns
      if the stage temperature has moved since.
    - **I (A):** leave it empty to use the sweep's mean current, which is
      what the averaged voltages belong to. Type a value only if the
      source was clamped and you know the real current.
    - **Sample type:** *Thin film* reports carriers per cm², *Bulk* per
      cm³.
7. **Press Calculate.** You get the Hall voltage, carrier type, carrier
   density, mobility and resistivity.

The **Hall V-I** plot under Run and Stop shows the ticked runs' sweeps with
their lines, so a noisy or clamped run is visible before its voltages are
copied.

**Check the carrier type against what you expect.** It comes from the
sign of the Hall voltage, and a flipped sign is exactly what a swapped
pair of contacts looks like. It is the cheapest check there is on a Hall
run.

**Keep the current below compliance.** The Hall voltage is a small
difference between two large readings, so a clamped reading ruins it
more than it would a resistance. If a run reports that it hit **VLIM**,
narrow the sweep or raise the limit and run it again.

## The panels

<!-- generated:controls vdp_hall -->
The controls every window has - in the Header strip, Instruments, Run controls, Results and Plot panels - are described once, on [Every window](every-window.md). What follows is this window's own.

### Sample and saving

![The Sample and saving panel](../../assets/screens/vdp_hall/sample-and-saving-light.png#only-light)
![The Sample and saving panel](../../assets/screens/vdp_hall/sample-and-saving-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Sample name** | The sample on the stage. It names the saved files and identifies the sample to every check in the suite, so two different coupons must never share a name - a result from one would be carried over onto the other. |
| **Thickness** | The film's thickness, with a unit: 100 nm, 1.5 µm, 2 mm. A bare number is read as nanometres. It turns a sheet resistance into a resistivity, so a wrong value scales that result directly. |
| **Next #** | The number the next saved measurement will carry in its file name. It counts up by itself on every save; it is not typed. |
| **Save path...** | Choose the folder to save into. A subfolder named for today's date is made inside it, so one folder holds a day's work. |
| **Save folder** | Where this session's files are being saved - today's dated folder inside the one chosen with Save path. |

### Tabs

![The Tabs panel](../../assets/screens/vdp_hall/tabs-light.png#only-light)
![The Tabs panel](../../assets/screens/vdp_hall/tabs-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Tabs** | Two measurements on one mounted sample, sharing its name, thickness, stage and instrument. Van der Pauw first, for the sheet resistance; Hall takes it from there. One tab measures at a time. |

### The Van der Pauw tab

#### Contact diagram

![The Contact diagram panel](../../assets/screens/vdp_hall/van-der-pauw-contact-diagram-light.png#only-light)
![The Contact diagram panel](../../assets/screens/vdp_hall/van-der-pauw-contact-diagram-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Contact diagram** | Which contact does what at the position selected below: the orange corners carry the current, the green ones sense the voltage, and the labels name each role. |

#### Position

![The Position panel](../../assets/screens/vdp_hall/van-der-pauw-position-light.png#only-light)
![The Position panel](../../assets/screens/vdp_hall/van-der-pauw-position-dark.png#only-dark)

Which pair of contacts carries the current and which pair senses the voltage, set on the switch box. Both positions are needed: A gives the horizontal resistance and B the vertical one, and the sheet resistance needs both. The diagram above shows the roles for the position selected here.

| Control | What it does |
|---|---|
| **A** | Switch box position A. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **B** | Switch box position B. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |

#### Measurement setup

![The Measurement setup panel](../../assets/screens/vdp_hall/van-der-pauw-measurement-setup-light.png#only-light)
![The Measurement setup panel](../../assets/screens/vdp_hall/van-der-pauw-measurement-setup-dark.png#only-dark)

What one run does: sweep the current from Start to Stop through the two contacts the selected position makes the current pair, reading the voltage across the other two at each point. The sweep crosses zero, and its negative and positive halves are averaged into one resistance for that position.

| Control | What it does |
|---|---|
| **Start current** | Where the current sweep begins, typed with a unit: -1u, -1 uA or -1e-6. The sweep has to cross zero, so one of Start and Stop is negative. Big enough to lift the voltage clear of the noise, small enough not to heat the film. |
| **Stop current** | Where the current sweep ends, with a unit. Opposite in sign to Start: the readings at negative and at positive current are the two polarities, and averaging them cancels the contacts' thermoelectric offsets. |
| **Voltage range** | The range the voltage is measured on, from what the connected instrument declares. AUTO lets it choose. A range far larger than the reading costs resolution; one too small clips it. |
| **VLIM (V)** | Compliance: the highest voltage the instrument will put across the sample to push the current you asked for. Reach it and it stops being a current source - the run is flagged and you are told when it ends. |
| **Points** | How many currents the sweep steps through, from Start to Stop. Each half of the sweep is averaged, so more points beat down noise and lengthen the run in proportion. |
| **Delay (ms)** | How long to wait at each current before reading it, in milliseconds - time for the sample, the leads and any thermoelectric offset to settle. |
| **Integration (NPLC)** | Integration time, in mains cycles. 1 NPLC averages over a whole cycle and rejects mains hum; 0.01 is twenty times faster and visibly noisier. Two runs at different NPLC are not comparable, so it is recorded with the data. |
| **High-Z output off** | What the instrument does to the sample between runs: open the relay (high-Z) or hold it at zero volts. High-Z leaves nothing driving the film. |

#### Results

![The Results panel](../../assets/screens/vdp_hall/van-der-pauw-results-light.png#only-light)
![The Results panel](../../assets/screens/vdp_hall/van-der-pauw-results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

Besides the controls below, it has the ones every window has - see [Results](every-window.md#results).

| Control | What it does |
|---|---|
| **Results table** | One row per completed run, still in memory and not yet on disk. Click the box at the left to tick a row: ticked rows are what the buttons below and the plot act on. R(ave) is the mean of the two polarities; R(fit) is the slope of the line through all their readings. |
| **Copy ticked → Calc** | Put the four ticked runs' R(ave) into the calculation boxes, one per position, and calculate. Exactly four rows, one per position, or it refuses - three positions still produce a number, just not this sample's sheet resistance. |
| **Save snapshot → CSV** | Write every run in the table to one CSV per sample, with the calculation in its header. Nothing reaches disk until you press this. |

#### Calculation

![The Calculation panel](../../assets/screens/vdp_hall/van-der-pauw-calculation-light.png#only-light)
![The Calculation panel](../../assets/screens/vdp_hall/van-der-pauw-calculation-dark.png#only-dark)

The A and B resistances go in, the sheet resistance comes out. Values copied from ticked runs carry those runs with them into the saved header; typed values do not, and the status line at the bottom says which you have.

| Control | What it does |
|---|---|
| **Pos A (Ω), Pos B (Ω)** | The resistance measured at this switch-box position, in ohms. A gives Rh and B gives Rv. Editing a copied value drops the run behind it, since the number is no longer that run's. |
| **Calculate** | Solve the Van der Pauw equation for the sheet resistance, and multiply by the thickness for the resistivity. The result records which runs it came from and goes stale if any input changes underneath it. |
| **Equations...** | Show the formulas this tab uses, with their symbols named - and, once a calculation is fresh, the same formulas with your numbers in them. |

### The Hall effect tab

#### Contact diagram

![The Contact diagram panel](../../assets/screens/vdp_hall/hall-effect-contact-diagram-light.png#only-light)
![The Contact diagram panel](../../assets/screens/vdp_hall/hall-effect-contact-diagram-dark.png#only-dark)

| Control | What it does |
|---|---|
| **Contact diagram** | Which contact does what at the position selected below: the orange corners carry the current, the green ones sense the voltage, and the labels name each role. |

#### Position (switch box) & B polarity

![The Position (switch box) & B polarity panel](../../assets/screens/vdp_hall/hall-effect-position-switch-box-b-polarity-light.png#only-light)
![The Position (switch box) & B polarity panel](../../assets/screens/vdp_hall/hall-effect-position-switch-box-b-polarity-dark.png#only-dark)

Which diagonal carries the current - set on the switch box - and which way the magnet's field points. The calculation needs all four combinations; the diagram above follows the choice.

| Control | What it does |
|---|---|
| **Pos C** | Switch box position C. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **Pos D** | Switch box position D. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **+, -** | Which way the magnet's field points through the sample, as it is set on the bench. Each run is recorded with it, and the calculation pairs the + runs against the - ones. |

#### Measurement setup

![The Measurement setup panel](../../assets/screens/vdp_hall/hall-effect-measurement-setup-light.png#only-light)
![The Measurement setup panel](../../assets/screens/vdp_hall/hall-effect-measurement-setup-dark.png#only-dark)

What one run does: sweep the current from Start to Stop through one diagonal, reading the voltage across the other at each point. The sweep's negative and positive halves are the two current polarities. One run is one (position, field polarity) pair; four of them - both positions at both field signs - make the eight voltages the calculation needs.

| Control | What it does |
|---|---|
| **Start current** | Where the current sweep begins, typed with a unit: -1u, -1 uA or -1e-6. The sweep has to cross zero, so one of Start and Stop is negative. Big enough to lift the voltage clear of the noise, small enough not to heat the film. |
| **Stop current** | Where the current sweep ends, with a unit, opposite in sign to Start. The mean current of the sweep's halves goes into the carrier density when the I box in the calculation is left empty. |
| **Voltage range** | The range the voltage is measured on, from what the connected instrument declares. AUTO lets it choose. A range far larger than the reading costs resolution; one too small clips it. |
| **VLIM (V)** | Compliance: the highest voltage the instrument will apply to push the current you asked for. Clamping here is worse than elsewhere - the Hall voltage is a small difference between large readings, and a clamped reading is not the sample's. |
| **Points** | How many currents the sweep steps through, from Start to Stop. Each half is averaged, and the Hall voltage is recovered by subtracting nearly equal numbers, so averaging is what makes it measurable at all. |
| **Delay (ms)** | How long to wait at each current before reading it, in milliseconds - time for the sample, the leads and any thermoelectric offset to settle. |
| **Integration (NPLC)** | Integration time, in mains cycles. Longer rejects mains hum and costs time; it is recorded with the data because two runs at different NPLC have visibly different scatter. |
| **High-Z output off** | What the instrument does to the sample between runs: open the relay (high-Z) or hold it at zero volts. |

#### Results

![The Results panel](../../assets/screens/vdp_hall/hall-effect-results-light.png#only-light)
![The Results panel](../../assets/screens/vdp_hall/hall-effect-results-dark.png#only-dark)

The runs of this session, held in memory until saved. Tick a row with the box at its left; the buttons below act on the ticked rows.

Besides the controls below, it has the ones every window has - see [Results](every-window.md#results).

| Control | What it does |
|---|---|
| **Results table** | One row per run: one switch-box position at one field polarity. V+ and V- are the voltages read at +I and -I. |
| **Copy ticked → Calc** | Put the four ticked runs' voltages into the calculation. It takes exactly Pos1 and Pos2 at + and - field, one run each, and refuses anything else rather than half-fill the boxes. |

#### Calculation

![The Calculation panel](../../assets/screens/vdp_hall/hall-effect-calculation-light.png#only-light)
![The Calculation panel](../../assets/screens/vdp_hall/hall-effect-calculation-dark.png#only-dark)

Eight measured voltages in, carrier density and mobility out. P and N are the sign of the magnetic field; swapping the digits in a name (13 against 31) means the current was reversed. The deltas beside them are P minus N, shown for eyeballing: one wildly out of line is usually a contact, not an interesting sample.

| Control | What it does |
|---|---|
| **V13,P (V) ... V42,N (V)** | A measured voltage. V13 is current in at contact 1 and out at 3; V31 the same pair reversed. P and N are the field polarity. Filled by Copy ticked -> Calc, or typed. |
| **B (T)** | Magnetic flux density in tesla, read off the magnet. It multiplies straight into the carrier density, so an error here scales every number below it. |
| **Rs (Ω/□)** | Sheet resistance of this same film, in ohms per square. Take it from a Van der Pauw run on the mounted sample with the button beside this box; typing over it drops that citation and the saved header then says the value was typed. |
| **Take Rs from VdP** | Fill Rs from the Van der Pauw tab's calculation, carrying its result id into this run's saved header. Refused if that result is out of date, and it warns if the stage temperature has moved since. Greyed out in a window with no Van der Pauw tab. |
| **I (A)** | The current the calculation should use, in amps. Left empty it falls back to the mean current of the sweep in the setup panel - the two differ when compliance clamped the source, and then this box is the honest one. |
| **Sample type** | Thin film reports carriers per square centimetre; Bulk divides by the thickness and reports per cubic centimetre. Changing it changes which number you get by a factor of the thickness, and none of the voltages move when it happens. |
| **Calculate** | Average the eight voltages into V_H, then compute carrier type, density, mobility and resistivity. The result records the runs behind it and goes stale if any input moves. |
| **Equations...** | Show the formulas this tab uses, with their symbols named - and, once a calculation is fresh, the same formulas with your numbers in them. |
<!-- /generated:controls -->

## What the saved file tells you

Every column is explained in [Reading your data](../good-data/reading-your-data.md). On these two:

- **Each run records its sweep**: `start_A` and `stop_A`, and every
  reading's commanded current (`level_A`) beside the current and voltage
  measured. `polarity` (Van der Pauw) or `current_polarity` (Hall) says
  which half a reading belongs to. A reading at exactly zero current is
  kept in the file and belongs to neither half.
- **A sheet resistance is only ever computed from complete runs.** A run
  that was interrupted is refused rather than calculated from what
  arrived.
- **Each Van der Pauw run records both R(ave) and R(fit).** On a good
  ohmic contact they agree closely. A large gap between them at one
  position points at that position's contacts.
- **Thickness is saved in nanometres** (`thickness_nm`), however you
  typed it.
- **The Hall file names the Van der Pauw result its sheet resistance came
  from**, by id, so the two can always be matched up. That is also why
  the sheet resistance has to come from the same session: yesterday's
  Van der Pauw cannot feed today's Hall. Re-run it; it takes minutes on
  the contacts you are about to use.
