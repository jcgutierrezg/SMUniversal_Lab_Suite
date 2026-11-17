"""The TDK-Lambda Z36-24's driver, against a fake that behaves the way
the two probe sittings found the unit behaving.

The fake is strict where the unit was surprising, because those are the
things a driver gets wrong without noticing:

  * it hears nothing until `INST:NSEL` selects it, `*IDN?` included;
  * it ignores a refused setting **in silence** until `SYST:ERR:ENAB`,
    and reports it afterwards in the unit's own format, address suffix
    and plus sign included;
  * it refuses a voltage above 95% of the trip and a trip below 105% of
    the voltage;
  * a setting lands a fraction of a step below what was sent.

A fake that heard everything and complained about everything would pass
a driver that never selects the supply and never enables its errors -
which is exactly the driver that fails at the bench on a supply switched
on that morning.
"""
import math
from types import SimpleNamespace

import pytest

from smuniversal_lab_suite.core import addresses
from smuniversal_lab_suite.core.base_app import LabApp
from smuniversal_lab_suite.core.limits import LimitError
from smuniversal_lab_suite.core.transports.base import (
    Transport,
    TransportDesynchronised,
)
from smuniversal_lab_suite.drivers import registry
from smuniversal_lab_suite.drivers.base_supply import CC, CV
from smuniversal_lab_suite.drivers.tdk_lambda_zplus import (
    FAULT_BITS,
    TDKLambdaZ36_24,
    TDKLambdaZPlus,
)

IDN = "TDK-LAMBDA,Z36-24,817A137-0013,2.231"

#: What the unit accepts: 5% over rated, and the trip window.
V_ACCEPTED, A_ACCEPTED = 37.8, 25.2
OVP_LOW, OVP_HIGH = 2.0, 40.0
#: A setting lands this far below what was sent (measured, about).
V_STEP, A_STEP = 0.0006, 0.0004


class ZPlusTransport(Transport):
    """A Z36-24 at bus address 1.

    `load_ohms` is what is across the terminals: None is nothing. A load
    drawing more than the current setting puts the supply in CC.
    `fault` is a fault-register value the next `STAT:QUES:COND?` reads,
    and then clears - a trip whose cause went away.
    """

    def __init__(self, address=1, selected=False, errors_enabled=False,
                 load_ohms=None, port=None):
        super().__init__()
        self.connected = True
        self.bus_address = address
        self.selected = selected
        self.errors_enabled = errors_enabled
        self.load_ohms = load_ohms
        self.port = port
        self.sent = []
        self.replies = []
        self.queue = []
        self.esr_bits = 0
        #: Commands that drew an error, other than the driver's own
        #: error probe. Together with an undrained queue this is what
        #: the checkup test reads as `esr`: anything left means the
        #: instrument complained about something it was sent by mistake.
        self.unexpected = []
        self.output = False
        self.v_set, self.i_set, self.ovp = 2.0, 20.0, 40.0
        self.auto_restart = False
        self.remote = "LOC"
        self.fault = 0

    @property
    def esr(self):
        return len(self.queue) + len(self.unexpected)

    # ---- the transport ----
    def connect(self, address, **kwargs):
        self.connected = True

    def close(self):
        self.connected = False

    def _write(self, text):
        self.sent.append(text)
        reply = self.handle(text.strip())
        if reply is not None:
            self.replies.append(reply)

    def _read(self, timeout_s=3.0):
        if self.replies:
            return self.replies.pop(0)
        raise TimeoutError("fake Z+: no reply")

    # ---- physics ----
    def vout(self):
        if not self.output:
            return 0.0
        if self.load_ohms is None:
            return self.v_set
        return min(self.v_set, self.i_set * self.load_ohms)

    def iout(self):
        if not self.output or self.load_ohms is None:
            return 0.0
        return self.vout() / self.load_ohms

    def mode(self):
        if not self.output:
            return "OFF"
        if self.load_ohms is not None and \
                self.v_set / self.load_ohms > self.i_set:
            return "CC"
        return "CV"

    # ---- the command set ----
    def refuse(self, command, code, text, bit):
        """The first sitting: silence. The second: the unit's format."""
        if not self.errors_enabled:
            return
        sign = "+" if code > 0 else ""
        self.queue.append(f'{sign}{code},"{text};address '
                          f'{self.bus_address}"')
        self.esr_bits |= bit
        if command != TDKLambdaZ36_24.ERROR_PROBE[0]:
            self.unexpected.append(command)

    def handle(self, text):
        header, _, arg = text.partition(" ")
        header, arg = header.upper(), arg.strip().upper()
        if header == "INST:NSEL":
            self.selected = arg.isdigit() and int(arg) == self.bus_address
            return None
        if not self.selected:
            return None
        if header.endswith("?"):
            return self.answer(text, header)
        value = None
        try:
            value = float(arg)
        except ValueError:
            pass
        if header in ("VOLT", "CURR", "VOLT:PROT:LEV", "OUTP"):
            self.remote = "REM"
        if header == "VOLT" and value is not None:
            if value > V_ACCEPTED:
                self.refuse(text, -222, "Data Out Of Range", 16)
            elif value > 0.95 * self.ovp + 1e-9:
                self.refuse(text, 301, "PV Above OVP", 8)
            else:
                self.v_set = max(0.0, round(value - V_STEP / 2, 4))
        elif header == "CURR" and value is not None:
            if value > A_ACCEPTED:
                self.refuse(text, -222, "Data Out Of Range", 16)
            else:
                self.i_set = max(0.0, round(value - A_STEP / 2, 4))
        elif header == "VOLT:PROT:LEV" and value is not None:
            if not OVP_LOW <= value <= OVP_HIGH:
                self.refuse(text, -222, "Data Out Of Range", 16)
            elif value < 1.05 * self.v_set - 1e-9:
                self.refuse(text, 304, "OVP Below PV", 8)
            else:
                self.ovp = round(value, 2)
        elif header == "OUTP" and arg in ("0", "1"):
            self.output = arg == "1"
        elif header == "OUTP:PON" and arg in ("0", "1"):
            self.auto_restart = arg == "1"
        elif header == "*RST":
            self.output, self.v_set, self.i_set = False, 0.0, 0.0
            self.ovp, self.auto_restart, self.remote = OVP_HIGH, False, "LOC"
        elif header == "*CLS":
            self.queue, self.esr_bits = [], 0
        elif header == "SYST:ERR:ENAB" and not arg:
            self.errors_enabled = True
        elif header == "SYST:REM" and arg in ("LOC", "REM"):
            self.remote = arg
        else:
            self.refuse(text, -100, "Command Error", 32)
        return None

    def answer(self, text, header):
        if header == "SYST:ERR?":
            return self.queue.pop(0) if self.queue else '0,"No error"'
        if header == "*ESR?":
            value, self.esr_bits = self.esr_bits, 0
            return str(value)
        if header == "STAT:QUES:COND?":
            value, self.fault = self.fault, 0
            return str(value)
        replies = {
            "*IDN?": IDN,
            "VOLT?": f"{self.v_set:07.4f}",
            "CURR?": f"{self.i_set:07.4f}",
            "VOLT:PROT:LEV?": f"{self.ovp:05.2f}",
            "OUTP?": "1" if self.output else "0",
            "OUTP:MODE?": self.mode(),
            "OUTP:PON?": "1" if self.auto_restart else "0",
            "SYST:REM?": self.remote,
            "MEAS:VOLT?": f"{self.vout():07.4f}",
            "MEAS:CURR?": f"{self.iout():07.4f}",
            "MEAS:POW?": f"{self.vout() * self.iout():06.2f}",
            "STAT:OPER:COND?": "5" if self.output else "4",
            "*OPC?": "1",
        }
        if header in replies:
            return replies[header]
        self.refuse(text, -100, "Command Error", 32)
        return None


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(TDKLambdaZPlus, "CLS_SETTLE_S", 0.0)
    monkeypatch.setattr(TDKLambdaZPlus, "WRITE_DELAY_S", 0.0)


def connected(**kwargs):
    """A driver after the reset every connect sends."""
    wire = ZPlusTransport(**kwargs)
    supply = TDKLambdaZ36_24(wire)
    supply.reset()
    return supply, wire


# ---------------------------------------------------------------
# Selection
# ---------------------------------------------------------------


def test_identify_selects_first_so_a_driver_chosen_by_hand_is_heard(check):
    wire = ZPlusTransport()
    supply = TDKLambdaZ36_24(wire)
    check("answered", supply.identify() == IDN)
    check("INST:NSEL 1 went first", wire.sent[:2] == ["INST:NSEL 1", "*IDN?"],
          f"{wire.sent}")


def test_an_unselected_supply_hears_nothing(check):
    """The fake's premise, pinned: without the greeting `*IDN?` is
    silence, which is what the registry would otherwise meet."""
    wire = ZPlusTransport()
    with pytest.raises(TransportDesynchronised):
        wire.query("*IDN?", timeout_s=0.01)
    check("unselected", wire.selected is False)


def ports(ids):
    return {"COM7": {"ids": ids, "description": "USB Serial Device",
                     "text": "", "serial_number": None}}


def test_the_registry_greets_its_usb_ids_and_identifies(monkeypatch,
                                                        check):
    monkeypatch.setattr(addresses, "serial_ports",
                        lambda: ports((0x2504, 0x0001)))
    wire = ZPlusTransport(port="COM7")
    driver, idn = registry.identify(wire)
    check("the Z36-24", isinstance(driver, TDKLambdaZ36_24), f"{driver}")
    check("greeted before *IDN?", wire.sent[:2] == ["INST:NSEL 1", "*IDN?"],
          f"{wire.sent}")


def test_another_usb_device_is_not_greeted(monkeypatch, check):
    monkeypatch.setattr(addresses, "serial_ports",
                        lambda: ports((0x0416, 0x5011)))
    wire = ZPlusTransport(port="COM7", selected=True)
    check("nothing greeted", registry.greet(wire) is None)
    check("nothing sent", wire.sent == [], f"{wire.sent}")


def test_a_gpib_address_is_not_looked_up(monkeypatch, check):
    def no_enumeration():
        raise AssertionError("the serial ports were enumerated for GPIB")

    monkeypatch.setattr(addresses, "serial_ports", no_enumeration)
    wire = SimpleNamespace(address="GPIB0::9::INSTR", sent=[],
                           write=lambda text: wire.sent.append(text))
    check("nothing greeted", registry.greet(wire) is None)


def test_a_visa_serial_address_is_greeted_too(monkeypatch, check):
    monkeypatch.setattr(addresses, "serial_ports",
                        lambda: ports((0x2504, 0x0001)))
    wire = ZPlusTransport()
    wire.address = "ASRL7::INSTR"
    check("greeted", registry.greet(wire) is TDKLambdaZ36_24)
    check("selected", wire.selected is True)


def test_the_dropdown_names_it(check):
    info = ports((0x2504, 0x0001))
    check("named", addresses.describe("COM7", info) == "TDK-Lambda Z36-24")
    check("kept", addresses.keep("COM7", info))


# ---------------------------------------------------------------
# Reset, and the errors it turns on
# ---------------------------------------------------------------


def test_reset_selects_resets_enables_errors_and_says_the_safe_settings(
        check):
    supply, wire = connected()
    check("the order", wire.sent == [
        "INST:NSEL 1", "*RST", "*CLS", "SYST:ERR:ENAB",
        "VOLT:PROT:LEV 40", "OUTP:PON 0"], f"{wire.sent}")
    check("errors enabled", wire.errors_enabled is True)
    check("output off, 0 V, widest trip", (wire.output, wire.v_set, wire.ovp)
          == (False, 0.0, 40.0))


def test_the_error_probe_is_reported_once_errors_are_enabled(check):
    supply, wire = connected()
    command, expected = supply.ERROR_PROBE
    wire.write(command)
    code, message = supply.read_error()
    check("the code", code == expected, f"{code}")
    check("the address suffix dropped", message == "Data Out Of Range",
          message)
    check("then empty", supply.read_error() == (0, "No error"))


def test_without_reset_the_same_probe_is_silent(check):
    """Why `reset()` enables errors: the first sitting's unit."""
    wire = ZPlusTransport(selected=True)
    supply = TDKLambdaZ36_24(wire)
    wire.write(supply.ERROR_PROBE[0])
    check("nothing reported", supply.read_error()[0] == 0)
    check("and nothing landed", wire.i_set == 20.0)


@pytest.mark.parametrize("reply, expected", [
    ('+304,"OVP Below PV;address 1"', (304, "OVP Below PV")),
    ('-100,"Command Error;address 12"', (-100, "Command Error")),
    ('0,"No error"', (0, "No error")),
    ("garbage", (0, "garbage")),
])
def test_error_replies_parse(reply, expected, check):
    wire = ZPlusTransport(selected=True)
    wire.replies.append(reply)
    supply = TDKLambdaZ36_24(wire)
    supply.transport.query = lambda *a, **k: reply
    check(reply, supply.read_error() == expected, f"{supply.read_error()}")


def test_a_failure_to_ask_is_code_zero(check):
    wire = ZPlusTransport()          # unselected: SYST:ERR? is silence
    supply = TDKLambdaZ36_24(wire)

    def boom(*args, **kwargs):
        raise OSError("port gone")

    wire.query = boom
    code, message = supply.read_error()
    check("code 0", code == 0)
    check("with the reason", "port gone" in message, message)


# ---------------------------------------------------------------
# The two knobs, the trip, and the rules between them
# ---------------------------------------------------------------


def test_levels_land_and_read_back(check):
    supply, wire = connected()
    supply.set_current_limit(0.05)
    supply.set_voltage_level(1.0)
    check("voltage", abs(supply.read_voltage_setpoint() - 1.0) < 0.001)
    check("current", abs(supply.read_current_setpoint() - 0.05) < 0.001)
    check("graded within a step",
          supply.verify_setpoint("voltage", 1.0).severity in ("pass", "warn"))
    check("nothing refused", wire.queue == [] and wire.unexpected == [])


def test_zero_current_is_a_setting_not_a_refusal(check):
    supply, wire = connected()
    supply.set_current_level(0.0)
    check("landed", wire.i_set == 0.0)
    supply.validate_source_point(voltage=1.0, current=0.0,
                                 sourcing="voltage")


def test_a_voltage_above_95_percent_of_the_trip_is_refused_first(check):
    supply, wire = connected()
    supply.set_overvoltage_trip(12.0)
    before = list(wire.sent)
    with pytest.raises(LimitError, match="95%"):
        supply.set_voltage_level(11.5)
    check("nothing sent", wire.sent == before)
    supply.set_voltage_level(11.0)
    check("11 V is fine", abs(wire.v_set - 11.0) < 0.001)


def test_a_trip_below_105_percent_of_the_voltage_is_refused_first(check):
    supply, wire = connected()
    supply.set_voltage_level(10.0)
    before = list(wire.sent)
    with pytest.raises(LimitError, match="105%"):
        supply.set_overvoltage_trip(10.0)
    check("nothing sent", wire.sent == before)
    supply.set_overvoltage_trip(10.5)
    check("10.5 V is fine", wire.ovp == 10.5)


def test_before_reset_the_guards_ask_the_instrument(check):
    wire = ZPlusTransport(selected=True)
    wire.ovp = 12.0
    supply = TDKLambdaZ36_24(wire)
    with pytest.raises(LimitError):
        supply.set_voltage_level(11.5)
    check("it asked", "VOLT:PROT:LEV?" in wire.sent, f"{wire.sent}")


@pytest.mark.parametrize("action", [
    lambda s: s.set_voltage_level(36.5),
    lambda s: s.set_current_level(24.5),
    lambda s: s.set_voltage_level(-1.0),
    lambda s: s.set_current_level(-0.1),
    lambda s: s.set_overvoltage_trip(1.0),
    lambda s: s.set_overvoltage_trip(41.0),
])
def test_out_of_envelope_is_refused_before_the_wire(action, check):
    supply, wire = connected()
    before = list(wire.sent)
    with pytest.raises(LimitError):
        action(supply)
    check("nothing sent", wire.sent == before, f"{wire.sent[len(before):]}")


def test_remote_sense_is_refused_and_says_why(check):
    supply, _ = connected()
    with pytest.raises(NotImplementedError, match="J2"):
        supply.set_remote_sense(True)


# ---------------------------------------------------------------
# Output, regulation, protection, readings
# ---------------------------------------------------------------


def test_output_and_its_readback(check):
    supply, wire = connected()
    supply.output_on()
    check("on", wire.output is True and supply.read_output_state() is True)
    supply.output_off()
    check("off", wire.output is False and supply.read_output_state() is False)


def test_regulation_is_read_as_a_state(check):
    supply, wire = connected(load_ohms=10.0)
    supply.set_source_function("voltage")
    supply.set_current_limit(1.0)
    supply.set_voltage_level(5.0)
    check("off is None", supply.regulation() is None)
    supply.output_on()
    check("CV under the limit", supply.regulation() == CV)
    check("not clamped", supply.compliance_tripped() is False)
    supply.set_current_limit(0.2)
    check("CC over it", supply.regulation() == CC)
    check("clamped", supply.compliance_tripped() is True)


def test_a_fault_is_latched_after_its_cause_clears(check):
    supply, wire = connected()
    supply.output_on()
    check("none yet", supply.protection_tripped() is False)
    wire.fault = 16
    check("seen", supply.protection_tripped() is True)
    check("and kept", supply.protection_tripped() is True)
    check("named", supply.faults() == [FAULT_BITS[16]], f"{supply.faults()}")
    supply.output_off()
    supply.output_on()
    check("cleared by the next output on", supply.protection_tripped()
          is False)


def test_output_off_is_not_a_fault(check):
    """Bit 6 of the fault register is "output off". It is not a trip."""
    supply, wire = connected()
    supply.output_on()
    wire.fault = 64
    check("not a trip", supply.protection_tripped() is False)


def test_measure_reads_zero_padded_replies(check):
    supply, wire = connected(load_ohms=10.0)
    supply.set_current_limit(1.0)
    supply.set_voltage_level(5.0)
    supply.output_on()
    volts, amps = supply.measure()
    check("volts", math.isclose(volts, wire.vout(), abs_tol=1e-4),
          f"{volts}")
    check("amps, positive out of a source", amps > 0
          and math.isclose(amps, wire.iout(), abs_tol=1e-4), f"{amps}")
    check("power", supply.measure_power() > 0)


def test_apply_ranges_records_the_one_range(check):
    from smuniversal_lab_suite.core.ranges import RangePlan

    supply, _ = connected()
    described = supply.apply_ranges(RangePlan.for_sourcing(
        "voltage", source_range=1.0, measure_range=0.05))
    check("one range", described.startswith("fixed - one range"),
          described)


# ---------------------------------------------------------------
# The front panel, and what is never sent
# ---------------------------------------------------------------


def test_disconnect_hands_the_front_panel_back_after_the_output_is_off(
        check):
    supply, wire = connected()
    supply.output_on()
    app = SimpleNamespace(
        instruments={"source": supply}, instrument_keys={},
        transports={"source": wire},
        ownership=SimpleNamespace(force_release=lambda key: False),
        log=lambda message: None)
    LabApp.disconnect_role(app, "source")
    tail = wire.sent[-2:]
    check("off, then local", tail == ["OUTP 0", "SYST:REM LOC"], f"{tail}")
    check("in local", wire.remote == "LOC")
    check("closed", wire.connected is False)


def test_a_driver_without_the_hook_disconnects_as_before(check):
    from test_tsx_p import SupplyTransport

    from smuniversal_lab_suite.drivers.aimtti_tsx_p import AimTTiTSX3510P

    wire = SupplyTransport()
    supply = AimTTiTSX3510P(wire)
    app = SimpleNamespace(
        instruments={"source": supply}, instrument_keys={},
        transports={"source": wire},
        ownership=SimpleNamespace(force_release=lambda key: False),
        log=lambda message: None)
    LabApp.disconnect_role(app, "source")
    check("off was the last thing sent", wire.sent[-1] == "OP 0",
          f"{wire.sent[-3:]}")


def test_never_sent(check):
    supply, wire = connected(load_ohms=10.0)
    supply.identify()
    supply.set_source_function("voltage")
    supply.set_current_limit(1.0)
    supply.set_voltage_level(5.0)
    supply.set_overvoltage_trip(20.0)
    supply.output_on()
    supply.measure()
    supply.measure_power()
    supply.regulation()
    supply.protection_tripped()
    supply.read_error()
    supply.output_off()
    supply.release_front_panel()
    banned = ("*SAV", "*RCL", "FRST", "GLOB", "LLO", "LIST", "WAVE",
              "TRIG", "INIT", "*TRG", "*PSC", "*SRE", "*ESE", ":ENAB ",
              "FOLD", "PROT:LOW", "ILC", "REL", "TTLT", "OUTP:PON 1")
    found = [s for s in wire.sent if any(b in s.upper() for b in banned)]
    check("none", not found, f"{found}")
    check("and the unit understood everything",
          wire.queue == [] and wire.unexpected == [],
          f"{wire.queue} {wire.unexpected}")
