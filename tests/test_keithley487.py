"""Keithley 487 - command spellings, reply parsing, and the silent drops.

Modelled on `test_tsx_p.py`: the assertions are about the exact strings
on the wire and the *absence* of everything else. The driver was written
from a scanned manual with no script behind it and before the unit had
answered anything, so the strings are all there is to check offline.

The traps this file exists for:

  * the dialect is Keithley's device-dependent commands, not SCPI - one
    `*RST` or one colon reaching the instrument is an illegal command;
  * a level beyond the selected source range is **ignored in silence**,
    with the previous level left on the sample;
  * a device clear restores the *saved* defaults - zero check on, an
    external trigger - and a reset that does not undo every one of them
    reads zeros, or yesterday's reading, without complaint;
  * the error and source-error words latch and empty when read;
  * a reading is triggered by asking for it, so it must be a bare talk
    with nothing sent in front of it.
"""
import re

import pytest

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.ranges import AUTO, RangeError, RangePlan
from smuniversal_lab_suite.core.readback import UNVERIFIED
from smuniversal_lab_suite.core.transports.base import (
    Transport,
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.keithley_487 import Keithley487
from smuniversal_lab_suite.drivers.registry import (
    KNOWN_SMUS,
    driver_by_display_name,
    driver_for_idn,
)

#: The factory defaults as Table 4-3 lists them: zero check on, both
#: filters, multiple-on-external-trigger, 0 V on the 50 V range with
#: the 25 uA limit. What a clear brings back unless somebody saved
#: something else.
FACTORY = {"A": "0", "B": "0", "C": "1", "F": "0", "G": "0", "K": "0",
           "M": "000", "O": "0", "P": "3", "S": "1", "T": "6", "Y": "0",
           "Z": "00"}

#: Full scales, as the manual gives them and not read from the driver.
SOURCE_FS = {0: 50.5, 1: 505.0}
LIMITS = {0: 25e-6, 1: 2.5e-3}
MEASURE_FS = {1: 2e-9, 2: 2e-8, 3: 2e-7, 4: 2e-6, 5: 2e-5, 6: 2e-4,
              7: 2e-3}

#: The U1 flags the fake sets, by position (manual Figure 4-7).
IDDC, IDDCO, TRIGGER_OVERRUN, V_CONFLICT, V_SOURCE = 0, 1, 4, 11, 12

_COMMAND = re.compile(r"([A-Z])([^A-Z]*)")


class Fake487(Transport):
    """A 487 that behaves the way its manual says it does.

    `resistance` is what sits between the source and the ammeter, in
    ohms; None is an open circuit. `stuck` names U0 letters whose
    commands the instrument ignores, to stand in for a saved default the
    reset fails to override; `reject` names letters it refuses with an
    IDDCO. `interlock_open` is a fitted interlock with the lid up.

    It reproduces the race the bench found on 2026-10-14. In `T1` every
    talk is a trigger - a status query too - and a conversion is still
    running when the next talk arrives straight after: that talk's
    trigger is an overrun, and if it was asking for a reading, no reading
    is ever sent (a timeout). And the error word survives a device clear.
    """

    def __init__(self, model="487", resistance=1e6, interlock_open=False,
                 stuck=(), reject=()):
        super().__init__()
        self.connected = True
        self.model = model
        self.resistance = resistance
        self.interlock_open = interlock_open
        self.stuck = set(stuck)
        self.reject = set(reject)
        self.sent = []          # every write, verbatim
        self.events = []        # writes and talks, in order
        self.talks = 0          # bare reads
        self.converting = False  # a talk-triggered conversion in progress
        self.buffer = ""        # commands received without an X yet
        self.zero_corrected = set()   # ranges C2X has corrected
        self.cleared = 0
        self.pending = None     # a U word waiting to be read
        self.last_reading = "NDCI+0.00000E+00"
        self.u1 = [0] * 13
        self.u9 = [0, 0]
        self.state = dict(FACTORY)
        self.level, self.v_range, self.v_limit = 0.0, 0, 0
        self.autorange, self.m_range = True, 1
        self.delay = 0.0

    # ---- what a talk returns ----
    def _status_word(self, which):
        if which == 0:
            s = self.state
            return (f"487A{s['A']}B{s['B']}C{s['C']}F{s['F']}G{s['G']}H00J0"
                    f"K{s['K']}M{s['M']}N000O{s['O']}P{s['P']}"
                    f"R{int(self.autorange)}{self.m_range}S{s['S']}"
                    f"T{s['T']}V{self.v_range}{self.v_limit}Y{s['Y']}"
                    f"Z{s['Z']}c0")
        if which == 1:
            word, self.u1 = "".join(map(str, self.u1)), [0] * 13
            return f"{self.model}{word}"
        if which == 2:
            return f"{self.model}A03  "
        if which == 9:
            word, self.u9 = "".join(map(str, self.u9)), [0, 0]
            return f"{self.model}{word}"
        raise AssertionError(f"U{which} not modelled")

    def current(self):
        """What flows, with the current limit clamping it."""
        if self.state["O"] != "1" or self.resistance is None:
            return 0.0
        amps = self.level / self.resistance
        limit = LIMITS[self.v_limit]
        if abs(amps) > limit:
            self.u9[0] = 1
            amps = limit if amps > 0 else -limit
        return amps

    def _take_reading(self):
        amps = 0.0 if self.state["C"] == "1" else self.current()
        if self.autorange:
            fitting = [n for n, fs in MEASURE_FS.items() if fs >= abs(amps)]
            self.m_range = fitting[0] if fitting else 7
        if abs(amps) > MEASURE_FS[self.m_range]:
            return "ODCI+9.87000E+37"
        prefix = "Z" if self.state["Z"][:1] == "1" else "N"
        function = "OHM" if self.state["F"] == "1" else "DCI"
        return f"{prefix}{function}{amps:+.5E}"

    # ---- the wire ----
    def _write(self, text):
        self.sent.append(text)
        self.events.append(text)
        # Held until an X arrives, then executed with it (manual 4.2.22).
        # A `*IDN?` sent on its own is not refused - it waits in here and
        # spoils the next string that does end in X.
        body = self.buffer + text.strip()
        if not body.endswith("X"):
            self.buffer = body
            return
        self.buffer = ""
        commands = _COMMAND.findall(body[:-1])
        # One illegal command voids the string (manual 4.1).
        for letter, option in commands:
            if letter not in "ABCDFGHJKLMNOPQRSTUVWYZ" or "*" in option \
                    or ":" in option or "?" in option:
                self.u1[IDDC] = 1
                return
        for letter, option in commands:
            self._execute(letter, option.strip())

    def _execute(self, letter, option):
        if letter in self.stuck:
            return
        if letter in self.reject:
            self.u1[IDDCO] = 1
            return
        if letter == "T":
            # A change of trigger mode lets any conversion finish.
            self.converting = False
        if letter == "U":
            # Which word; it is composed at the talk, as the bench showed
            # (the poll that overran reported its own overrun).
            self.pending = int(option)
        elif letter == "V":
            fields = (option.split(",") + ["", "", ""])[:3]
            level = float(fields[0]) if fields[0] else self.level
            v_range = int(fields[1]) if fields[1] else self.v_range
            limit = int(fields[2]) if fields[2] else self.v_limit
            if abs(level) > 505:
                self.u1[IDDCO] = 1
                return
            if abs(level) > SOURCE_FS[v_range]:
                # Ignored, all of it. The previous level stays.
                self.u1[V_CONFLICT] = 1
                return
            self.level, self.v_range, self.v_limit = level, v_range, limit
        elif letter == "O":
            if option == "1" and self.interlock_open:
                self.u1[V_SOURCE] = 1
                self.u9[1] = 1
                return
            self.state["O"] = option
        elif letter == "R":
            value = int(option)
            if value == 0:
                self.autorange = True
            elif value == 10:
                self.autorange = False
            elif 1 <= value <= 7:
                self.autorange, self.m_range = False, value
            else:
                self.u1[IDDCO] = 1
        elif letter == "W":
            self.delay = float(option)
        elif letter == "C" and option == "2":
            # Zero correct, then zero check back to what it was (4.2.3).
            self.zero_corrected.add(self.m_range)
        elif letter in self.state:
            self.state[letter] = option
        elif letter == "L":
            raise AssertionError("L must never be sent: it rewrites the "
                                 "saved defaults of a shared instrument")

    def _talk_triggers(self):
        """In T1 this talk is a trigger. True if it is a usable one."""
        if self.state["T"] != "1":
            return False
        if self.converting:
            self.u1[TRIGGER_OVERRUN] = 1
            return False
        self.converting = True
        return True

    def _read(self, timeout_s):
        self.events.append("<talk>")
        if self.pending is not None:
            which, self.pending = self.pending, None
            # A status word still triggers in T1; its conversion runs on
            # with nobody waiting for it.
            self._talk_triggers()
            return self._status_word(which)
        if self.state["T"] == "1":
            if not self._talk_triggers():
                raise TimeoutError("trigger overrun: no reading was taken")
            self.converting = False      # this talk collects its own
            self.last_reading = self._take_reading()
        # Any other trigger mode: whatever was last converted. Exactly
        # the stale reading a wrong trigger mode would hand back.
        return self.last_reading

    def read(self, timeout_s=3.0):
        self.talks += 1
        return super().read(timeout_s)

    def clear(self):
        """SDC: back to the saved defaults - here, the factory ones.

        The error and source-error words are NOT cleared, as on the bench.
        """
        self.cleared += 1
        self.converting = False
        self.buffer = ""
        self.state = dict(FACTORY)
        self.level, self.v_range, self.v_limit = 0.0, 0, 0
        self.autorange = True
        self.pending = None
        return True

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False


def make(**kwargs):
    transport = Fake487(**kwargs)
    driver = Keithley487(transport)
    return driver, transport


def ready(**kwargs):
    driver, transport = make(**kwargs)
    driver.reset()
    transport.sent.clear()
    return driver, transport


# ---------------------------------------------------------------------
# identity and the dialect
# ---------------------------------------------------------------------

def test_it_is_registered_but_never_auto_detected(check):
    check("in the SMU fleet", Keithley487 in KNOWN_SMUS)
    check("reachable by name, as the manual dropdown asks",
          driver_by_display_name("Keithley 487") is Keithley487)
    check("no MODEL_IDS", Keithley487.MODEL_IDS == [])
    check("nothing resolves to it",
          driver_for_idn("487A03") is None
          and driver_for_idn("KEITHLEY,487,1,A03") is None)


def test_identify_asks_u2_not_idn(check):
    driver, transport = make()
    reply = driver.identify()
    check("the model and firmware, blanks stripped", reply == "487A03",
          repr(reply))
    check("asked with U2X", transport.sent == ["U2X"], f"{transport.sent}")


def test_reset_refuses_a_486_before_configuring_it(check):
    driver, transport = make(model="486")
    with pytest.raises(RuntimeError, match="486"):
        driver.reset()
    check("only the identity question went out",
          transport.sent == ["U2X"], f"{transport.sent}")


def test_nothing_scpi_ever_reaches_it(check):
    driver, transport = make()
    driver.reset()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 10.0, AUTO))
    driver.set_current_limit(25e-6)
    driver.set_voltage_level(1.0)
    driver.output_on()
    driver.measure()
    driver.compliance_tripped()
    driver.read_error()
    driver.output_off()
    for text in transport.sent:
        check(f"{text!r} is a device-dependent command",
              "*" not in text and ":" not in text and "?" not in text
              and text.endswith("X"))
    check("and one command per X",
          all(len(_COMMAND.findall(t[:-1])) == 1 for t in transport.sent),
          f"{[t for t in transport.sent if len(_COMMAND.findall(t[:-1])) > 1]}")
    check("nothing illegal along the way", transport.u1 == [0] * 13,
          f"{transport.u1}")


# ---------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------

def test_reset_undoes_every_saved_default_it_depends_on(check):
    driver, transport = make()
    driver.reset()
    check("cleared first", transport.cleared == 1)
    state = transport.state
    for letter, want, why in (
            ("C", "0", "zero check off"), ("F", "0", "V/I ohms off"),
            ("Z", "0", "rel off"), ("T", "3", "idle: one-shot on GET"),
            ("P", "0", "filters off"), ("O", "0", "standby"),
            ("G", "0", "prefixed ASCII"), ("B", "0", "A/D readings")):
        check(f"{why} ({letter})", state[letter] == want,
              f"{letter}{state[letter]}")
    check("0 V, 50 V range, 25 uA limit",
          (transport.level, transport.v_range, transport.v_limit)
          == (0.0, 0, 0))
    check("autorange", transport.autorange)
    check("standby is the first thing configured",
          [t for t in transport.sent if not t.startswith("U")][0] == "O0X",
          f"{transport.sent[:5]}")
    check("the trigger mode is set last",
          [t for t in transport.sent if not t.startswith("U")][-1] == "T3X",
          f"{transport.sent}")
    check("the saved defaults are never touched",
          not any(t.startswith("L") for t in transport.sent))


def test_a_reset_that_did_not_take_is_refused(check):
    """A saved default the commands failed to override - here zero
    check - reads as zero forever. It has to stop the instrument."""
    driver, _ = make(stuck={"C"})
    with pytest.raises(RuntimeError, match="zero check"):
        driver.reset()


def test_a_reset_the_instrument_complained_about_is_refused(check):
    driver, _ = make(reject={"K"})
    with pytest.raises(RuntimeError, match="IDDCO"):
        driver.reset()


def test_flags_left_by_an_earlier_session_do_not_fail_the_reset(check):
    """Seen 2026-10-14: a reading lost in one session left its trigger
    overrun latched through the device clear, and the next reset
    reported it as its own."""
    driver, transport = make()
    transport.u1[TRIGGER_OVERRUN] = 1
    transport.u9[0] = 1
    driver.reset()
    check("and the instrument is ready", transport.state["T"] == "3")


# ---------------------------------------------------------------------
# what it can and cannot be asked to do
# ---------------------------------------------------------------------

def test_voltage_only(check):
    driver, transport = ready()
    driver.set_source_function("voltage")
    check("voltage sends nothing - there is no choice to make",
          transport.sent == [])
    with pytest.raises(ValueError, match="only source voltage"):
        driver.set_source_function("current")
    with pytest.raises(NotImplementedError):
        driver.set_current_level(1e-6)
    with pytest.raises(NotImplementedError):
        driver.set_voltage_limit(1.0)
    check("declared", Keithley487.source_functions() == ("voltage",))
    check("not a current source", not Keithley487.supports_current_sourcing())


def test_the_compliance_is_a_menu(check):
    driver, transport = ready()
    driver.set_current_limit(2.5e-3)
    check("2.5 mA is option 1", transport.v_limit == 1)
    driver.set_current_limit(25e-6)
    check("25 uA is option 0", transport.v_limit == 0)
    transport.sent.clear()
    with pytest.raises(LimitError, match="nothing else"):
        driver.set_current_limit(1e-4)
    check("refused before the wire", transport.sent == [])
    with pytest.raises(LimitError):
        driver.validate_source_point(voltage=1.0, current=1e-4,
                                     sourcing="voltage")
    driver.validate_source_point(voltage=1.0, current=25e-6,
                                 sourcing="voltage")
    with pytest.raises(LimitError, match="cannot source current"):
        driver.validate_source_point(current=1e-6, voltage=1.0,
                                     sourcing="current")
    check("the menu is declared safest first",
          Keithley487.compliance_choices("current") == (25e-6, 2.5e-3))
    check("and is a protection only",
          not Keithley487.compliance_sets_measure_range())


def test_a_level_beyond_the_range_is_refused_not_dropped(check):
    """The instrument would ignore it and keep the old level on the
    sample. So the driver must never send it."""
    driver, transport = ready()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 10.0, AUTO))
    driver.set_voltage_level(5.0)
    transport.sent.clear()
    with pytest.raises(RangeError, match="50.5 V source range"):
        driver.set_voltage_level(60.0)
    check("nothing sent", transport.sent == [])
    check("the instrument still holds the old level",
          transport.level == 5.0)


def test_ranging(check):
    driver, transport = ready()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 10.0, AUTO))
    check("10 V lands on the 50 V range at 0 V",
          "V0,0,0X" in transport.sent, f"{transport.sent}")
    check("measurement on autorange", "R0X" in transport.sent)
    driver.set_voltage_level(-10.0)
    check("the level reaches the instrument", transport.level == -10.0)

    transport.sent.clear()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 100.0, 3e-9))
    check("100 V takes the 500 V range", transport.v_range == 1)
    check("and the level went to 0 V with it", transport.level == 0.0)
    check("3 nA takes the 20 nA range", "R2X" in transport.sent,
          f"{transport.sent}")
    driver.set_voltage_level(100.0)
    check("100 V reaches the instrument", transport.level == 100.0)
    check("no conflict raised", transport.u1[V_CONFLICT] == 0)

    with pytest.raises(RangeError):
        driver.apply_ranges(RangePlan.for_sourcing("voltage", 600.0, AUTO))
    with pytest.raises(RangeError):
        driver.apply_ranges(RangePlan.for_sourcing("current", 1e-6, 1.0))


# ---------------------------------------------------------------------
# readings
# ---------------------------------------------------------------------

def test_a_reading_is_one_talk_in_one_shot_on_talk(check):
    driver, transport = ready(resistance=1e6)
    driver.set_voltage_level(1.0)
    driver.output_on()
    transport.events.clear()
    volts, amps = driver.measure()
    check("no voltage, ever", volts is None)
    check("1 V across 1 Mohm", amps == pytest.approx(1e-6), f"{amps}")
    check("T1 for the talk, then straight back to idle",
          transport.events == ["T1X", "<talk>", "T3X"],
          f"{transport.events}")


def test_back_to_idle_even_when_the_reading_fails(check):
    driver, transport = ready()
    driver.output_on()

    def no_reading(timeout_s):
        raise TimeoutError("no reply")

    transport._read = no_reading
    with pytest.raises(TransportDesynchronised):
        driver.measure()
    check("T3 was still sent", transport.sent[-1] == "T3X",
          f"{transport.sent[-3:]}")


@pytest.mark.parametrize("reply, expected", [
    ("NDCI+1.23456E-09", 1.23456e-09),
    ("NDCI-4.50000E-03", -4.5e-3),
    ("  NDCI+0.00000E+00\r\n", 0.0),
])
def test_readings_parse(reply, expected):
    assert Keithley487._parse_reading(reply) == pytest.approx(expected)


def test_an_overflow_is_no_reading_by_either_sign(check):
    check("O prefix", Keithley487._parse_reading("ODCI+1.00000E-03") is None)
    check("9.87E37 in the field",
          Keithley487._parse_reading("NDCI+9.87000E+37") is None)


@pytest.mark.parametrize("reply, why", [
    ("NOHM+1.00000E+06", "ohms"),
    ("ZDCI+1.00000E-09", "rel"),
    ("+1.00000E-09", "unexpected"),
    ("", "unexpected"),
])
def test_a_reading_in_the_wrong_shape_is_loud(reply, why):
    with pytest.raises(ValueError, match=why):
        Keithley487._parse_reading(reply)


def test_status_queries_between_readings_trigger_nothing(check):
    """The 2026-10-14 race, closed. Polls as fast as a checkup drains the
    error word, a reading after each, and every reading is fresh."""
    driver, transport = ready(resistance=1e6)
    driver.output_on()
    for volts in (1.0, 2.0, 3.0):
        driver.set_voltage_level(volts)
        for _ in range(20):
            driver.read_error()
            driver.compliance_tripped()
        check(f"a fresh reading at {volts} V",
              driver.measure()[1] == pytest.approx(volts / 1e6))
    check("no overrun", transport.u1[TRIGGER_OVERRUN] == 0)


def test_idling_in_one_shot_on_talk_loses_readings(check):
    """What the driver did until 2026-10-14, so the fake is known to
    model it: in T1 a status query is a trigger, the poll after it is
    an overrun, and a reading asked for then never comes."""
    driver, transport = ready()
    driver.output_on()
    transport.state["T"] = "1"
    driver.read_error()
    code, message = driver.read_error()
    check("the second poll overran", "trigger overrun" in message, message)
    with pytest.raises(TransportDesynchronised):
        transport.read()


def test_any_other_trigger_mode_hands_back_stale_readings(check):
    """Why a reading is always taken in T1: in a mode where the talk is
    not the trigger, it returns the last conversion, which looks exactly
    like a reading."""
    driver, transport = ready(resistance=1e6)
    driver.set_voltage_level(1.0)
    driver.output_on()
    first = driver.measure()[1]
    driver.set_voltage_level(2.0)
    check("a stale reading from a bare talk in idle",
          Keithley487._parse_reading(transport.read()) == first)


# ---------------------------------------------------------------------
# output
# ---------------------------------------------------------------------

def test_off_is_zero_volts_then_standby(check):
    driver, transport = ready()
    driver.set_voltage_level(10.0)
    driver.output_on()
    transport.sent.clear()
    driver.output_off()
    check("0 V first, then the relay",
          transport.sent == ["V0,0,0X", "O0X"], f"{transport.sent}")
    check("standby", transport.state["O"] == "0")


def test_an_open_interlock_stops_the_output_on(check):
    driver, transport = ready(interlock_open=True)
    with pytest.raises(RuntimeError, match="interlock"):
        driver.output_on()
    check("still in standby", transport.state["O"] == "0")


def test_a_clamp_is_reported_once(check):
    """U9 latches "has been in current limit" and empties on read."""
    driver, transport = ready(resistance=1e3)
    driver.set_voltage_level(1.0)   # 1 mA into a 25 uA limit
    driver.output_on()
    _, amps = driver.measure()
    check("held at the limit", amps == pytest.approx(25e-6), f"{amps}")
    check("tripped", driver.compliance_tripped() is True)
    check("and cleared by being read", driver.compliance_tripped() is False)


def test_the_interlock_opening_mid_run_stops_it(check):
    driver, transport = ready()
    driver.output_on()
    transport.u9[1] = 1
    with pytest.raises(RuntimeError, match="interlock opened"):
        driver.compliance_tripped()


# ---------------------------------------------------------------------
# errors and readback
# ---------------------------------------------------------------------

def test_the_error_word_names_its_flags_and_empties(check):
    driver, transport = ready()
    transport.u1[V_CONFLICT] = 1
    code, message = driver.read_error()
    check("a nonzero code", code == V_CONFLICT + 1, f"{code}")
    check("named", "V-source conflict" in message, message)
    check("then empty", driver.read_error() == (0, ""))


def test_the_settings_are_read_back_from_u0(check):
    driver, transport = ready()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 100.0, 3e-9))
    driver.set_current_limit(2.5e-3)
    check("limit", driver.read_current_limit() == 2.5e-3)
    check("source range", driver.read_source_voltage_range() == 505.0)
    check("measure range", driver.read_measure_current_range() == 2e-8)
    answer = driver.verify_compliance("voltage", 2.5e-3)
    check("graded, and not trusted until benched",
          answer.state == UNVERIFIED, f"{answer.state}")
    check("a wrong limit is a mismatch",
          driver.verify_compliance("voltage", 25e-6).is_safety_event)


def test_integration_snaps_onto_its_two_settings(check):
    driver, transport = ready()
    for asked, recorded, sent in ((0.01, 0.1, "S0X"), (0.2, 0.1, "S0X"),
                                  (0.5, 1.0, "S1X"), (10, 1.0, "S1X")):
        check(f"{asked} records {recorded}",
              Keithley487.clamp_nplc(asked) == recorded)
        transport.sent.clear()
        driver.set_nplc(asked)
        check(f"{asked} sends {sent}", transport.sent == [sent],
              f"{transport.sent}")


def test_a_failed_talk_latches_the_transport(check):
    class Silent(Fake487):
        def _read(self, timeout_s):
            raise TimeoutError("no reply")

    driver = Keithley487(Silent())
    with pytest.raises(TransportDesynchronised):
        driver.measure()
    check("latched", driver.transport.is_desynchronised)
    with pytest.raises(TransportDesynchronised):
        driver.transport.read()


# ---------------------------------------------------------------------
# what the first bench session (2026-10-14) taught
# ---------------------------------------------------------------------

def test_the_checkup_passes_on_a_well_behaved_487(check):
    """The first bench checkup failed twice on readings that were right.

    `measure()` returned `(None, 9e-09)` - no voltage, because nothing on
    the 487 measures one, and 9 nA of open-circuit noise on the 200 uA
    range - and the checkup called every None a reply that would not
    parse. The every-driver checkup test only asks that a checkup
    finishes, so it never saw it. This asks for no failures.
    """
    from smuniversal_lab_suite.core.checkup import Checkup

    checkup = Checkup(Keithley487(Fake487(resistance=None)),
                      open_circuit=True)
    checkup.run()
    failed = [f"{r.name}: {r.detail}" for r in checkup.results
              if r.severity == "fail"]
    check("no failures", not failed, "; ".join(failed))
    check("the open-circuit current was graded",
          any(r.name == "open-circuit current is near zero"
              and r.severity == "pass" for r in checkup.results))
    check("no 4-wire warning on a 2-wire instrument",
          checkup._sensing_note is None, f"{checkup._sensing_note!r}")


def test_a_missing_voltage_is_still_a_failure_where_one_is_promised(check):
    """The relaxation is the 487's declaration, not a blanket one."""
    from smuniversal_lab_suite.core.checkup import Checkup

    class Promises(Keithley487):
        MEASURE_FUNCTIONS = ("voltage", "current")

    checkup = Checkup(Promises(Fake487(resistance=None)), open_circuit=True)
    checkup.run(tiers=(2, 3), burst=False)
    check("a None voltage fails there",
          any(r.name.startswith("measure()") and r.severity == "fail"
              for r in checkup.results),
          f"{[(r.name, r.severity) for r in checkup.results]}")


@pytest.mark.parametrize("reply, firmware", [
    ("487B07", "B07"),       # read off the unit, 2026-10-14
    ("486A03", "A03"),       # the manual's example
])
def test_the_firmware_comes_out_of_the_u2_reply(reply, firmware):
    from smuniversal_lab_suite.core.provenance import firmware_from_idn
    assert firmware_from_idn(reply) == firmware


def test_the_real_replies_parse(check):
    """Verbatim from the 2026-10-14 trace. The readings come back in
    engineering form - `000.009E-06` - not the `1.23456E-03` of the
    manual's figure, and both parse."""
    check("9 nA", Keithley487._parse_reading("NDCI+000.009E-06")
          == pytest.approx(9e-9))
    check("-1 nA", Keithley487._parse_reading("NDCI-000.001E-06")
          == pytest.approx(-1e-9))
    word = "487A0B0C0F0G0H17J0K0M000N000O0P0R11S1T1V00Y0Z00c0"
    driver, transport = make()
    transport._status_word = lambda which: word
    fields = driver._machine_status()
    check("fields by letter",
          (fields["C"], fields["R"], fields["T"], fields["V"])
          == ("0", "11", "1", "00"), f"{fields}")


def test_the_settle_is_kept_by_the_driver_never_by_w(check, monkeypatch):
    """The instrument's trigger delay loses readings - 4 of 432 at 10 ms,
    none of 1152 at 0, on 2026-10-14 - so the settle is a wait before
    each reading's T1X and `W` never leaves 0."""
    import smuniversal_lab_suite.drivers.keithley_487 as module

    driver, transport = ready()
    driver.output_on()
    slept = []
    monkeypatch.setattr(module.time, "sleep",
                        lambda seconds: (slept.append(seconds),
                                         transport.events.append(
                                             f"sleep {seconds:g}")))
    transport.sent.clear()
    driver.set_source_delay(0.01)
    check("nothing sent for it", transport.sent == [], f"{transport.sent}")
    transport.events.clear()
    driver.measure()
    check("the wait comes before the trigger mode changes",
          transport.events[:3] == ["sleep 0.01", "T1X", "<talk>"],
          f"{transport.events}")
    check("W is still 0 on the instrument", transport.delay == 0.0)
    driver.set_source_delay(0)
    slept.clear()
    driver.measure()
    check("no wait when none is asked for", slept == [], f"{slept}")


def test_nothing_the_driver_does_sets_a_trigger_delay(check):
    driver, transport = make()
    driver.reset()
    driver.apply_ranges(RangePlan.for_sourcing("voltage", 10.0, AUTO))
    driver.set_current_limit(25e-6)
    driver.set_source_delay(0.25)
    driver.set_nplc(1)
    driver.output_on()
    driver.measure()
    driver.output_off()
    sent_w = [t for t in transport.sent if t.startswith("W")]
    check("only W0", sent_w == ["W0X"], f"{sent_w}")
