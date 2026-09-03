
"""The Keithley 2401 driver.

The 2401 is the same instrument family as the 2450 but an older
generation, and the SCPI spelling differs in ways that do not announce
themselves: send a 2450 compliance command to a 2401 and the instrument
logs an error, ignores it, and carries on with whatever compliance it
had. Nothing raises. The sweep completes. The numbers are wrong.

So the thing worth testing is not "does it emit SCPI" but "does it emit
the *2400-series* SCPI, and never the 2450's". That is what this file
checks, along with the sweep it inherits from BaseSMU.
"""
import time

from core.transports.base import Transport
from drivers.base_smu import BaseSMU
from drivers.keithley_2401 import Keithley2401
from drivers.keithley_2450 import Keithley2450
from drivers.registry import driver_for_idn

SAMPLE_OHM = 470.0


class Fake2401(Transport):
    """A 2401 holding a plain resistor.

    Tracks the sourced level from the SCPI it receives so the test can
    assert on what was actually asked for, and answers :READ? with the
    five-field group a real 2400 returns.
    """

    def __init__(self):
        super().__init__()
        self.sent = []
        self.connected = True
        self.level = 0.0
        self.mode = "voltage"

    def connect(self, address, **kw):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        upper = text.upper()
        if ":SOUR:FUNC" in upper:
            self.mode = "current" if "CURR" in upper else "voltage"
        if ":SOUR:VOLT:LEV" in upper or ":SOUR:CURR:LEV" in upper:
            try:
                self.level = float(text.split()[-1])
            except ValueError:
                pass

    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "IDN" in last.upper():
            return "KEITHLEY INSTRUMENTS INC.,MODEL 2401,4102345,C30"
        if self.mode == "voltage":
            volts, amps = self.level, self.level / SAMPLE_OHM
        else:
            amps, volts = self.level, self.level * SAMPLE_OHM
        # voltage, current, resistance, timestamp, status
        return (f"{volts:.6E},{amps:.6E},{SAMPLE_OHM:.6E},"
                f"{time.time():.3f},0")


# ---------------------------------------------------------------
# A. the registry finds it
# ---------------------------------------------------------------


def test_identification(check):
    resolved = driver_for_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2401,4102345,C30")
    check("2401 IDN resolves to the 2401 driver", resolved is Keithley2401,
          resolved.DISPLAY_NAME if resolved else "None")

    # A serial number containing '2401' must not hijack another model. The
    # registry prefers the longest matching ID, which is what protects this.
    hijack = driver_for_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2611A,124019,3.2.1")
    check("a serial containing 2401 doesn't hijack a 2611A",
          hijack is not Keithley2401,
          hijack.DISPLAY_NAME if hijack else "None")

    # ---------------------------------------------------------------
    # B. the dialect is the 2400 one, not the 2450 one
    # ---------------------------------------------------------------


def test_dialect_is_2400_series(check):
    t = Fake2401()
    smu = Keithley2401(t)

    smu.set_source_function("voltage")
    smu.set_current_limit(1e-3)
    smu._apply_measure_current_range(1e-3)
    smu.set_remote_sense(True)
    sent = " | ".join(t.sent)

    check("compliance uses :SENS:CURR:PROT", ":SENS:CURR:PROT" in sent)
    check("compliance does NOT use the 2450's :SOUR:VOLT:ILIM",
          "ILIM" not in sent.upper())
    check("sense function is set alongside source", ':SENS:FUNC "CURR"' in sent)
    check("auto-clear is disabled", ":SOUR:CLE:AUTO 0" in sent)
    check("remote sense uses numeric 1", ":SYST:RSEN 1" in sent)

    # The distinctness claim, stated directly: drive both models through the
    # same call and confirm the bytes differ.
    t2450 = Fake2401()
    Keithley2450(t2450).set_voltage_limit(2.0)
    t2401 = Fake2401()
    Keithley2401(t2401).set_voltage_limit(2.0)
    check("2450 and 2401 emit different compliance commands",
          t2450.sent != t2401.sent,
          f"{t2450.sent[0].split()[0]} vs {t2401.sent[0].split()[0]}")

    # ---------------------------------------------------------------
    # C. configure() puts it in a safe known state
    # ---------------------------------------------------------------


def test_reset(check):
    t = Fake2401()
    Keithley2401(t).reset()
    sent = " | ".join(t.sent)
    check("resets", "*RST" in sent)
    # configure() used to pin :OUTP:SMOD HIMP. It is now a per-run choice
    # from the panel, defaulting to NORMal - the relay has a finite number
    # of operations in it and a periodic run cycles the output hundreds of
    # times. Asserting its ABSENCE here so the old behaviour can't creep
    # back in unnoticed.
    check("output-off mode is NOT pinned at configure",
          ":OUTP:SMOD" not in sent,
          "it is a per-run panel choice now")
    check("but the control exists and both ways work",
          Keithley2401.supports_high_z_off())
    t_off = Fake2401()
    d_off = Keithley2401(t_off)
    d_off.set_output_off_mode(False)
    d_off.set_output_off_mode(True)
    check("NORMal and HIMPedance both reachable",
          any(":OUTP:SMOD NORM" in x for x in t_off.sent)
          and any(":OUTP:SMOD HIMP" in x for x in t_off.sent))
    check("4-wire by default", ":SYST:RSEN 1" in sent)

    # ---------------------------------------------------------------
    # D. it sweeps, via the inherited software fallback
    # ---------------------------------------------------------------


def test_inherited_software_sweep(check):
    check("declares software sweep", Keithley2401.sweep_kind() == "software")
    check("does not define its own sweep",
          Keithley2401.start_linear_sweep is BaseSMU.start_linear_sweep,
          "inherits BaseSMU's")

    t = Fake2401()
    smu = Keithley2401(t)
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", -1.0, 1.0, 21, 0.0)

    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 21 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced, measured = smu.read_sweep(21)

    check("all points returned", len(measured) == 21, f"{len(measured)}/21")
    if len(measured) == 21:
        recovered = (sourced[-1] - sourced[0]) / (measured[-1] - measured[0])
        error = abs(recovered - SAMPLE_OHM) / SAMPLE_OHM
        check("recovers the sample resistance", error < 1e-5,
              f"{recovered:.4f} Ω vs {SAMPLE_OHM:g} Ω")

    # ---------------------------------------------------------------
    # E. the rounding bug is not reproduced
    # ---------------------------------------------------------------


def test_low_bias_sweep_not_quantised(check):
    # The original sent round(Vo + i*step, 4), quantising the source to
    # 100 µV. Over ±1 V that is invisible. Over ±100 µV it collapses 21
    # requested levels into 3 duplicates, while the saved x-axis still
    # claims 21 evenly spaced points - so the damage is undetectable after
    # the fact. This is the regression guard for that.
    t = Fake2401()
    smu = Keithley2401(t)
    smu.set_source_function("voltage")
    smu.start_linear_sweep("voltage", -1e-4, 1e-4, 21, 0.0)

    deadline = time.monotonic() + 20
    while smu.sweep_points_ready() < 21 and time.monotonic() < deadline:
        time.sleep(0.01)
    sourced, _ = smu.read_sweep(21)

    distinct = len({round(v, 12) for v in sourced})
    check("21 distinct levels at ±100 µV", distinct == 21, f"{distinct}/21")

    quantised = len({round(round(-1e-4 + i * (2e-4 / 20), 4), 12)
                     for i in range(21)})
    check("the original's rounding would have given far fewer",
          quantised < 21, f"round(...,4) yields {quantised}/21")

    # ---------------------------------------------------------------
    # F. reading format
    # ---------------------------------------------------------------


def test_reading_parse(check):
    volts, amps = Keithley2401._parse_reading(
        "1.234000E-01,1.000000E-04,1.234000E+03,1234.5,0")
    check("takes voltage and current from a 5-field group",
          volts == 0.1234 and amps == 1e-4, f"V={volts} I={amps}")
    check("empty reply is handled",
          Keithley2401._parse_reading("") == (None, None))
