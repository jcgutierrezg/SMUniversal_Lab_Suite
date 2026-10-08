"""Aim-TTi TSX-P - command spellings, reply parsing and the error path.

Modelled on `test_72_13200.py`: the assertions are about the exact
strings on the wire, and about the *absence* of everything else. This
driver was written from a manual with no script behind it and before
either unit had answered a query, so the strings are all there is to
check offline - and a test asserting only that a number came back would
pass against a driver that sent nothing the instrument understood.

The traps this file exists for:

  * replies carry text at one end or the other - `12.55V`, `V 12.55` -
    and a raw one handed to `drop_sentinel()` becomes `None`: a reading
    that existed, silently discarded;
  * the dialect is not SCPI, and one colon reaching the instrument is a
    command error;
  * errors live in three registers that each empty when read, so a
    decoder that reads the wrong one reports "no error" for ever;
  * "did it clamp?" is an event rather than a state.
"""
import pytest

from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.readback import (
    MISMATCHED,
    UNVERIFIED,
)
from smuniversal_lab_suite.core.transports.base import (
    Transport,
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers.aimtti_tsx_p import (
    EXECUTION_ERRORS,
    AimTTiTSX1820P,
    AimTTiTSX3510P,
    AimTTiTSXP,
)
from smuniversal_lab_suite.drivers.base_supply import CC, CROSSED, CV
from smuniversal_lab_suite.drivers.registry import driver_for_idn

#: The 1820's is the real reply, read off the unit on 2026-10-08. The
#: 3510's has **not** been read: it is the 1820's with the model field
#: changed, which is what the manual's form predicts and nothing more.
#: What the tests rely on is only the model field, which is what
#: `MODEL_IDS` matches.
IDNS = {
    "TSX3510P": "THURLBY-THANDAR,TSX3510P,0,0.00",
    "TSX1820P": "THURLBY-THANDAR,TSX1820P,0,1.20",
}

#: The one identity the manuals do print: the Series II example. Kept as
#: a second shape the registry has to resolve.
SERIES_II_IDN = "THURLBY THANDAR,TSX1820P,389730,1.00 - 1.00"

#: (maximum volts, maximum amps, lowest trip, highest trip) per model,
#: as the fake enforces them - which is the specification's figures and
#: deliberately not read from the driver under test.
ENVELOPES = {
    "TSX3510P": (35.3, 10.2, 1.0, 40.0),
    "TSX1820P": (18.15, 20.2, 1.0, 25.0),
}


class SupplyTransport(Transport):
    """A TSX-P that answers the way the manual says it does.

    Every reply carries its unit or its header, because that is the
    point: a fake returning bare floats would let a driver that never
    strips either pass.

    It **rejects** what the real instrument rejects - a setting outside
    its range, and anything it cannot parse - and files the complaint in
    the registers rather than raising. A fake that accepted everything
    would let a SCPI spelling through as if it had landed.

    `load_ohms` is what is across the terminals. None is nothing, which
    is the checkup's premise; a number lets a test put the supply into
    current limit.

    `reasserts` picks between the two readings of the limit register the
    manual leaves open: False is "reports an entry once", True is "the
    bit comes back while the condition holds".
    """

    def __init__(self, model="TSX3510P", load_ohms=None, reasserts=False,
                 volts_error=0.0, settles=True, headers="series1"):
        super().__init__()
        self.connected = True
        self.model = model
        self.vmax, self.imax, self.ovp_low, self.ovp_high = ENVELOPES[model]
        self.load_ohms = load_ohms
        self.reasserts = reasserts
        #: Added to the voltmeter, to model a readback that is wrong.
        self.volts_error = volts_error
        #: False makes a verified set time out.
        self.settles = settles
        self.headers = headers
        self.sent = []
        self.v_set = 0.0
        self.i_set = 0.01
        self.ovp = self.ovp_high
        self.output = False
        self.damping = False
        self.esr = 0
        self.eer = 0
        self.qer = 0
        self.lsr = 0
        self._mode = None
        self._reply = ""

    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    # ---- the output, as a load line ----
    def _operating_point(self):
        """(volts, amps, mode) at the terminals right now."""
        if not self.output:
            return 0.0, 0.0, None
        if self.load_ohms is None:
            return self.v_set, 0.0, CV
        wanted = self.v_set / self.load_ohms
        if wanted > self.i_set:
            return self.i_set * self.load_ohms, self.i_set, CC
        return self.v_set, wanted, CV

    def _note_mode(self):
        """Raise a limit event when the regulation mode is entered."""
        volts, _, mode = self._operating_point()
        if self.output and volts > self.ovp:
            # A trip, as the manual describes one: the output shuts
            # down and the limit register says so. That it also files
            # execution error 118 is this fake's guess, and nothing
            # under test depends on it.
            self.output = False
            self.lsr |= 4
            self._reject(118)
            mode = None
        if mode is not None and mode != self._mode:
            self.lsr |= 1 if mode == CC else 2
        self._mode = mode

    def _reject(self, number):
        self.esr |= 16
        self.eer = number

    # ---- writes ----
    def _write(self, text):
        self.sent.append(text)
        self._reply = ""
        command = text.strip()
        upper = command.upper()
        head, _, argument = upper.partition(" ")

        if head.endswith("?"):
            self._reply = self._answer(head)
            return
        try:
            value = float(argument) if argument else None
        except ValueError:
            value = None

        if head == "*RST":
            self.v_set, self.i_set, self.ovp = 0.0, 0.01, self.ovp_high
            self.output = self.damping = False
            self._mode = None
        elif head == "*CLS":
            self.esr = self.eer = self.qer = self.lsr = 0
        elif head in ("V", "VV") and value is not None:
            if value > self.vmax:
                self._reject(100)
            elif value < 0:
                self._reject(102)
            else:
                self.v_set = round(value, 2)
                if head == "VV" and not self.settles:
                    self.esr |= 8
                self._note_mode()
        elif head == "I" and value is not None:
            if value > self.imax:
                self._reject(101)
            elif value < 0.01:
                self._reject(103)
            else:
                self.i_set = round(value, 2)
                self._note_mode()
        elif head == "OVP" and value is not None:
            if value > self.ovp_high:
                self._reject(108)
            elif value < self.ovp_low:
                self._reject(107)
            else:
                self.ovp = round(value, 2)
        elif head == "OP" and value in (0.0, 1.0):
            self.output = bool(value)
            self._note_mode()
        elif head == "DAMPING" and value in (0.0, 1.0):
            self.damping = bool(value)
        else:
            # Anything else - including every SCPI spelling - is a
            # command error, and the setting it was meant to change is
            # left exactly where it was.
            self.esr |= 32

    # ---- queries ----
    def _answer(self, head):
        volts, amps, mode = self._operating_point()
        numbered = self.headers == "series2"
        if head == "*IDN?":
            return IDNS[self.model]
        if head == "VO?":
            return f"{volts + (self.volts_error if self.output else 0):.2f}V"
        if head == "IO?":
            return f"{amps:.3f}A"
        if head == "POWER?":
            return f"{volts * amps:.1f}W"
        if head == "V?":
            return f"{'V1' if numbered else 'V'} {self.v_set:.2f}"
        if head == "I?":
            return f"{'I1' if numbered else 'I'} {self.i_set:.3f}"
        if head == "OVP?":
            return f"{'VP1' if numbered else 'OVP'} {self.ovp:.2f}"
        if head == "LSR?":
            value, self.lsr = self.lsr, 0
            if self.reasserts and mode is not None:
                self.lsr |= 1 if mode == CC else 2
            return str(value)
        if head == "*ESR?":
            value, self.esr = self.esr, 0
            return str(value)
        if head == "EER?":
            value, self.eer = self.eer, 0
            return str(value)
        if head == "QER?":
            value, self.qer = self.qer, 0
            return str(value)
        if head == "*STB?":
            return "0"
        self.esr |= 32
        return ""

    def _read(self, timeout_s=3.0):
        return self._reply

    def writes(self):
        """Everything sent that was not a query."""
        return [s for s in self.sent if not s.strip().endswith("?")]


def build(cls=AimTTiTSX3510P, **kwargs):
    kwargs.setdefault("model", cls.MODEL_IDS[0])
    transport = SupplyTransport(**kwargs)
    return cls(transport), transport


# ---------------------------------------------------------------
# The spellings
# ---------------------------------------------------------------


def test_every_setting_is_spelled_the_way_the_manual_spells_it(check):
    supply, wire = build()
    for action, expected in (
            (lambda: supply.set_voltage_level(12.5), "V 12.5"),
            (lambda: supply.set_current_limit(2.0), "I 2"),
            (lambda: supply.set_overvoltage_trip(20.0), "OVP 20"),
            (lambda: supply.set_meter_damping(True), "DAMPING 1"),
            (lambda: supply.set_meter_damping(False), "DAMPING 0"),
            (supply.output_off, "OP 0")):
        wire.sent.clear()
        action()
        check(f"{expected!r} is what was sent", wire.sent == [expected],
              f"sent {wire.sent}")


def test_the_level_and_the_compliance_are_one_knob(check):
    """`set_voltage_level` and `set_voltage_limit` write the same
    setting, and so do the two current setters.

    That is what a supply is: which one regulates is the load's
    decision. A driver giving the pair different commands would be
    inventing a distinction the instrument does not have.
    """
    supply, wire = build()
    for setter, expected in ((supply.set_voltage_level, "V 5"),
                             (supply.set_voltage_limit, "V 5"),
                             (supply.set_current_level, "I 5"),
                             (supply.set_current_limit, "I 5")):
        wire.sent.clear()
        setter(5.0)
        check(f"{setter.__name__} -> {expected!r}", wire.sent == [expected],
              f"sent {wire.sent}")


def test_the_source_function_sends_nothing(check):
    """There is no command for it, so a write here would be a guess."""
    supply, wire = build()
    for mode in ("voltage", "current"):
        supply.set_source_function(mode)
    check("nothing reached the wire", wire.sent == [], f"{wire.sent}")
    check("and the choice is remembered",
          supply.source_function() == "current")
    with pytest.raises(ValueError):
        supply.set_source_function("resistance")


def test_reset_states_its_defaults_instead_of_trusting_them(check):
    """Fault 17. The trip's reset value is the least protective one
    there is, so it is sent rather than assumed."""
    supply, wire = build()
    supply.reset()
    check("reset, clear, then the two settings said out loud",
          wire.sent == ["*RST", "*CLS", "OVP 40", "DAMPING 0"],
          f"sent {wire.sent}")
    other, other_wire = build(AimTTiTSX1820P)
    other.reset()
    check("and the 1820 sends its own trip ceiling",
          "OVP 25" in other_wire.sent, f"sent {other_wire.sent}")


def test_a_reading_is_two_queries_in_voltage_then_current_order(check):
    supply, wire = build()
    supply.measure()
    check("VO? then IO?", wire.sent == ["VO?", "IO?"], f"{wire.sent}")


def _exercise_everything(supply):
    """Call every public method that reaches the instrument."""
    supply.identify()
    supply.reset()
    supply.set_source_function("voltage")
    supply.set_current_limit(0.5)
    supply.set_voltage_level(3.0)
    supply.set_voltage_limit(3.0)
    supply.set_current_level(0.5)
    supply.set_overvoltage_trip(10.0)
    supply.set_meter_damping(True)
    supply.set_source_delay(0.1)
    supply.set_voltage_verified(3.0)
    supply.read_voltage_setpoint()
    supply.read_current_setpoint()
    supply.read_overvoltage_trip()
    supply.verify_setpoint("voltage", 3.0)
    supply.verify_overvoltage_trip(10.0)
    supply.output_on()
    supply.measure()
    supply.measure_power()
    supply.regulation()
    supply.compliance_tripped()
    supply.protection_tripped()
    supply.read_status_byte()
    supply.read_error()
    supply.output_off()
    supply.safe_output_off()


def test_no_other_dialect_ever_reaches_the_wire(check):
    """Not one colon. This instrument has no command tree, and the
    spellings every other driver here uses are command errors on it."""
    supply, wire = build()
    _exercise_everything(supply)
    check("something was sent at all", len(wire.sent) > 20, len(wire.sent))
    for sent in wire.sent:
        check(f"{sent!r} is not SCPI", ":" not in sent)
        for foreign in ("SOUR", "MEAS", "OUTP", "SENS", "SYST", "FUNC",
                        "INP", "smu."):
            check(f"{sent!r} carries no {foreign}",
                  foreign.upper() not in sent.upper())
    check("and the instrument understood all of it",
          wire.esr == 0 and supply.read_error()[0] == 0,
          f"esr {wire.esr}")


def test_the_declined_commands_are_never_sent(check):
    """Each is in the manual's command list and absent on purpose - see
    the driver's "Never sent". The worst is a recall, which restores the
    stored output state and so can energise whatever is attached."""
    supply, wire = build()
    _exercise_everything(supply)
    heads = {sent.split()[0].upper().rstrip("?") for sent in wire.sent}
    for declined in ("INCV", "INCVV", "DECV", "DECVV", "INCI", "DECI",
                     "DELTAV", "DELTAI", "*SAV", "*RCL", "*LRN", "LRN",
                     "STO", "BUZZER", "BUZZ", "*SRE", "*ESE", "LSE",
                     "*PRE", "LOCAL"):
        check(f"{declined} was not sent", declined not in heads,
              f"sent heads: {sorted(heads)}")


# ---------------------------------------------------------------
# Replies carry text
# ---------------------------------------------------------------


def test_a_reading_survives_its_unit_suffix(check):
    """`'1.00V'` is a reading, not a parse failure - and the failure
    this guards is not an exception but a silent `None`."""
    supply, wire = build(load_ohms=10.0)
    supply.set_current_limit(1.0)
    supply.set_voltage_level(1.0)
    supply.output_on()
    volts, amps = supply.measure()
    check("the voltage parsed", volts == 1.0, f"got {volts!r}")
    check("the current parsed", amps == 0.1, f"got {amps!r}")
    check("and the power", supply.measure_power() == 0.1)


@pytest.mark.parametrize("reply,expected", [
    ("12.55V", (12.55, "V")),
    ("0.934A", (0.934, "A")),
    ("175.3W", (175.3, "W")),
    ("V 12.55", (12.55, "")),
    ("I 1.000", (1.0, "")),
    ("OVP 33.00", (33.0, "")),
    # The manual's syntax line has no space where its example has one.
    ("V12.55", (12.55, "")),
    # Series II puts the output number in the header.
    ("V1 12.55", (12.55, "")),
    ("VP1 33.00", (33.0, "")),
    ("  12.55V\r\n", (12.55, "V")),
    ("9.910000E+37", (9.91e37, "")),
    ("", (None, "")),
    ("no number here", (None, "")),
    (None, (None, "")),
])
def test_the_number_is_taken_off_the_end_of_a_reply(reply, expected):
    assert AimTTiTSXP._parse(reply) == expected


def test_a_setting_reads_back_under_either_generations_header(check):
    for headers in ("series1", "series2"):
        supply, _ = build(headers=headers)
        supply.set_voltage_level(12.5)
        supply.set_current_limit(1.5)
        supply.set_overvoltage_trip(30.0)
        check(f"{headers}: voltage", supply.read_voltage_setpoint() == 12.5)
        check(f"{headers}: current", supply.read_current_setpoint() == 1.5)
        check(f"{headers}: trip", supply.read_overvoltage_trip() == 30.0)


def test_a_reply_in_the_wrong_unit_is_refused_not_recorded(check):
    """A current in the voltage column is fault 21, and the unit on the
    reply is the only thing that can catch it."""
    supply, wire = build()
    wire._answer = lambda head: "0.934A"
    try:
        supply.measure()
    except RuntimeError as exc:
        check("it says the link is out of step", "out of step" in str(exc),
              str(exc))
    else:
        check("a voltage query answered in amps raised", False,
              "it was recorded as a voltage")


def test_a_sentinel_is_dropped_after_the_unit_is_stripped(check):
    supply, wire = build()
    wire._answer = lambda head: ("9.910000E+37V" if head == "VO?"
                                 else "0.250A")
    volts, amps = supply.measure()
    check("the sentinel is not data", volts is None, f"{volts!r}")
    check("and it did not take the current with it", amps == 0.25,
          f"{amps!r}")


# ---------------------------------------------------------------
# The guards
# ---------------------------------------------------------------


def test_what_the_instrument_would_reject_never_reaches_it(check):
    """Refused by the driver, with a reason, before the wire - because
    the instrument's own refusal is an error number in a register that
    a worker thread would find out about later, if at all."""
    supply, wire = build()
    for name, action in (
            ("a negative voltage", lambda: supply.set_voltage_level(-1.0)),
            ("a negative current", lambda: supply.set_current_level(-0.5)),
            ("a current below 10 mA",
             lambda: supply.set_current_limit(0.005)),
            ("a current of zero", lambda: supply.set_current_level(0.0)),
            ("a voltage above the range",
             lambda: supply.set_voltage_level(36.0)),
            ("a current above the range",
             lambda: supply.set_current_limit(10.5)),
            ("a trip above its window",
             lambda: supply.set_overvoltage_trip(41.0)),
            ("a trip below its window",
             lambda: supply.set_overvoltage_trip(0.5))):
        wire.sent.clear()
        try:
            action()
        except LimitError:
            check(f"{name}: nothing was sent", wire.sent == [], wire.sent)
        else:
            check(f"{name}: refused", False, f"sent {wire.sent}")


def test_each_model_is_held_to_its_own_envelope(check):
    """The reason there are two classes. 20 V is ordinary on the 3510
    and above the top of the 1820; 15 A is the other way round."""
    big_v, _ = build(AimTTiTSX3510P)
    big_i, _ = build(AimTTiTSX1820P)
    big_v.set_voltage_level(20.0)
    big_i.set_current_limit(15.0)
    with pytest.raises(LimitError):
        big_i.set_voltage_level(20.0)
    with pytest.raises(LimitError):
        big_v.set_current_limit(15.0)
    check("3510 envelope", (big_v.LIMITS.max_voltage,
                            big_v.LIMITS.max_current) == (35.3, 10.2))
    check("1820 envelope", (big_i.LIMITS.max_voltage,
                            big_i.LIMITS.max_current) == (18.15, 20.2))
    check("the trips differ too",
          (big_v.OVP_RANGE_V, big_i.OVP_RANGE_V)
          == ((1.0, 40.0), (1.0, 25.0)))


def test_the_gate_refuses_before_the_run(check):
    supply, _ = build()
    supply.validate_source_point(voltage=12.0, current=1.0,
                                 sourcing="voltage")
    supply.validate_source_point(current=2.0, voltage=30.0,
                                 sourcing="current")
    for name, kwargs, says in (
            ("a negative level",
             dict(voltage=-1.0, current=1.0, sourcing="voltage"),
             "power supply"),
            ("a sinking level",
             dict(current=-1.0, voltage=5.0, sourcing="current"),
             "cannot sink"),
            ("a compliance below the floor",
             dict(voltage=5.0, current=0.001, sourcing="voltage"),
             "compliance"),
            ("a level below the floor",
             dict(current=0.001, voltage=5.0, sourcing="current"),
             "level"),
            ("a level above the range",
             dict(voltage=40.0, current=1.0, sourcing="voltage"),
             "maximum")):
        try:
            supply.validate_source_point(**kwargs)
        except LimitError as exc:
            check(f"{name}: says why", says in str(exc), str(exc))
            check(f"{name}: does not call it a load",
                  "electronic load cannot" not in str(exc), str(exc))
        else:
            check(f"{name}: refused", False, "it passed the gate")


def test_a_remote_sense_request_is_refused(check):
    supply, wire = build()
    with pytest.raises(NotImplementedError):
        supply.set_remote_sense(True)
    check("and nothing was sent", wire.sent == [])
    check("the wiring is recorded instead",
          "links" in supply.fixed_sense() and
          not supply.supports_remote_sense_control())


# ---------------------------------------------------------------
# The error path
# ---------------------------------------------------------------


def test_a_rejected_setting_comes_back_under_the_instruments_number(check):
    supply, wire = build()
    command, expected = supply.ERROR_PROBE
    wire.write(command)
    code, message = supply.read_error()
    check("the probe is rejected with the declared number",
          code == expected, f"{code}: {message}")
    check("under the manual's wording",
          message == EXECUTION_ERRORS[expected], message)
    check("and the registers are empty afterwards",
          supply.read_error()[0] == 0)


def test_a_scpi_spelling_is_a_command_error_not_a_silence(check):
    """The whole reason spellings are asserted: on a SCPI instrument a
    wrong header is logged, and on this one it is too - under a bit
    with no number, which the driver files as the negative of the
    bit."""
    supply, wire = build()
    supply.set_voltage_level(5.0)
    wire.write(":SOUR:VOLT 12")
    code, message = supply.read_error()
    check("reported", code == -32, f"{code}: {message}")
    check("and the setting did not move", wire.v_set == 5.0, wire.v_set)


def test_one_read_of_the_register_can_carry_several_errors(check):
    """`*ESR?` empties itself. Whatever it held has to be handed out
    one entry per call, or a caller draining in a loop loses all but
    the first."""
    supply, wire = build()
    wire.write("NONSENSE")
    wire.write("V 99")
    codes = []
    for _ in range(5):
        code, _ = supply.read_error()
        if code == 0:
            break
        codes.append(code)
    check("both came out, in the order they were decoded",
          codes == [-32, 100], f"{codes}")
    check("with a single read of the register",
          wire.sent.count("*ESR?") == 2, wire.sent)


def test_being_unable_to_ask_is_not_an_error(check):
    """The contract's rule: a failure to read reports code 0, with the
    reason, and an unparseable reply is shown rather than interpreted."""
    supply, wire = build()

    def dead(text, timeout_s=3.0):
        raise TimeoutError("no reply")
    wire.query = dead
    code, message = supply.read_error()
    check("a timeout is code 0", code == 0, f"{code}")
    check("and says what happened", "TimeoutError" in message, message)

    supply, wire = build()
    wire._answer = lambda head: "garbage"
    code, message = supply.read_error()
    check("an unparseable reply is code 0", code == 0, f"{code}")
    check("with the raw text for a human", "garbage" in message, message)


def test_a_desynchronised_link_is_never_swallowed(check):
    supply, wire = build()
    supply.set_source_function("voltage")
    supply._output_enabled = True

    def out_of_step(text, timeout_s=3.0):
        raise TransportDesynchronised("the link is out of step")
    wire.query = out_of_step
    for name, action in (("read_error", supply.read_error),
                         ("regulation", supply.regulation),
                         ("compliance_tripped", supply.compliance_tripped),
                         ("protection_tripped", supply.protection_tripped),
                         ("measure", supply.measure),
                         ("output_on", supply.output_on)):
        with pytest.raises(TransportDesynchronised):
            action()
        check(f"{name} let it through", True)


# ---------------------------------------------------------------
# Which knob is in charge
# ---------------------------------------------------------------


def _energised(mode, **kwargs):
    supply, wire = build(**kwargs)
    supply.set_source_function(mode)
    supply.set_current_limit(1.0)
    supply.set_voltage_level(5.0)
    supply.output_on()
    return supply, wire


def test_an_open_circuit_is_constant_voltage_and_not_clamped(check):
    supply, _ = _energised("voltage")
    check("constant voltage", supply.regulation() == CV)
    check("so sourcing voltage is not clamped",
          supply.compliance_tripped() is False)


def test_current_limit_is_the_compliance_when_sourcing_voltage(check):
    """5 V into 1 ohm wants 5 A against a 1 A setting."""
    supply, _ = _energised("voltage", load_ohms=1.0)
    check("constant current", supply.regulation() == CC)
    check("which is the compliance", supply.compliance_tripped() is True)
    volts, amps = supply.measure()
    check("and the reading is of the ceiling", (volts, amps) == (1.0, 1.0),
          f"{volts}, {amps}")


def test_the_meaning_inverts_when_sourcing_current(check):
    """Sourcing current, constant current is the supply doing what it
    was asked. It is clamped when it falls back to constant voltage:
    the load would not take the current, and the reading is of the
    voltage ceiling."""
    delivering, _ = _energised("current", load_ohms=1.0)
    check("in CC it is delivering the level",
          delivering.compliance_tripped() is False)
    starved, _ = _energised("current")
    check("open-circuit it sits at the voltage ceiling",
          starved.compliance_tripped() is True)


def test_the_output_off_is_not_clamped_and_unknown_is_not_fine(check):
    supply, wire = build()
    supply.set_source_function("voltage")
    check("off: not clamped", supply.compliance_tripped() is False)
    check("and nothing was asked to find that out", wire.sent == [])

    supply, wire = build()
    supply.output_on()
    check("on, with no source function chosen: cannot say",
          supply.compliance_tripped() is None)

    supply, wire = build()
    supply.set_source_function("voltage")
    supply.output_on()
    wire.lsr = 0
    wire._mode = CV
    check("on, with no limit event seen: cannot say",
          supply.compliance_tripped() is None,
          "an instrument that reported nothing was read as not clamped")


def test_the_state_is_kept_between_polls_under_either_reading(check):
    """The manual does not say whether a limit bit comes back after
    being read. The driver has to be right both ways."""
    for reasserts in (False, True):
        supply, _ = _energised("voltage", load_ohms=1.0,
                               reasserts=reasserts)
        seen = [supply.compliance_tripped() for _ in range(4)]
        check(f"reasserts={reasserts}: clamped on every poll",
              seen == [True] * 4, f"{seen}")


def test_a_crossover_and_back_between_polls_is_a_clamped_interval(check):
    """Both bits at once: it reached the ceiling and left it. That is
    reported as clamped, and then - under the reading where bits are
    not reasserted - as unknown, never as a mode nobody observed."""
    supply, wire = _energised("voltage")
    supply.regulation()
    wire.lsr = 3
    check("both entries read as crossed", supply.regulation() == CROSSED)
    wire.lsr = 3
    check("which counts as clamped", supply.compliance_tripped() is True)
    check("and the next quiet poll cannot say",
          supply.compliance_tripped() is None)


def test_events_from_before_the_output_came_on_are_not_this_runs(check):
    """The register is flushed going on, or a limit entered an hour ago
    is the first thing a new run is told."""
    supply, wire = build()
    supply.set_source_function("voltage")
    wire.lsr = 1
    supply.output_on()
    check("the flush came before the switch",
          wire.sent[-2:] == ["LSR?", "OP 1"], wire.sent)
    check("and the stale entry is gone",
          supply.compliance_tripped() is False)


def test_a_trip_is_latched_until_the_output_next_goes_on(check):
    supply, wire = _energised("voltage")
    check("nothing has tripped", supply.protection_tripped() is False)
    wire.lsr = 4
    check("a trip is seen", supply.protection_tripped() is True)
    check("and stays seen after the register empties",
          supply.protection_tripped() is True)
    supply.output_off()
    supply.output_on()
    check("a fresh energising starts clean",
          supply.protection_tripped() is False)


# ---------------------------------------------------------------
# Readback, verified set, and state
# ---------------------------------------------------------------


def test_a_setting_is_graded_on_the_grid_and_never_confirmed_yet(check):
    """Unverified until a bench has checked the query against a value
    the instrument was known to hold - a query handing back the number
    it was just given is not evidence."""
    supply, wire = build()
    supply.set_voltage_level(0.05)
    readback = supply.verify_setpoint("voltage", 0.05)
    check("agreement is unverified, not confirmed",
          readback.state == UNVERIFIED, readback.state)

    wire.v_set = 0.06
    check("one step out still agrees",
          supply.verify_setpoint("voltage", 0.05).state == UNVERIFIED)
    wire.v_set = 0.08
    check("three steps out is a mismatch",
          supply.verify_setpoint("voltage", 0.05).state == MISMATCHED)

    supply.set_overvoltage_trip(20.0)
    wire.ovp = 40.0
    check("a trip that did not move is a mismatch",
          supply.verify_overvoltage_trip(20.0).state == MISMATCHED)


def test_a_verified_set_reports_whether_the_output_got_there(check):
    supply, wire = build()
    check("settled", supply.set_voltage_verified(5.0) is True)
    check("spelled VV", "VV 5" in wire.sent, wire.sent)

    slow, slow_wire = build(settles=False)
    check("timed out", slow.set_voltage_verified(5.0) is False)
    check("and the time-out is the answer, not a queued error",
          slow.read_error()[0] == 0)

    busy, busy_wire = build()
    busy_wire.write("NONSENSE")
    busy.set_voltage_verified(5.0)
    check("an error the same read carried is kept for read_error()",
          busy.read_error()[0] == -32)
    with pytest.raises(LimitError):
        busy.set_voltage_verified(-1.0)


def test_reset_forgets_what_the_driver_was_keeping(check):
    supply, wire = _energised("voltage", load_ohms=1.0)
    supply.compliance_tripped()
    supply.set_meter_damping(True)
    supply.reset()
    check("output believed off", supply._output_enabled is False)
    check("no source function", supply.source_function() is None)
    check("no regulation state", supply._regulation is None)
    check("damping off", supply.meter_damping is False)
    check("and the instrument agrees", wire.output is False
          and wire.v_set == 0.0 and wire.damping is False)


def test_output_off_stops_claiming_to_be_energised_even_if_it_raises(check):
    supply, wire = _energised("voltage")

    def broken(text):
        raise OSError("the cable came out")
    wire.write = broken
    with pytest.raises(OSError):
        supply.output_off()
    check("the driver no longer says the output is on",
          supply._output_enabled is False)


# ---------------------------------------------------------------
# Identity, and the sweep it inherits
# ---------------------------------------------------------------


def test_each_identity_resolves_to_its_own_model(check):
    """A 3510 driven by the 1820's class would be held to the wrong
    envelope in both directions, and nothing downstream would notice."""
    check("TSX3510P", driver_for_idn(IDNS["TSX3510P"]) is AimTTiTSX3510P)
    check("TSX1820P", driver_for_idn(IDNS["TSX1820P"]) is AimTTiTSX1820P)
    check("the Series II example in the manual",
          driver_for_idn(SERIES_II_IDN) is AimTTiTSX1820P)
    check("the shared base claims nothing", AimTTiTSXP.MODEL_IDS == []
          and AimTTiTSXP.LIMITS is None)


def test_the_software_sweep_records_what_was_read_back(check):
    """Inherited from `BaseInstrument`, and it records the voltmeter's
    reading as the sourced value - which on a 10 mV grid is the level
    the instrument actually produced, not the one that was asked for."""
    supply, wire = build(load_ohms=10.0)
    supply.set_source_function("voltage")
    supply.set_current_limit(2.0)
    supply.output_on()
    supply.start_linear_sweep("voltage", 1.0, 2.0, 5, 0.0)
    sourced, measured = supply.read_sweep(5)
    check("five points", len(sourced) == 5, f"{sourced}")
    check("levels as read back", sourced == [1.0, 1.25, 1.5, 1.75, 2.0],
          f"{sourced}")
    check("with the current each drew",
          measured == [0.1, 0.125, 0.15, 0.175, 0.2], f"{measured}")
    check("declared as a software sweep", supply.sweep_kind() == "software")
