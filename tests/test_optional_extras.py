"""What happens on a machine that did not install an extra.

Review A-11 moved the miniSMU vendor library and the USB layer out of
the default install. That trade is only worth making if the absence is
**legible**: an extra that turns a missing package into an opaque
`ImportError` at the moment an operator selects an instrument is worse
than shipping it to everybody, because the operator is now debugging
Python at a bench instead of measuring.

So each extra is asked the same three questions here:

1. does the application still start without it?
2. when the thing it enables is actually reached, does the failure name
   the extra rather than the traceback?
3. and for the one whose absence is *silent*, does something say so?

That third one is the whole reason `usb` was the hard case. Every other
optional path fails loudly on its own: `MiniSMUTransport.connect()`
raises, `NIUSBGPIBTransport.connect()` raises. pyvisa-py without a USB
layer raises nothing at all - it enumerates GPIB and sockets, reports
success, and never mentions a USB device. An empty dropdown and an
unplugged cable look identical, which is exactly how the Keysight
U2722A went missing while plugged in and working.

Absence is simulated with `sys.modules[name] = None`, which makes any
`import name` raise `ImportError`. That is the same trick
`test_packaging.py` already uses, and it tests the real code path
rather than a machine somebody has to remember to prepare.

No Tk and no instruments: this file runs in the fast shared process.
"""
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _in_a_fresh_process(script):
    """Run `script` in a child interpreter and return its result.

    A child rather than `monkeypatch`, because these tests are about
    what happens at *import* time on a machine without the package, and
    this process has already imported the real ones.
    """
    return subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          capture_output=True, text=True)


# ------------------------------------------------------------------
# the extras themselves
# ------------------------------------------------------------------
def test_every_extra_is_named_in_at_least_one_install_message():
    """An extra nobody can be told to install is a dead end.

    The mechanical half of the rule this file exists for: if the code
    can reach a state that only `--extra <name>` fixes, some message
    somewhere has to say `--extra <name>`. Checked by searching the
    production tree for the literal flag, because that is what an
    operator will be copying.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"].get("optional-dependencies", {})

    sources = []
    for folder in ("core", "devices", "drivers", "experiments", "tools"):
        sources.extend((ROOT / folder).rglob("*.py"))
    text = "\n".join(p.read_text(encoding="utf-8") for p in sources)

    # `bench` is the convenience alias rather than a capability of its
    # own, so it is exempt from needing a failure that names it.
    unmentioned = [name for name in extras
                   if name != "bench" and f"--extra {name}" not in text]
    assert not unmentioned, (
        f"these extras exist and nothing tells an operator to install "
        f"them: {unmentioned}")


# ------------------------------------------------------------------
# minismu
# ------------------------------------------------------------------
def test_the_app_starts_without_the_minismu_extra():
    """The whole fleet must not go down with one absent vendor library."""
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['minismu_py'] = None\n"
        "import core.base_app, drivers.registry\n"
        "from drivers.undalogic_minismu import UndalogicMiniSMU\n"
        "from core.transports.minismu_transport import MiniSMUTransport\n"
        "print('ok')\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_connecting_a_minismu_without_the_extra_names_the_extra():
    """The failure an operator actually meets, and what it has to say.

    Two claims, and the second is the one A-11 turns on: it must be a
    `RuntimeError` carrying a sentence, not the `ImportError` from
    somewhere inside a vendor package - and the sentence has to name the
    flag that fixes it, because on a machine that never installed the
    extra this message is the whole of the diagnosis.
    """
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['minismu_py'] = None\n"
        "from core.transports.minismu_transport import MiniSMUTransport\n"
        "try:\n"
        "    MiniSMUTransport().connect('COM9')\n"
        "except RuntimeError as exc:\n"
        "    print('RUNTIMEERROR', exc)\n"
        "except ImportError as exc:\n"
        "    print('IMPORTERROR', exc)\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.startswith("RUNTIMEERROR"), result.stdout
    assert "--extra minismu" in result.stdout, result.stdout


# ------------------------------------------------------------------
# usb - the silent one
# ------------------------------------------------------------------
def test_the_app_starts_without_the_usb_extra():
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['usb'] = None\n"
        "sys.modules['usb.core'] = None\n"
        "sys.modules['libusb_package'] = None\n"
        "import core.base_app, drivers.registry\n"
        "from core.transports.visa_transport import VisaTransport\n"
        "print('ok')\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_a_missing_usb_layer_is_reported_rather_than_looking_like_no_devices():
    """The scan says why it can see no USB instrument.

    This is the assertion the `usb` extra had to earn before it could
    exist. Without it, moving PyUSB out of the default install
    reintroduces the U2722A fault - plugged in, working, absent from the
    dropdown, no error anywhere - for every machine that runs a plain
    `uv sync`.
    """
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['usb'] = None\n"
        "sys.modules['usb.core'] = None\n"
        "from core.transports.visa_transport import usb_layer_note\n"
        "print(usb_layer_note())\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "--extra usb" in result.stdout, result.stdout


def test_the_note_reaches_the_console_line_the_operator_reads():
    """`usb_layer_note()` being right is not enough; it has to arrive.

    The note is appended to the "@py" line of `scan_summary()`, which is
    what the connection panel prints after a refresh. Checked through
    that function rather than by calling the note directly, because a
    correct diagnostic nothing displays is the same as no diagnostic.

    The line *count* is asserted too: the note rides on its backend's
    own line rather than adding one, so "how many backends were asked"
    keeps meaning that.
    """
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['usb'] = None\n"
        "sys.modules['usb.core'] = None\n"
        "from core.transports import visa_transport as vt\n"
        "\n"
        "class FakeRM:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def list_resources(self, pattern='?*::INSTR'): return ()\n"
        "    def close(self): pass\n"
        "\n"
        "class FakePyvisa:\n"
        "    ResourceManager = FakeRM\n"
        "\n"
        "vt.pyvisa = FakePyvisa\n"
        "vt.VisaTransport.LAST_SCAN = []\n"
        "lines = vt.VisaTransport.scan_summary()\n"
        "print(len(lines))\n"
        "print('|'.join(lines))\n")
    assert result.returncode == 0, result.stderr[-1500:]
    count, joined = result.stdout.splitlines()[:2]
    assert count == "2", f"one line per backend, got {count}: {joined}"

    py_line = [ln for ln in joined.split("|") if ln.startswith("@py:")]
    assert py_line, joined
    assert "--extra usb" in py_line[0], py_line[0]

    default_line = [ln for ln in joined.split("|")
                    if ln.startswith("default:")]
    assert "usb" not in default_line[0].lower(), (
        f"a vendor backend brings its own USB layer, so the note does "
        f"not belong on its line: {default_line[0]}")


def test_the_note_is_absent_when_the_layer_is_present():
    """The control. A note that is always there says nothing.

    Skipped rather than failed where the extra is genuinely not
    installed - which is a legitimate developer environment, and the
    thing every test above is about.
    """
    from core.transports.visa_transport import usb_layer_note

    try:
        import libusb_package
        import usb.core  # noqa: F401 - probed, not used
    except ImportError:
        pytest.skip("the usb extra is not installed in this environment")
    if libusb_package.get_libusb1_backend() is None:
        pytest.skip("libusb-package supplied no backend on this machine")

    assert usb_layer_note() is None
