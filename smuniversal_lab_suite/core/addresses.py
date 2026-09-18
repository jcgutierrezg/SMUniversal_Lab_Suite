"""Which addresses belong to this bench, and what to call them.

The dropdown used to show whatever a VISA scan returned. On this machine
that is a dozen entries, most of which are not instruments: phantom
`ASRL1::INSTR` motherboard COM ports, `TCPIP::…::INSTR` entries invented
by a network scan, and `::RAW` duplicates of the same USB device. The
four that matter are in there somewhere, spelled
`USB0::8580::125::gew852313::0::INSTR`.

Two jobs, kept apart
--------------------
**Keeping** decides whether an address is one of this bench's
instruments. **Naming** decides what to call it. An address can be kept
without being named - every GPIB address is kept, because the GPIB
adapter is this bench's own, whether or not the map below says what is
plugged into it.

Why a table here rather than on the drivers
-------------------------------------------
A driver identifies an instrument by what it answers to `*IDN?`, which
is the honest question and needs the instrument to be open. This table
answers a different one - "is this address worth showing before anything
is opened" - from the bus id alone. Putting it on the drivers would mean
touching every driver file to add a fact about *this bench's wiring*,
and a driver's bench note goes stale on any byte changed in the files
its commissioning covers.

Nothing here is load-bearing for a measurement. At worst a wrong entry
mislabels a dropdown row; the instrument is still identified from
`*IDN?` at connect, and a mismatch is refused there.
"""
import re

#: GPIB address -> what is plugged into it on this bench. Addresses are
#: matched without the trailing `::INSTR`, so `GPIB0::9` covers
#: `GPIB0::9::INSTR`.
#:
#: **This is bench wiring, not a fact about the instruments.** Re-address
#: an instrument on its front panel and this is wrong until it is
#: edited; that is the trade the fixed map makes for naming a GPIB
#: address without opening it. The name is a label only - what actually
#: identifies an instrument is its `*IDN?` reply at connect.
GPIB_MAP = {
    # Read off this bench's own commissioning reports in `checkups/`,
    # which record the address every checkup was run at.
    "GPIB0::9": "Keysight B2901A",
    "GPIB0::24": "Keithley 2401",
    "GPIB0::25": "Keithley 2611A",
    "GPIB0::27": "Keithley 2635B",
    # The 2450 has never been commissioned here - see
    # `docs/open/checkup-owed.md` - so there is no address to record. It
    # still appears in the dropdown, unnamed, like any other GPIB
    # address.
}

#: USB (vendor id, product id) -> instrument, for the USB-TMC members of
#: the fleet. Ids are as VISA spells them in the resource string, which
#: is decimal on some backends and `0x`-prefixed hex on others, so both
#: are normalised to integers before lookup.
USB_IDS = {
    (0x2184, 0x007D): "GW Instek GSM-20H10",      # 8580::125 in decimal
    (0x0957, 0x4118): "Keysight U2722A",
}

#: Serial (vendor id, product id) -> instrument, matched against what
#: pyserial reports for a COM port.
SERIAL_IDS = {
    (0x0416, 0x5011): "Multicomp Pro 72-13200",
    # The miniSMU is on COM5 on this bench but its USB ids have never
    # been written down. It is kept and shown anyway, by the rule below
    # that a USB-attached port is a device somebody plugged in; add it
    # here to have it named.
}

#: Interfaces this bench uses. Everything else - TCPIP above all - is
#: not scanned for and not shown; a LAN instrument is still reachable by
#: typing its address into the box, which stays editable.
KEPT_INTERFACES = ("GPIB", "USB", "ASRL")

_ADDRESS = re.compile(r"^(?P<interface>[A-Za-z]+)(?P<board>\d*)::(?P<rest>.*)$")


def _number(text):
    """`0x05E6`, `1510` or `05E6` as an int, or None."""
    text = str(text).strip()
    try:
        return int(text, 0)
    except ValueError:
        pass
    try:
        return int(text, 16)
    except ValueError:
        return None


def interface_of(address):
    """`GPIB`, `USB`, `ASRL`, `TCPIP`... or "" if it is not an address."""
    match = _ADDRESS.match(str(address).strip())
    return match.group("interface").upper() if match else ""


def usb_ids(address):
    """(vendor, product) from a USB resource string, or None."""
    parts = str(address).split("::")
    if len(parts) < 3 or not parts[0].upper().startswith("USB"):
        return None
    vendor, product = _number(parts[1]), _number(parts[2])
    if vendor is None or product is None:
        return None
    return (vendor, product)


def com_port_of(address):
    """`ASRL3::INSTR` -> `COM3`, the name pyserial knows it by.

    Windows only in effect, which is where this bench is. On anything
    else the ASRL number is not a COM number and this returns None, so
    the port is matched by its own name instead.
    """
    match = _ADDRESS.match(str(address).strip())
    if match is None or match.group("interface").upper() != "ASRL":
        return None
    digits = match.group("board")
    if not digits:
        # `ASRL::3::INSTR` rather than `ASRL3::INSTR`; both spellings
        # exist in the wild and mean the same port.
        digits = match.group("rest").split("::")[0]
    return f"COM{digits}" if digits.isdigit() else None


def serial_ports():
    """`{port name: ((vendor id, product id), description)}` for this host.

    A port with no vendor id is not a USB device: on this bench those
    are the motherboard's own UARTs, which is what `ASRL1::INSTR` and
    `ASRL3::INSTR` are, and no instrument has ever been on one. That is
    the difference `keep()` uses.

    Empty when pyserial is missing, which leaves every serial address
    unnamed and unkept rather than raising - the same shape the
    transports take.
    """
    try:
        from serial.tools import list_ports
    except Exception:
        return {}
    out = {}
    try:
        for port in list_ports.comports():
            out[port.device] = ((port.vid, port.pid),
                                (port.description or "").strip())
    except Exception:
        return {}
    return out


def describe(address, ports=None):
    """What to call this address, or None when nothing here knows.

    `ports` is the mapping `serial_ports()` returns, passed in so a
    dropdown refresh enumerates the host's ports once rather than once
    per address.
    """
    text = str(address).strip()
    interface = interface_of(text)

    if interface == "GPIB":
        bare = text.upper().replace("::INSTR", "")
        return GPIB_MAP.get(bare)

    if interface == "USB":
        return USB_IDS.get(usb_ids(text))

    if interface == "ASRL" or text.upper().startswith("COM"):
        port = com_port_of(text) or text.upper()
        info = (ports if ports is not None else serial_ports()).get(port)
        if not info:
            return None
        ids, description = info
        named = SERIAL_IDS.get(ids)
        if named:
            return named
        # Not in the table, but the host knows what the device calls
        # itself. "Silicon Labs CP210x UART Bridge" is not the
        # instrument's name and is still far more use than `ASRL5`.
        return description or None

    return None


def keep(address, ports=None):
    """True if this address is one of the bench's instruments.

    GPIB is kept whatever is on it: the adapter is this bench's own, and
    an instrument moved to a new address must not vanish from the list
    because a table was not updated. USB and serial are kept when the
    bus ids say which instrument they are, which is what removes the
    phantom `ASRL1::INSTR` ports and every device that is not an
    instrument at all.
    """
    interface = interface_of(address)
    if interface == "GPIB":
        return True
    if interface == "USB":
        return usb_ids(address) in USB_IDS
    if interface == "ASRL" or str(address).upper().startswith("COM"):
        # Kept when it is a USB device, named or not: the miniSMU's ids
        # are not written down anywhere and it must still be in the
        # list. A port with no USB ids behind it is a motherboard UART.
        port = com_port_of(address) or str(address).upper()
        info = (ports if ports is not None else serial_ports()).get(port)
        return bool(info and info[0][0] is not None)
    return False


def label(address, ports=None):
    """The dropdown entry: `Keysight B2901A - GPIB0::9::INSTR`.

    The address stays in the label rather than being replaced by the
    name. Two of the same model would otherwise be one entry written
    twice, and the address is what a person compares against the sticker
    on the back of the instrument.
    """
    name = describe(address, ports)
    return f"{name} - {address}" if name else str(address)


def address_of(label_text):
    """The address back out of a label, for connecting.

    A typed address is returned unchanged, so the box stays a box: this
    only has to undo what `label()` did.
    """
    text = str(label_text).strip()
    return text.split(" - ", 1)[1].strip() if " - " in text else text


def filtered(addresses, show_all=False, ports=None):
    """`(labels, mapping)` for the dropdown, in the order given.

    `show_all` keeps everything the scan found, still labelled where a
    name is known, for a borrowed instrument that is not in the tables.
    """
    if ports is None:
        ports = serial_ports()
    labels, mapping = [], {}
    for address in addresses:
        if not show_all and not keep(address, ports):
            continue
        text = label(address, ports)
        if text not in mapping:
            labels.append(text)
            mapping[text] = str(address)
    return labels, mapping
