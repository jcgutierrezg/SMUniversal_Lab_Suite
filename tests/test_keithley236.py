"""Keithley 236 - command spellings, reply parsing, and the silent changes.

Modelled on `test_keithley487.py`: the assertions are about the exact
strings on the wire and the *absence* of everything else. The driver was
written from the manual with no script behind it and before the unit had
answered anything, so the strings are all there is to check offline.

The traps this file exists for:

  * the dialect is Keithley's device-dependent commands - one `*RST` or
    one colon reaching the instrument is an illegal command;
  * a level beyond the selected range is **clamped to the range's full
    scale** in silence, and a compliance below 100 counts is raised;
  * each source keeps its own setup, so changing source brings back
    whatever the other one last had;
  * a level or a compliance may only take effect on a trigger - the fake
    assumes the worst, so a driver that relies on `X` alone fails here;
  * a trigger must never land on an unread reading, and a status query
    must never trigger anything.
"""
import math
import re
import time

import pytest

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import AUTO, RangeError, RangePlan
from smuniversal_lab_suite.core.transports.base import (
    Transport,
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.keithley_236 import Keithley236
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_SMUS,
    driver_by_display_name,
    driver_for_idn,
)
from smuniversal_lab_suite.experiments.fixed_source.experiment import (
    FixedSourceExperiment,
)
from smuniversal_lab_suite.experiments.hall.experiment import HallExperiment
from smuniversal_lab_suite.experiments.iv_sweep.experiment import (
    IVSweepExperiment,
)
from smuniversal_lab_suite.experiments.ossila_4pp.experiment import (
    Ossila4PPExperiment,
)
from smuniversal_lab_suite.experiments.vanderpauw.experiment import (
    VanDerPauwExperiment,
)

#: Full scales, as the manual gives them and not read from the driver.
V_FS = {1: 1.1, 2: 11.0, 3: 110.0}
I_FS = {1: 1e-9, 2: 1e-8, 3: 1e-7, 4: 1e-6, 5: 1e-5, 6: 1e-4, 7: 1e-3,
        8: 1e-2, 9: 1e-1}

#: U1 positions (manual Figure 3-15) and U9 positions (Figure 3-23).
TRIGGER_OVERRUN, IDDC, IDDCO, INTERLOCK = 0, 1, 2, 3
ILLEGAL_MEASURE_RANGE, ILLEGAL_SOURCE_RANGE = 4, 5
VALUE_OUT_OF_RANGE, OVERFLOW = 2, 8

#: A command and its options. An E is part of a number when it follows
#: a digit - `B1.0000E+00,2,0` - and a command letter otherwise.
_COMMAND = re.compile(r"([A-Z])((?:[-+0-9.,\s]|(?<=[0-9.])E)*)")


def _factory_source(voltage):
    """One source as factory initialisation leaves it (Table 3-4):
    0 on the 11 V / 10 mA range, 10 mA / 10 V compliance, fast
    integration, default delay on."""
    return {"level": 0.0, "b_range": 2 if voltage else 8, "delay": 0,
            "compliance": 1e-2 if voltage else 10.0,
            "l_range": 8 if voltage else 2, "O": "0", "P": "0", "S": "0",
            "W": "1", "Z": "0", "applied_level": 0.0,
            "applied_compliance": 1e-2 if voltage else 10.0}


def _leftover_source(voltage):
    """What somebody else's session left on one source: every setting
    this driver depends on, set the wrong way."""
    return {"level": 5.0 if voltage else 1e-3, "b_range": 2 if voltage
            else 7, "delay": 250, "compliance": 1e-2 if voltage else 10.0,
            "l_range": 0, "O": "1", "P": "5", "S": "0", "W": "0",
            "Z": "1", "applied_level": 0.0,
            "applied_compliance": 1e-2 if voltage else 10.0}


class Fake236(Transport):
    """A 236 that behaves the way its manual says - and, where the
    manual is unclear, the worst way it could.

    `resistance` is the load across the output, in ohms; None is an open
    circuit. A programmed level or compliance reaches the output only at
    the next trigger (the pessimistic reading of paragraphs 3.6.10 and
    3.6.18). `interlock_open` is a fitted interlock with the lid up;
    `stuck` names commands it ignores, `reject` names ones it refuses
    with an IDDCO. `leftovers` starts it as somebody else's session left
    it - trigger on talk, suppression on, the current source active -
    rather than as factory initialisation does.
    """

    def __init__(self, model="236", resistance=1e6, interlock_open=False,
                 stuck=(), reject=(), leftovers=False, level_on_x=False,
                 compliance_on_x=False, recover_s=0.0, can_poll=True,
                 never_ready=False):
        super().__init__()
        self.connected = True
        self.model = model
        self.resistance = resistance
        self.interlock_open = interlock_open
        self.stuck = set(stuck)
        self.reject = set(reject)
        # The other reading of the manual: a level, or a compliance,
        # that reaches the output when its command executes.
        self.level_on_x = level_on_x
        self.compliance_on_x = compliance_on_x
        # After a reading has been read, the unit is not ready for the
        # next trigger for `recover_s`; a trigger before then is a TRIG
        # OVERRUN and no reading follows - what the bench saw at 0.4 ms
        # (2026-11-16). `can_poll` False is a transport with no serial
        # poll; `never_ready` a unit that has stopped.
        self.recover_s = recover_s
        self.can_poll = can_poll
        self.never_ready = never_ready
        self.ready_at = 0.0
        self.polls = 0
        self.overruns = 0
        self.sent = []
        self.events = []
        self.buffer = ""
        self.pending = None
        self.unread = None
        self.triggers = 0
        self.triggers_in_standby = 0
        self.overwritten = 0       # triggers that landed on an unread reading
        self.u1 = [0] * 26
        self.u9 = [0] * 10
        # Factory: immediate trigger, continuous; source-only output.
        self.glob = {"G": "1,0,0", "K": "0", "Y": "0", "M": "0,0",
                     "R": "1", "T": "4,0,0,0", "N": "0"}
        fresh = _leftover_source if leftovers else _factory_source
        self.source = {0: fresh(True), 1: fresh(False)}
        self.active = 0
        if leftovers:
            # Trigger on talk - the setting that would hurt most - and
            # left sourcing current.
            self.glob["T"] = "2,0,4,0"
            self.active = 1

    @property
    def output(self):
        return self.glob["N"] == "1"

    @property
    def src(self):
        return self.source[self.active]

    # ---- what a talk returns ----
    def _status_word(self, which):
        s, g = self.src, self.glob
        if which == 0:
            return f"{self.model}A01  "
        if which == 1:
            word, self.u1 = "".join(map(str, self.u1)), [0] * 26
            return f"ERS{word}"
        if which == 3:
            items, rest = g["G"].split(",", 1)
            mask, comp = g["M"].split(",")
            return (f"MSTG{int(items):02d},{rest}K{g['K']}"
                    f"M{int(mask):03d},{comp}N{g['N']}R{g['R']}T{g['T']}"
                    f"V0Y{g['Y']}")
        if which == 4:
            ident = "IMP" if self.active == 0 else "VMP"
            # The comma after L is the unit's own (2026-11-16).
            return (f"{ident}L,{s['l_range']:02d}F{self.active},0O{s['O']}"
                    f"P{s['P']}S{s['S']}W{s['W']}Z{s['Z']}")
        if which == 5:
            # As the unit spells it: `ICP0100.00E-06` - an engineering
            # exponent and a zero-padded mantissa.
            ident = "ICP" if self.active == 0 else "VCP"
            value = s["compliance"]
            exponent = 3 * math.floor(math.log10(value) / 3) if value else 0
            return f"{ident}{value / 10 ** exponent:07.2f}E{exponent:+03d}"
        if which == 9:
            word, self.u9 = "".join(map(str, self.u9)), [0] * 10
            return f"WRS{word}"
        raise AssertionError(f"U{which} not modelled")

    def _take_reading(self):
        s = self.src
        level, limit = s["applied_level"], s["applied_compliance"]
        if self.active == 0:
            measured = 0.0 if self.resistance is None \
                else level / self.resistance
            fs_table, src_unit, meas_unit = I_FS, "V", "I"
        else:
            measured = (limit if level >= 0 else -limit) \
                if self.resistance is None else level * self.resistance
            fs_table, src_unit, meas_unit = V_FS, "I", "V"
        s_status = "N"
        if abs(measured) >= limit:
            measured = limit if measured >= 0 else -limit
            s_status = "O"
        m_status = "Z" if s["Z"] == "1" else "N"
        if s["l_range"]:
            if abs(measured) > 1.125 * fs_table[s["l_range"]]:
                m_status = "O"
                self.u9[OVERFLOW] = 1
                measured = 9.9999e37
        if s_status == "O":
            m_status = "O"
        return (f"{s_status}SDC{src_unit}{level:+.4E},"
                f"{m_status}MDC{meas_unit}{measured:+.5E}")

    # ---- the wire ----
    def _write(self, text):
        self.sent.append(text)
        self.events.append(text)
        body = self.buffer + text.strip()
        if not body.endswith("X"):
            self.buffer = body
            return
        self.buffer = ""
        commands = _COMMAND.findall(body[:-1])
        if "".join(letter + option for letter, option in commands) \
                != body[:-1] or any("*" in o or "?" in o for _, o in commands):
            self.u1[IDDC] = 1
            return
        for letter, _ in commands:
            if letter not in "ABCDFGHJKLMNOPQRSTUVWYZ":
                self.u1[IDDC] = 1
                return
        for letter, option in commands:
            self._execute(letter, option.replace(" ", ""))

    def _execute(self, letter, option):
        if letter in self.stuck:
            return
        if letter in self.reject:
            self.u1[IDDCO] = 1
            return
        s = self.src
        voltage = self.active == 0
        if letter == "F":
            source, function = (option.split(",") + ["", ""])[:2]
            source = int(source) if source else self.active
            if function not in ("", "0"):
                raise AssertionError("only the dc function is used")
            if source != self.active:
                self.glob["N"] = "0"       # a change of source: standby
            self.active = source
        elif letter == "B":
            level, b_range, delay = (option.split(",") + ["", "", ""])[:3]
            b_range = int(b_range) if b_range else s["b_range"]
            if b_range > (3 if voltage else 9):
                self.u1[ILLEGAL_SOURCE_RANGE] = 1
                return
            level = float(level) if level else s["level"]
            table = V_FS if voltage else I_FS
            if b_range and abs(level) > table[b_range]:
                # Clamped, not refused (manual 3.6.19, Value Out of Range).
                level = table[b_range] if level > 0 else -table[b_range]
                self.u9[VALUE_OUT_OF_RANGE] = 1
            s["level"], s["b_range"] = level, b_range
            if self.level_on_x and self.glob["N"] == "1":
                s["applied_level"] = level
            if delay:
                s["delay"] = int(delay)
        elif letter == "L":
            value, l_range = (option.split(",") + ["", ""])[:2]
            l_range = int(l_range) if l_range else s["l_range"]
            if l_range > (9 if voltage else 3):
                self.u1[ILLEGAL_MEASURE_RANGE] = 1
                return
            value = abs(float(value)) if value else s["compliance"]
            table = I_FS if voltage else V_FS
            if l_range:
                if value > table[l_range]:
                    value = table[l_range]
                    self.u9[VALUE_OUT_OF_RANGE] = 1
                value = max(value, table[l_range] / 100.0)   # 100 counts
            s["compliance"], s["l_range"] = value, l_range
            if self.compliance_on_x and self.glob["N"] == "1":
                s["applied_compliance"] = value
        elif letter == "N":
            if option == "1" and self.interlock_open:
                self.u1[INTERLOCK] = 1
                return
            self.glob["N"] = option
        elif letter == "H":
            self._trigger()
        elif letter == "U":
            self.pending = int(option)
        elif letter in ("O", "P", "S", "W", "Z"):
            s[letter] = option
        elif letter in self.glob:
            self.glob[letter] = option
        elif letter in ("J", "C", "V", "A", "Q", "D"):
            raise AssertionError(f"{letter} is never sent by this driver")

    def _trigger(self):
        if self.glob["R"] != "1":
            return
        # H0X is honoured whatever the origin (3.6.18, note 7). The check
        # is the fake's own: in any origin but 4 a talk or an X can
        # trigger too, so a trigger seen there means a driver that never
        # set its idle configuration.
        assert self.glob["T"].startswith("4"), self.glob["T"]
        self.triggers += 1
        if self.glob["N"] != "1":
            self.triggers_in_standby += 1
            return
        if not self._ready():
            self.u1[TRIGGER_OVERRUN] = 1
            self.overruns += 1
            return
        if self.unread is not None:
            self.overwritten += 1
        s = self.src
        s["applied_level"] = s["level"]
        s["applied_compliance"] = s["compliance"]
        self.unread = self._take_reading()

    def _read(self, timeout_s):
        self.events.append("<talk>")
        if self.pending is not None:
            which, self.pending = self.pending, None
            return self._status_word(which)
        if self.glob["T"].startswith("2"):
            raise AssertionError("trigger on talk: this talk is a trigger")
        if self.unread is None:
            raise TimeoutError("no reading: nothing was triggered")
        reading, self.unread = self.unread, None
        self.ready_at = time.monotonic() + self.recover_s
        return reading

    def clear(self):
        """SDC: power-up defaults - standby, source-only output, local
        sense; most else as last programmed (manual Table 3-4)."""
        self.buffer, self.pending, self.unread = "", None, None
        self.glob.update(N="0", G="1,0,0", K="0", M="0,0")
        for s in self.source.values():
            s["O"] = "0"
        return True

    def _ready(self):
        return (not self.never_ready and self.glob["R"] == "1"
                and time.monotonic() >= self.ready_at)

    def _serial_poll(self):
        if not self.can_poll:
            raise NotImplementedError("this transport cannot serial poll")
        self.polls += 1
        return 0x10 if self._ready() else 0x00

    def terminal_volts(self):
        """What a second meter across the load reads: 0 in standby,
        else the applied level, clamped by the applied compliance."""
        if self.glob["N"] != "1" or self.resistance is None:
            return 0.0
        s = self.src
        if self.active == 0:
            level, ceiling = s["applied_level"],                 s["applied_compliance"] * self.resistance
        else:
            level, ceiling = s["applied_level"] * self.resistance,                 s["applied_compliance"]
        return level if abs(level) <= ceiling else             (ceiling if level > 0 else -ceiling)

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False


def make(**kwargs):
    kwargs.setdefault("leftovers", True)
    transport = Fake236(**kwargs)
    driver = Keithley236(transport)
    return driver, transport


def ready(**kwargs):
    driver, transport = make(**kwargs)
    driver.reset()
    transport.sent.clear()
    transport.events.clear()
    return driver, transport


def energised(mode="voltage", compliance=None, plan=None, **kwargs):
    """Reset, configured the way the experiments do it, output on."""
    driver, transport = ready(**kwargs)
    driver.set_source_function(mode)
    driver.apply_ranges(plan or RangePlan.for_sourcing(
        mode, 11.0 if mode == "voltage" else 1e-3, AUTO))
    if mode == "voltage":
        driver.set_current_limit(compliance or 1e-3)
    else:
        driver.set_voltage_limit(compliance or 10.0)
    driver.output_on()
    transport.sent.clear()
    transport.events.clear()
    return driver, transport


# ---------------------------------------------------------------------
# identity and the dialect
# ---------------------------------------------------------------------

def test_it_is_registered_but_never_auto_detected(check):
    check("in the SMU fleet", Keithley236 in KNOWN_SMUS)
    check("reachable by name, as the manual dropdown asks",
          driver_by_display_name("Keithley 236") is Keithley236)
    check("no MODEL_IDS", Keithley236.MODEL_IDS == [])
    check("nothing resolves to it",
          driver_for_idn("236A01") is None
          and driver_for_idn("KEITHLEY,236,1,A01") is None)


def test_identify_asks_u0_not_idn(check):
    driver, transport = make()
    reply = driver.identify()
    check("the model and firmware, blanks stripped", reply == "236A01",
          repr(reply))
    check("asked with U0X", transport.sent == ["U0X"], f"{transport.sent}")


@pytest.mark.parametrize("model", ["237", "238"])
def test_reset_refuses_a_sibling_before_configuring_it(check, model):
    driver, transport = make(model=model)
    with pytest.raises(RuntimeError, match=model):
        driver.reset()
    check("only the identity question went out",
          transport.sent == ["U0X"], f"{transport.sent}")


def test_nothing_scpi_ever_reaches_it(check):
    driver, transport = make()
    driver.reset()
    driver.set_source_function("voltage")
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 10.0, 1e-3))
    driver.set_current_limit(1e-3)
    driver.set_nplc(1.0)
    driver.set_remote_sense(False)
    driver.output_on()
    driver.set_voltage_level(1.0)
    driver.measure()
    driver.compliance_tripped()
    driver.read_error()
    driver.output_off()
    for text in transport.sent:
        check(f"{text!r} is a device-dependent command",
              "*" not in text and ":" not in text and "?" not in text
              and text.endswith("X"))
    many = [t for t in transport.sent if len(_COMMAND.findall(t[:-1])) > 1]
    check("and one command per X", not many, f"{many}")
    check("nothing illegal along the way",
          transport.u1 == [0] * 26 and transport.u9[VALUE_OUT_OF_RANGE] == 0,
          f"U1 {transport.u1} U9 {transport.u9}")


# ---------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------

def test_reset_overrides_what_somebody_else_left(check):
    driver, transport = ready()
    g = transport.glob
    check("standby", g["N"] == "0")
    check("source and measure items, prefix, no suffix",
          g["G"] == "5,1,0", g["G"])
    check("immediate trigger only, starting the source phase",
          g["T"] == "4,1,0,0", g["T"])
    check("triggers enabled", g["R"] == "1")
    check("the voltage source is the active one", transport.active == 0)
    for index, name in ((0, "voltage"), (1, "current")):
        s = transport.source[index]
        check(f"{name} source: suppression off, filter off, local sense",
              (s["Z"], s["P"], s["O"]) == ("0", "0", "0"),
              f"{s['Z']} {s['P']} {s['O']}")
        check(f"{name} source: line-cycle integration, default delay on",
              (s["S"], s["W"]) == ("3", "1"), f"{s['S']} {s['W']}")
        check(f"{name} source: level 0 on autorange, no dc delay",
              (s["level"], s["b_range"], s["delay"]) == (0.0, 0, 0),
              f"{s['level']} {s['b_range']} {s['delay']}")
        check(f"{name} source: the small reset compliance on autorange",
              s["l_range"] == 0 and s["compliance"]
              == (1e-4 if index == 0 else 1.0), f"{s['compliance']}")


def test_reset_never_triggers_and_never_restores_factory(check):
    driver, transport = make()
    driver.reset()
    check("no trigger during reset", transport.triggers == 0)
    check("no J0X - every setting is sent instead",
          not any(t.startswith("J") for t in transport.sent))


def test_a_setting_that_did_not_take_fails_the_reset(check):
    driver, transport = make(stuck={"T"})
    with pytest.raises(RuntimeError, match="did not take"):
        driver.reset()


def test_a_command_refused_during_reset_fails_it(check):
    driver, transport = make(reject={"Z"})
    with pytest.raises(RuntimeError, match="IDDCO"):
        driver.reset()


def test_flags_latched_before_the_reset_are_not_its_own(check):
    driver, transport = make()
    transport.u1[TRIGGER_OVERRUN] = 1
    driver.reset()
    check("a trigger overrun from an earlier session does not fail it",
          True)


# ---------------------------------------------------------------------
# readings
# ---------------------------------------------------------------------

def test_a_reading_sourcing_voltage_is_none_then_amps(check):
    driver, transport = energised(resistance=1e6)
    driver.set_voltage_level(2.0)
    transport.events.clear()
    volts, amps = driver.measure()
    check("no voltage: it is not measured", volts is None)
    check("the current through 1 MOhm", amps == pytest.approx(2e-6),
          f"{amps}")
    check("a trigger, then one talk",
          transport.events == ["H0X", "<talk>"], f"{transport.events}")


def test_a_reading_sourcing_current_is_volts_then_none(check):
    driver, transport = energised(mode="current", resistance=1e3)
    driver.set_current_level(1e-3)
    volts, amps = driver.measure()
    check("the voltage across 1 kOhm", volts == pytest.approx(1.0),
          f"{volts}")
    check("no current: it is not measured", amps is None)


def test_a_level_is_on_the_sample_before_the_setter_returns(check):
    """The fake applies a level only at a trigger. A driver that sent B
    and waited for the reading's trigger would leave the old level on
    the sample through the whole settle."""
    driver, transport = energised()
    driver.set_voltage_level(3.0)
    check("applied already", transport.src["applied_level"] == 3.0,
          f"{transport.src['applied_level']}")


def test_a_compliance_set_in_operate_takes_effect_at_once(check):
    driver, transport = energised(compliance=1e-3)
    driver.set_current_limit(2e-4)
    check("applied already",
          transport.src["applied_compliance"] == pytest.approx(2e-4))


def test_a_compliance_set_in_standby_is_in_force_from_operate(check):
    driver, transport = ready()
    driver.set_source_function("voltage")
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 11.0, AUTO))
    driver.set_current_limit(5e-6)
    check("nothing triggered in standby", transport.triggers == 0)
    driver.output_on()
    check("operate's own cycle applied it",
          transport.src["applied_compliance"] == pytest.approx(5e-6))


def test_no_trigger_in_standby_and_none_on_an_unread_reading(check):
    driver, transport = energised()
    for level in (0.5, 1.0, -1.0, 0.0):
        driver.set_voltage_level(level)
        driver.measure()
        driver.compliance_tripped()
    driver.output_off()
    driver.set_voltage_level(1.0)
    check("never triggered in standby", transport.triggers_in_standby == 0)
    check("no trigger ever landed on an unread reading",
          transport.overwritten == 0)
    check("nothing left unread", transport.unread is None)


def test_a_status_query_triggers_nothing(check):
    driver, transport = energised()
    before = transport.triggers
    driver.read_error()
    driver.read_current_limit()
    driver.identify()
    check("no trigger from a talk", transport.triggers == before)


def test_compliance_is_flagged_from_the_reading(check):
    driver, transport = energised(compliance=1e-6, resistance=1e3,
                                  plan=RangePlan.for_sourcing(
                                      "voltage", 11.0, 1e-6))
    driver.compliance_tripped()
    driver.set_voltage_level(1.0)           # 1 mA wanted, 1 uA allowed
    volts, amps = driver.measure()
    check("the reading at compliance is a real number",
          amps == pytest.approx(1e-6), f"{amps}")
    check("and it is flagged", driver.compliance_tripped() is True)
    check("which clears when asked", driver.compliance_tripped() is False)


def test_an_overflow_is_no_reading_and_not_a_trip(check):
    driver, transport = energised(compliance=1e-3, resistance=1e3,
                                  plan=RangePlan.for_sourcing(
                                      "voltage", 11.0, 1e-3))
    # The measurement range pinned below the current, compliance above it.
    transport.src["l_range"] = 4
    driver.set_voltage_level(0.5)           # 500 uA on the 1 uA range
    volts, amps = driver.measure()
    check("no reading", amps is None, f"{amps}")
    check("not a compliance trip", driver.compliance_tripped() is False)


@pytest.mark.parametrize("reply", [
    "",
    "NSDCV+1.0000E+00",                          # no measure item
    "NMDCI+1.00000E-06",                         # no source item
    "NSDCI+1.0000E-03,NMDCV+1.00000E+00",        # sourcing the other one
    "NSDCV+1.0000E+00,ZMDCI+1.00000E-06",        # suppressed
])
def test_a_reading_in_any_other_shape_raises(check, reply):
    driver, _ = make()
    with pytest.raises(ValueError):
        driver._parse_reading(reply)


def test_the_manual_spaced_layout_still_parses(check):
    driver, _ = make()
    value = driver._parse_reading("NSDCV+1.2345 E+00, NMDCI+1.23456 E-09")
    check("spaces are not part of the format", value == pytest.approx(
        1.23456e-9), f"{value}")


# ---------------------------------------------------------------------
# the silent changes: refused before the wire
# ---------------------------------------------------------------------

def test_a_level_beyond_the_fixed_range_is_refused(check):
    driver, transport = energised(plan=RangePlan.for_sourcing(
        "voltage", 1.0, AUTO))
    with pytest.raises(RangeError, match="full scale"):
        driver.set_voltage_level(5.0)
    check("nothing reached the wire", transport.sent == [],
          f"{transport.sent}")
    check("and the instrument never clamped anything",
          transport.u9[VALUE_OUT_OF_RANGE] == 0)


def test_the_fake_would_have_clamped_it(check):
    """So the refusal above is protecting against something real."""
    _, transport = ready()
    transport.write("B0,1,0X")
    transport.write("B5.0000E+00,1,0X")
    check("1.1 V instead of 5 V", transport.src["level"] == 1.1)


def test_a_compliance_beyond_the_range_is_refused(check):
    driver, transport = energised(compliance=1e-6, plan=RangePlan.for_sourcing(
        "voltage", 11.0, 1e-6))
    with pytest.raises(LimitError, match="beyond"):
        driver.set_current_limit(5e-6)
    check("nothing reached the wire", transport.sent == [])


def test_a_compliance_below_100_counts_is_refused(check):
    driver, transport = energised(compliance=1e-2, plan=RangePlan.for_sourcing(
        "voltage", 11.0, 1e-1))
    with pytest.raises(LimitError, match="100 counts"):
        driver.set_current_limit(1e-4)    # 100 counts of 100 mA is 1 mA
    check("nothing reached the wire", transport.sent == [])


def test_ranging_moves_the_compliance_under_the_new_range(check):
    driver, transport = ready()
    driver.set_source_function("voltage")
    driver.set_current_limit(1e-2)
    transport.u9 = [0] * 10
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 11.0, 1e-6))
    check("no VALUE OUT OF RANGE from the range change",
          transport.u9[VALUE_OUT_OF_RANGE] == 0, f"{transport.u9}")
    check("measure range 1 uA", transport.src["l_range"] == 4)


# ---------------------------------------------------------------------
# each source remembers its own setup
# ---------------------------------------------------------------------

def test_a_change_of_source_sends_this_drivers_settings_again(check):
    driver, transport = ready()
    driver.set_source_function("voltage")
    driver.set_nplc(0.2)
    driver.set_remote_sense(True)
    driver.set_source_function("current")
    s = transport.source[1]
    check("the current source integrates as asked", s["S"] == "1", s["S"])
    check("and senses as asked", s["O"] == "1", s["O"])
    check("its level is 0", s["level"] == 0.0)


def test_a_level_for_the_other_source_is_refused(check):
    driver, _ = ready()
    driver.set_source_function("voltage")
    with pytest.raises(ValueError, match="sourcing voltage"):
        driver.set_current_level(1e-6)


# ---------------------------------------------------------------------
# output
# ---------------------------------------------------------------------

def test_output_off_is_zero_then_standby_and_writes_only(check):
    driver, transport = energised()
    driver.set_voltage_level(2.0)
    transport.events.clear()
    driver.output_off()
    check("B0 then N0, nothing read",
          transport.events == ["B0.0000E+00,2,0X", "N0X"]
          or transport.events == ["B0,2,0X", "N0X"],
          f"{transport.events}")
    check("in standby", transport.output is False)


def test_an_open_interlock_stops_output_on(check):
    driver, transport = ready(interlock_open=True)
    with pytest.raises(RuntimeError, match="interlock"):
        driver.output_on()
    check("left in standby", transport.output is False)
    check("and nothing triggered", transport.triggers == 0)


# ---------------------------------------------------------------------
# reading state back, errors, timing
# ---------------------------------------------------------------------

def test_the_compliance_and_range_read_back(check):
    driver, transport = energised(plan=RangePlan.for_sourcing(
        "voltage", 11.0, 1e-3), compliance=5e-4)
    check("U5 compliance", driver.read_current_limit()
          == pytest.approx(5e-4))
    check("U4 measure range", driver.read_measure_current_range() == 1e-3)
    with pytest.raises(ValueError, match="other source"):
        driver.read_voltage_limit()
    check("untrusted until the bench",
          not Keithley236.COMPLIANCE_READBACK_TRUSTED
          and not Keithley236.RANGE_READBACK_TRUSTED)


def test_read_error_latches_and_clears(check):
    driver, transport = ready()
    transport.write("E1X")
    code, message = driver.read_error()
    check("IDDC is the second flag", code == 2, f"{code} {message}")
    check("named", "IDDC" in message, message)
    check("then empty", driver.read_error() == (0, ""))


def test_nplc_snaps_onto_the_menu(check):
    check("1 PLC is the 20 ms line cycle", Keithley236.clamp_nplc(1) == 1.0)
    check("10 PLC is still 1", Keithley236.clamp_nplc(10) == 1.0)
    check("0.1 PLC is the 4 ms setting", Keithley236.clamp_nplc(0.1)
          == pytest.approx(0.2))
    check("0.01 PLC is the fast setting", Keithley236.clamp_nplc(0.01)
          == pytest.approx(0.0208))
    driver, transport = ready()
    driver.set_nplc(0.01)
    check("sent as S0", transport.sent[-1] == "S0X", transport.sent[-1])


def test_the_dc_delay_rides_in_the_b_command(check):
    driver, transport = ready()
    driver.set_source_delay(0.5)
    check("500 ms", transport.src["delay"] == 500)


# ---------------------------------------------------------------------
# which experiments take it
# ---------------------------------------------------------------------

def test_the_four_contact_tabs_refuse_it_and_iv_and_fixed_take_it(check):
    for experiment in (IVSweepExperiment, FixedSourceExperiment):
        check(f"{experiment.__name__} takes it",
              not experiment.unaccepted_caveats("source", Keithley236))
    for experiment in (VanDerPauwExperiment, HallExperiment,
                       Ossila4PPExperiment):
        check(f"{experiment.__name__} refuses it",
              "sourced_quantity_not_measured"
              in experiment.unaccepted_caveats("source", Keithley236))


def test_a_measure_range_for_the_other_source_is_kept_for_it(check):
    """A full plan names a voltage measurement range while sourcing
    voltage. Nothing measures voltage then; the range belongs to the
    current source's setup, and arrives with it."""
    driver, transport = ready()
    driver.set_source_function("current")
    driver.set_voltage_limit(10.0)            # on autorange
    driver.set_source_function("voltage")
    transport.sent.clear()
    driver.apply_ranges(RangePlan(source_voltage=11.0, source_current=1e-3,
                                  measure_current=1e-3, measure_voltage=1.1))
    check("nothing sent for the voltage measurement range",
          not any(t.startswith("L") and t.endswith(",1X")
                  for t in transport.sent), f"{transport.sent}")
    transport.u9 = [0] * 10
    driver.set_source_function("current")
    s = transport.source[1]
    check("the current source arrives on the 1.1 V range", s["l_range"] == 1)
    check("with its 10 V compliance held inside it, not clamped",
          s["compliance"] == pytest.approx(1.1)
          and transport.u9[VALUE_OUT_OF_RANGE] == 0,
          f"{s['compliance']} {transport.u9}")
    driver.set_voltage_limit(1.0)             # no stale warning to trip on
    check("and the next compliance is set cleanly",
          s["compliance"] == pytest.approx(1.0))


# ---------------------------------------------------------------------
# replies read off the unit, 2026-11-16 (firmware A10)
# ---------------------------------------------------------------------

class Replays(Transport):
    """Answers each U word with what the unit said, and each talk after
    a trigger with the next reading given."""

    WORDS = {0: "236A10", 1: "ERS" + "0" * 26, 9: "WRS" + "0" * 10,
             3: "MSTG05,1,0K0M000,0N0R1T4,1,0,0V0Y0",
             4: "IMPL,06F0,0O0P0S3W1Z0", 5: "ICP0100.00E-06"}

    def __init__(self, readings=(), **words):
        super().__init__()
        self.connected = True
        self.words = dict(self.WORDS)
        self.words.update({int(k[1:]): v for k, v in words.items()})
        self.readings = list(readings)
        self.pending = None

    def _write(self, text):
        if text.startswith("U"):
            self.pending = int(text[1:-1])

    def _read(self, timeout_s):
        if self.pending is not None:
            which, self.pending = self.pending, None
            return self.words[which]
        return self.readings.pop(0)

    def clear(self):
        return True

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False


def test_the_units_status_words_pass_the_reset_check(check):
    driver = Keithley236(Replays(U4="IMPL,00F0,0O0P0S3W1Z0"))
    driver.reset()
    check("identity", driver.identify() == "236A10")


def test_the_units_readbacks_parse(check):
    driver = Keithley236(Replays())
    check("U5 ICP0100.00E-06 is 100 uA",
          driver.read_current_limit() == pytest.approx(1e-4))
    check("U4 L,06 is the 100 uA range",
          driver.read_measure_current_range() == 1e-4)
    driver = Keithley236(Replays(U4="VMPL,02F1,0O0P0S3W1Z0"))
    check("VMP L,02 is the 11 V range",
          driver.read_measure_voltage_range() == 11.0)


@pytest.mark.parametrize("reply,expected", [
    ("NSDCV+0.1000E+00,NMDCI-000.006E-06", -6e-9),
    ("NSDCV+0.0000E+00,NMDCI+000.007E-06", 7e-9),
    ("NSDCV+0.0000E+00,NMDCI-01.8621E-09", -1.8621e-9),
    ("NSDCV+0.0500E+00,NMDCI+0.28781E-09", 0.28781e-9),
])
def test_the_units_readings_parse(check, reply, expected):
    driver = Keithley236(Replays(readings=[reply]))
    volts, amps = driver.measure()
    check(f"{reply}", volts is None and amps == pytest.approx(expected),
          f"{volts} {amps}")
    check("not a trip", driver.compliance_tripped() is False)


def test_the_units_reading_at_compliance(check):
    driver = Keithley236(Replays(
        readings=["OSDCI+1.0000E-06,OMDCV+0.99977E+00"]))
    driver._mode = "current"
    volts, amps = driver.measure()
    check("a real reading at the limit", volts == pytest.approx(0.99977)
          and amps is None, f"{volts} {amps}")
    check("flagged", driver.compliance_tripped() is True)



# ---------------------------------------------------------------------
# ready for a trigger (the 2026-11-16 bench sitting)
# ---------------------------------------------------------------------

def _sweep(driver, levels=(0.2, 0.4, 0.6, 0.8, 1.0)):
    for level in levels:
        driver.set_voltage_level(level)
        driver.measure()


def test_no_trigger_goes_out_before_the_unit_is_ready(check):
    driver, transport = energised(recover_s=0.01)
    _sweep(driver)
    check("no trigger was ever lost", transport.overruns == 0,
          f"{transport.overruns}")
    check("the ready bit was asked", transport.polls > 0)


def test_without_the_wait_the_bench_failure_comes_back(check):
    """What the sitting saw: the measuring trigger straight after the
    extra cycle's reading, no reading, a latched link."""
    driver, transport = energised(recover_s=0.01)
    driver._wait_until_ready = lambda: None
    with pytest.raises(TransportDesynchronised):
        _sweep(driver)
    check("a trigger overrun", transport.overruns >= 1)


def test_a_transport_that_cannot_poll_waits_the_gap(check):
    driver, transport = energised(recover_s=0.02, can_poll=False)
    _sweep(driver)
    check("no trigger lost", transport.overruns == 0, f"{transport.overruns}")
    check("and no poll attempted to succeed", transport.polls == 0)


def test_a_unit_that_never_gets_ready_is_refused_not_triggered(
        check, monkeypatch):
    from smuniversal_lab_suite.drivers import keithley_236
    monkeypatch.setattr(keithley_236, "READY_TIMEOUT_S", 0.05)
    driver, transport = energised()
    transport.never_ready = True
    transport.sent.clear()
    with pytest.raises(RuntimeError, match="ready for a trigger"):
        driver.measure()
    check("no H0X sent", "H0X" not in transport.sent, f"{transport.sent}")
    check("and the link is still usable", driver.read_error() == (0, ""))


def test_the_transport_serial_poll_contract(check):
    from smuniversal_lab_suite.core.transports.visa_transport import (
        VisaTransport,
    )

    class Plain(Transport):
        def _write(self, text):
            pass

        def _read(self, timeout_s):
            return ""

        def connect(self, address, **kwargs):
            pass

        def close(self):
            pass

    plain = Plain()
    plain.connected = True
    with pytest.raises(NotImplementedError):
        plain.serial_poll()

    class Resource:
        def read_stb(self):
            return 0x50

    visa = VisaTransport()
    visa.res, visa.connected = Resource(), True
    check("VISA reads the status byte", visa.serial_poll() == 0x50)
