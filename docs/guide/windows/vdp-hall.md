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

![The Van der Pauw tab after four positions and a calculation](../../assets/screens/vdp_hall/window-van-der-pauw-light.png#only-light)
![The Van der Pauw tab after four positions and a calculation](../../assets/screens/vdp_hall/window-van-der-pauw-dark.png#only-dark)

## What it can run on

Any SMU the suite knows. The electronic load cannot run it, since it can
only sink current, and it is refused at Connect. See
[Instruments](../instruments/index.md).

## The sample and the switch box

Four contacts at the edges of the film, numbered 1 to 4 round the edge,
wired to the SMU through a **switch box**. The box chooses which pair of
contacts carries the current and which pair senses the voltage. The
suite cannot see the box, so **you set it by hand, and tell the window
which position it is in**. The contact diagram above the position buttons
shows the roles for the position you pick, with the current pair in
orange and the sensing pair in green. Check it against the box before
every run.

**Thickness and sample name** sit in the strip across the top of the
window and are shared by both tabs. Type the thickness with its unit
(`180 nm`, `1.5 µm`); a bare number is read as nanometres.

## Van der Pauw: the sheet resistance

1. **Connect** the SMU (see [Every window](every-window.md#the-usual-order)).
2. **Check the setup**: the source current (typed with a unit: `100u`,
   `100 µA`), the voltage limit **VLIM**, the points per polarity and the
   settle delay.
3. **Position 1.** Set the switch box to position 1, select **1** in the
   window, and press **Run**. Each run measures at +I and then −I and
   averages the two, which cancels the contacts' thermoelectric offsets.
4. **Positions 2, 3 and 4**, the same way. You need all four: 1 and 2
   give the horizontal resistance, 3 and 4 the vertical one.
5. **Tick the four runs** and press **Copy ticked → Calc**. It takes
   exactly one run per position, and refuses anything else.
6. **Press Calculate.** The sheet resistance (Ω/□) and, with the
   thickness, the resistivity appear.

**Reading the runs.** Each run is plotted as voltage against current,
with a straight line through both polarities. The slope is the
resistance, and the table shows it as **R(fit)** beside the average
**R(ave)**. If the line misses a cluster of points, or a cluster is
smeared out, that position's contacts are suspect: re-seat and run it
again before copying it.

![The Hall tab after the four field and position combinations](../../assets/screens/vdp_hall/window-hall-effect-light.png#only-light)
![The Hall tab after the four field and position combinations](../../assets/screens/vdp_hall/window-hall-effect-dark.png#only-dark)

## Hall: carrier density and mobility

Hall uses the two diagonals of the same four contacts, at both
directions of the magnetic field. That is four runs: position 1 and
position 2, each with the field **+** and **−**.

1. **Switch to the Hall tab.** The instrument, sample name and thickness
   come with you.
2. **Set the source current.** Press **Set level** to apply it and check
   it before a run, if you want to.
3. **Position 1, field +.** Set the switch box and the magnet, select
   **Pos1** and **+**, and press **Run**.
4. **The other three combinations:** Pos1 with −, then Pos2 with + and
   with −. The window records the field direction you selected with each
   run. It cannot see the magnet, so what you select is what the
   calculation believes.
5. **Tick the four runs** and press **Copy ticked → Calc**. It takes
   exactly Pos1 and Pos2 at + and −, one run each.
6. **Fill in the rest of the calculation.**
    - **B (T):** the magnetic field, read off the magnet.
    - **Take Rs from VdP:** fills the sheet resistance from the Van der
      Pauw tab. It refuses if that calculation is out of date, and warns
      if the stage temperature has moved since.
    - **Sample type:** *Thin film* reports carriers per cm², *Bulk* per
      cm³.
7. **Press Calculate.** You get the Hall voltage, carrier type, carrier
   density, mobility and resistivity.

**Check the carrier type against what you expect.** It comes from the
sign of the Hall voltage, and a flipped sign is exactly what a swapped
pair of contacts looks like. It is the cheapest check there is on a Hall
run.

**Keep the current below compliance.** The Hall voltage is a small
difference between two large readings, so a clamped reading ruins it
more than it would a resistance. If a run reports that it hit **VLIM**,
lower the current or raise the limit and run it again.

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

Which pair of contacts carries the current and which pair senses the voltage, set on the switch box. All four positions are needed: 1 and 2 average into the horizontal resistance, 3 and 4 into the vertical one, and the sheet resistance needs both. The diagram above shows the roles for the position selected here.

| Control | What it does |
|---|---|
| **1** | Switch box position 1. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **2** | Switch box position 2. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **3** | Switch box position 3. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **4** | Switch box position 4. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |

#### Measurement setup

![The Measurement setup panel](../../assets/screens/vdp_hall/van-der-pauw-measurement-setup-light.png#only-light)
![The Measurement setup panel](../../assets/screens/vdp_hall/van-der-pauw-measurement-setup-dark.png#only-dark)

What one run does: source the current below through the two contacts the selected position makes the current pair, measure the voltage across the other two, then repeat with the current reversed. The two blocks are averaged into one resistance for that position.

| Control | What it does |
|---|---|
| **Source current** | The current driven through the sample, typed with a unit: 100u, 100 uA or 1e-4. Both polarities of it are measured. Big enough to lift the voltage clear of the noise, small enough not to heat the film - a bad guess shows up as a resistance that drifts with the level. |
| **Voltage range** | The range the voltage is measured on, from what the connected instrument declares. AUTO lets it choose. A range far larger than the reading costs resolution; one too small clips it. |
| **VLIM (V)** | Compliance: the highest voltage the instrument will put across the sample to push the current you asked for. Reach it and it stops being a current source - the run is flagged and you are told when it ends. |
| **Points** | Readings per polarity. They are averaged, so more of them beats down noise and lengthens the run in proportion. |
| **Delay (ms)** | How long to wait after each polarity change before reading. This is what lets the thermoelectric offsets settle; too short and the two polarities do not cancel. |
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

The four position resistances go in, the sheet resistance comes out. Values copied from ticked runs carry those runs with them into the saved header; typed values do not, and the status line at the bottom says which you have.

| Control | What it does |
|---|---|
| **Pos1 (Ω) ... Pos4 (Ω)** | The resistance measured at this switch-box position, in ohms. Pos1 and Pos2 average into Rh, Pos3 and Pos4 into Rv. Editing a copied value drops the run behind it, since the number is no longer that run's. |
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
| **Pos1** | Switch box position 1. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **Pos2** | Switch box position 2. Set the box to match before pressing Run: the run is recorded against this position, and nothing can check the box itself. |
| **+, -** | Which way the magnet's field points through the sample, as it is set on the bench. Each run is recorded with it, and the calculation pairs the + runs against the - ones. |

#### Measurement setup

![The Measurement setup panel](../../assets/screens/vdp_hall/hall-effect-measurement-setup-light.png#only-light)
![The Measurement setup panel](../../assets/screens/vdp_hall/hall-effect-measurement-setup-dark.png#only-dark)

What one run does: source the current below through one diagonal, measure the voltage across the other, at both current polarities. One run is one (position, field polarity) pair; four of them - both positions at both field signs - make the eight voltages the calculation needs.

| Control | What it does |
|---|---|
| **Source current** | The current through the sample, typed with a unit: 47u, 47 uA or 4.7e-5. It appears in the carrier density directly, so the value used by the calculation is the one in the I box there - which may differ from this if compliance clamped the source. |
| **Set level** | Check the current and, with an instrument connected, apply it now - to see what it does before a run. A value outside the instrument's limits is refused. |
| **Voltage range** | The range the voltage is measured on, from what the connected instrument declares. AUTO lets it choose. A range far larger than the reading costs resolution; one too small clips it. |
| **VLIM (V)** | Compliance: the highest voltage the instrument will apply to push the current you asked for. Clamping here is worse than elsewhere - the Hall voltage is a small difference between large readings, and a clamped reading is not the sample's. |
| **Points** | Readings per polarity, averaged. The Hall voltage is recovered by subtracting nearly equal numbers, so averaging is what makes it measurable at all - this is why the default is much higher than Van der Pauw's. |
| **Delay (ms)** | How long to wait after each polarity change before reading, in milliseconds. It lets thermoelectric offsets settle; too short and the two polarities do not cancel. |
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
| **I (A)** | The current the calculation should use, in amps. Left empty it falls back to the level in the setup panel - they differ when compliance clamped the source, and then this box is the honest one. |
| **Sample type** | Thin film reports carriers per square centimetre; Bulk divides by the thickness and reports per cubic centimetre. Changing it changes which number you get by a factor of the thickness, and none of the voltages move when it happens. |
| **Calculate** | Average the eight voltages into V_H, then compute carrier type, density, mobility and resistivity. The result records the runs behind it and goes stale if any input moves. |
| **Equations...** | Show the formulas this tab uses, with their symbols named - and, once a calculation is fresh, the same formulas with your numbers in them. |
<!-- /generated:controls -->

## What this means for your data

### Van der Pauw

<!-- generated:data-notes experiments/van-der-pauw.md -->
**Sheet resistance is computed from eight readings, not two.** If a run
reports fewer, something interrupted it and the result is refused rather
than computed from what arrived.

**Voltages are now recorded to nine significant figures**, not six.
Results from the original notebook carry a precision floor of about 0.1%
on anything derived from a difference of two readings. Sheet resistance
itself is largely unaffected; the Hall numbers taken alongside it are
not.

**Files record thickness in nanometres** (`thickness_nm`), and each run
records its fitted resistance (`R_fit_ohm`) beside R(ave). On an ohmic
contact the two agree closely; a large gap between them on one position
is worth a second look at that position's contacts.

**A sheet resistance can only be handed to a Hall run in the same
session.** That is deliberate — see [Hall effect](vdp-hall.md).
<!-- /generated:data-notes -->

### Hall

<!-- generated:data-notes experiments/hall.md -->
**Hall results from before August 2026 have two independent precision
floors on them**, one in the software and one in the instrument, both at
six significant figures. Because the Hall voltage is a small difference
between large readings, that is roughly a 0.1% floor on V_H and
everything derived from it. Noisy or irreproducible old Hall numbers are
more likely to be this than the sample.

**Van der Pauw and Hall must be run in the same session, on the same
mounted sample.** The sheet resistance is carried in memory, not read
from a file, so yesterday's Van der Pauw cannot feed today's Hall. If
you need to, re-run it — it takes minutes and it is measuring the same
contacts you are about to use.

**Check the carrier type against what you expect.** It comes from the
sign of the Hall voltage, and a sign flip is what a swapped pair of
contacts looks like. It is the cheapest sanity check available on a Hall
run.
<!-- /generated:data-notes -->
