"""
VISA backend diagnostic - run this when an instrument is plugged in,
powered on, and not in the address dropdown.

    uv run tools/visa_doctor.py

It answers one question the dropdown cannot: *which layer is failing?*
An empty list has at least four causes that look identical from the GUI,
and they have different fixes:

  1. No VISA implementation is installed at all.
  2. A vendor implementation is installed but does not know about this
     instrument. Keysight's USB modular boxes (the U2722A included) are
     a classic case - the vendor library is present and healthy and
     simply does not enumerate them.
  3. pyvisa-py is present but has no USB layer under it. Without pyusb
     and a libusb binary it will happily enumerate GPIB and sockets and
     find zero USB devices, reporting no error while doing so. This is
     the quietest failure of the four.
  4. The instrument is enumerating as something other than ::INSTR -
     ::RAW, usually - so pyvisa's default `?*::INSTR` filter hides it.

The script prints what every backend sees under every pattern, checks
the USB layer directly, and optionally sends *IDN? to whatever it finds.

Nothing here is imported by the app. It is a bench tool.
"""
import sys, os
from core.transports.base import TransportDesynchronised
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATTERNS = ("?*::INSTR", "?*")
BACKENDS = ("", "@py")


def heading(text):
    print(f"\n{text}\n{'-' * len(text)}")


def check_imports():
    heading("Layers")
    try:
        import pyvisa
        print(f"  pyvisa           {pyvisa.__version__}")
    except ImportError:
        print("  pyvisa           MISSING  ->  uv add pyvisa")
        return None

    try:
        import pyvisa_py
        print(f"  pyvisa-py        {getattr(pyvisa_py, '__version__', 'present')}")
    except ImportError:
        print("  pyvisa-py        MISSING  ->  uv add pyvisa-py")

    # The quiet one. pyvisa-py without pyusb does not error, it just
    # never reports a USB instrument.
    try:
        import usb.core
        print("  pyusb            present")
        try:
            backend_found = usb.core.find() is not None or True
            devices = list(usb.core.find(find_all=True))
            print(f"  libusb           working - {len(devices)} USB device(s) visible")
        except Exception as exc:
            print(f"  libusb           NOT WORKING - {exc}")
            print("                   ->  uv add libusb-package")
    except ImportError:
        print("  pyusb            MISSING  ->  uv add pyusb libusb-package")
        print("                   without it, '@py' finds NO USB instruments")
        print("                   and reports no error while doing so")
    return pyvisa


def scan(pyvisa):
    heading("What each backend sees")
    everything = {}
    for spec in BACKENDS:
        label = spec or "default (vendor, if installed)"
        rm = None
        try:
            rm = pyvisa.ResourceManager(spec) if spec \
                else pyvisa.ResourceManager()
        except Exception as exc:
            print(f"\n  {label}")
            print(f"    unavailable: {exc}")
            continue

        print(f"\n  {label}")
        try:
            print(f"    implementation: {rm.visalib}")
        except Exception:
            pass
        for pattern in PATTERNS:
            try:
                found = list(rm.list_resources(pattern))
            except Exception as exc:
                print(f"    {pattern:<12} error: {exc}")
                continue
            print(f"    {pattern:<12} {found if found else 'nothing'}")
            for name in found:
                everything.setdefault(name, []).append(spec or "default")
        try:
            rm.close()
        except Exception:
            pass
    return everything


def interpret(everything):
    heading("Reading")
    if not everything:
        print("  Nothing found by any backend.")
        print("  - Is the instrument powered and the cable in a port that")
        print("    carries data rather than only power?")
        print("  - If it is USB and the layers above show pyusb missing,")
        print("    fix that first: that alone hides every USB instrument.")
        return

    for name, backends in sorted(everything.items()):
        who = ", ".join(backends)
        print(f"  {name}")
        print(f"      seen by: {who}")
        if len(backends) == 1:
            print(f"      -> only one backend can see this. The app merges "
                  f"both, so it will appear in the dropdown, and connect "
                  f"will fall through to '{backends[0]}' automatically.")
        if "::RAW" in name.upper():
            print("      -> enumerates as ::RAW, so pyvisa's default "
                  "'?*::INSTR' filter would have hidden it entirely.")


def identify(pyvisa, everything):
    if not everything:
        return
    heading("*IDN? on each")
    print("  (a resource that lists but will not answer is a different "
          "problem from one that never listed)\n")
    for name, backends in sorted(everything.items()):
        spec = backends[0]
        rm = None
        try:
            rm = pyvisa.ResourceManager(spec) if spec \
                else pyvisa.ResourceManager()
            res = rm.open_resource(name)
            res.timeout = 3000
            try:
                reply = res.query("*IDN?").strip()
                print(f"  {name}\n      {reply}")
            finally:
                res.close()
        except TransportDesynchronised:
            raise
        except Exception as exc:
            print(f"  {name}\n      no reply: {exc}")
        finally:
            if rm is not None:
                try:
                    rm.close()
                except Exception:
                    pass


def main():
    print("VISA backend diagnostic")
    pyvisa = check_imports()
    if pyvisa is None:
        return 1
    everything = scan(pyvisa)
    interpret(everything)
    if "--idn" in sys.argv:
        identify(pyvisa, everything)
    else:
        print("\n  (re-run with --idn to send *IDN? to everything found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
