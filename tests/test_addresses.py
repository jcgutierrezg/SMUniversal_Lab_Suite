"""Which addresses reach the dropdown, and what they are called.

The rules are in `core/addresses.py`. The cases below are the actual
contents of this bench's scan: four GPIB instruments, two USB ones, two
USB serial ones, a pair of phantom motherboard COM ports and a network
address that a scan invented.

Nothing here can make an instrument unreachable - the address box stays
editable and a typed address is opened as written - so these are about
what a person is shown, not about what the software will talk to.
"""
import pytest

from smuniversal_lab_suite.core import addresses


#: What pyserial reports on this bench. COM1 is the motherboard's own
#: UART: no USB ids behind it, and no instrument has ever been on one.
def _port(ids, description, text=None, serial_number=None):
    return {"ids": ids, "description": description,
            "text": text if text is not None else description,
            "serial_number": serial_number}


PORTS = {
    "COM1": _port((None, None), "Communications Port"),
    "COM3": _port((None, None), "Communications Port"),
    # The miniSMU: ids nobody has written down, but it says what it is.
    "COM5": _port((0x303A, 0x1001), "USB Serial Device",
                  "USB Serial Device miniSMU MS01 Undalogic Ltd",
                  "lunar-tuvok-7966"),
    "COM6": _port((0x0416, 0x5011), "USB-SERIAL CH340"),
    # Somebody's Arduino, on the same generic bridge chip as nothing
    # here: kept, because it is a USB device, and not named as an
    # instrument.
    "COM9": _port((0x1A86, 0x7523), "USB-SERIAL CH340"),
}

SCAN = [
    "GPIB0::9::INSTR",                              # B2901A
    "GPIB0::24::INSTR",                             # 2401
    "GPIB0::18::INSTR",                             # nothing recorded
    "USB0::8580::125::gew852313::0::INSTR",         # GSM-20H10, decimal ids
    "USB0::0x0957::0x4118::my62030002::0::INSTR",   # U2722A, hex ids
    "USB0::0x1234::0x5678::sn::0::INSTR",           # not an instrument here
    "ASRL1::INSTR",
    "ASRL3::INSTR",
    "ASRL5::INSTR",
    "ASRL6::INSTR",
    "TCPIP::129.67.86.137::INSTR",
]


def test_the_scan_is_cut_to_this_bench():
    labels, _ = addresses.filtered(SCAN, ports=PORTS)
    assert labels == [
        "Keysight B2901A - GPIB0::9::INSTR",
        "Keithley 2401 - GPIB0::24::INSTR",
        "GPIB0::18::INSTR",
        "GW Instek GSM-20H10 - USB0::8580::125::gew852313::0::INSTR",
        "Keysight U2722A - USB0::0x0957::0x4118::my62030002::0::INSTR",
        "Undalogic miniSMU MS01 - ASRL5::INSTR",
        "Multicomp Pro 72-13200 - ASRL6::INSTR",
    ]


def test_every_gpib_address_is_kept_named_or_not():
    """An instrument re-addressed on its front panel must not vanish
    because a table was not edited."""
    assert addresses.keep("GPIB0::18::INSTR", PORTS)
    assert addresses.describe("GPIB0::18::INSTR", PORTS) is None
    assert addresses.label("GPIB0::18::INSTR", PORTS) == "GPIB0::18::INSTR"


@pytest.mark.parametrize("address", [
    "TCPIP::129.67.86.137::INSTR",       # a network scan's invention
    "ASRL1::INSTR",                      # a motherboard UART
    "USB0::0x1234::0x5678::sn::0::INSTR",  # somebody's USB widget
])
def test_what_is_not_an_instrument_here_is_dropped(address):
    assert not addresses.keep(address, PORTS)


def test_show_all_brings_back_everything_still_labelled():
    labels, mapping = addresses.filtered(SCAN, show_all=True, ports=PORTS)
    assert len(labels) == len(SCAN)
    assert "TCPIP::129.67.86.137::INSTR" in labels
    assert mapping["Keithley 2401 - GPIB0::24::INSTR"] == "GPIB0::24::INSTR"


def test_usb_ids_are_read_in_whichever_base_the_backend_wrote_them():
    assert addresses.usb_ids("USB0::8580::125::x::0::INSTR") == (0x2184, 0x7D)
    assert addresses.usb_ids("USB0::0x2184::0x007D::x::0::INSTR") == \
        (0x2184, 0x7D)
    assert addresses.usb_ids("GPIB0::9::INSTR") is None


def test_a_label_goes_back_to_the_address_it_came_from():
    for address in SCAN:
        assert addresses.address_of(addresses.label(address, PORTS)) == address


def test_a_typed_address_passes_through_untouched():
    """The box is a box: whatever is typed is what gets opened."""
    assert addresses.address_of("GPIB0::26::INSTR") == "GPIB0::26::INSTR"
    assert addresses.address_of("  COM7 ") == "COM7"
    assert addresses.address_of("TCPIP::10.0.0.4::INSTR") == \
        "TCPIP::10.0.0.4::INSTR"


def test_a_serial_port_is_matched_by_its_com_name():
    assert addresses.com_port_of("ASRL6::INSTR") == "COM6"
    assert addresses.describe("COM6", PORTS) == "Multicomp Pro 72-13200"
    assert addresses.keep("COM5", PORTS)


def test_the_scan_no_longer_asks_for_network_instruments():
    """The patterns are what stop the network scan happening at all;
    filtering the results afterwards would leave the delay and the
    warnings in place."""
    from smuniversal_lab_suite.core.transports.visa_transport import (
        VisaTransport,
    )
    patterns = VisaTransport.LIST_PATTERNS
    assert not any(p.startswith("TCPIP") or p.startswith("?*")
                   for p in patterns), patterns
    assert any(p.startswith("GPIB") for p in patterns)
    assert any(p.startswith("USB") for p in patterns)
    assert any(p.startswith("ASRL") for p in patterns)


# ------------------------------------------------------------------
# telling one USB-serial device from another
# ------------------------------------------------------------------
def test_a_device_that_says_what_it_is_is_named_by_it():
    """The miniSMU's USB ids are not written down anywhere, and it is
    still not "some USB serial device"."""
    assert addresses.describe("COM5", PORTS) == "Undalogic miniSMU MS01"


def test_a_generic_bridge_is_not_mistaken_for_an_instrument():
    """An Arduino on a CH340 is kept - it is a USB device - but it is
    not given an instrument's name."""
    assert addresses.keep("COM9", PORTS)
    assert addresses.describe("COM9", PORTS) == "USB-SERIAL CH340"


def test_nothing_here_is_keyed_on_a_com_number():
    """The same device on another machine gets another COM number, and
    must still be the same instrument."""
    moved = {"COM12": PORTS["COM6"]}
    assert addresses.describe("COM12", moved) == "Multicomp Pro 72-13200"
    assert addresses.keep("ASRL12::INSTR", moved)
    assert addresses.identity_key("COM12", moved) == \
        addresses.identity_key("COM6", PORTS)


def test_a_connect_teaches_the_dropdown_what_answered():
    addresses.LEARNED.clear()
    try:
        # A GPIB address with nothing recorded against it.
        assert addresses.describe("GPIB0::18::INSTR", PORTS) is None
        addresses.remember("GPIB0::18::INSTR", "Keithley 2450", PORTS)
        assert addresses.describe("GPIB0::18::INSTR", PORTS) == "Keithley 2450"

        # What answered outranks the wiring table, which is somebody's
        # note about how things were plugged in last time.
        addresses.remember("GPIB0::24::INSTR", "Keithley 2450", PORTS)
        assert addresses.describe("GPIB0::24::INSTR", PORTS) == "Keithley 2450"
    finally:
        addresses.LEARNED.clear()


def test_a_learned_serial_name_follows_the_device_not_the_port():
    addresses.LEARNED.clear()
    try:
        addresses.remember("COM5", "Undalogic miniSMU MS01", PORTS)
        moved = {"COM12": PORTS["COM5"]}
        assert addresses.describe("COM12", moved) == "Undalogic miniSMU MS01"
        # ...and not to whatever else lands on COM5 next.
        other = {"COM5": PORTS["COM9"]}
        assert addresses.describe("COM5", other) == "USB-SERIAL CH340"
    finally:
        addresses.LEARNED.clear()


def test_listing_ports_never_opens_one():
    """Opening a serial port toggles DTR, which resets an ESP32-based
    device like the miniSMU. A dropdown refresh must not do that to an
    instrument somebody is using, so the naming reads descriptors the
    host already has."""
    import inspect

    source = inspect.getsource(addresses)
    assert "serial.Serial" not in source
    assert "open(" not in source.replace("open()", "")
