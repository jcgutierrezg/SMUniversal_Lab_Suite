"""What happens on a machine whose install is missing a package.

Every instrument's library is part of the one install - there are no
optional extras, so every machine that ran `uv sync` has them all. A
package can still go missing: a half-finished install, an environment
copied by hand, a sync interrupted by a dropped network. When it does,
the absence has to be **legible**: an opaque `ImportError` at the moment
an operator selects an instrument leaves them debugging Python at a
bench instead of measuring.

So each library is asked the same three questions here:

1. does the application still start without it?
2. when the thing it enables is actually reached, does the failure name
   the fix rather than the traceback?
3. and for the one whose absence is *silent*, does something say so?

That third one is the USB layer. `MiniSMUTransport.connect()` and
`NIUSBGPIBTransport.connect()` fail loudly on their own. pyvisa-py
without a USB layer raises nothing at all - it enumerates GPIB and
sockets, reports success, and never mentions a USB device. An empty
dropdown and an unplugged cable look identical, which is exactly how
the Keysight U2722A once went missing while plugged in and working.

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
# one install
# ------------------------------------------------------------------
def test_there_is_one_install_for_every_machine():
    """No optional extras: `uv sync` gives every machine everything.

    They existed for a while (review A-11), and a machine that forgot
    one lost an instrument without saying so. Reintroducing one means
    every bench needs to know a flag again - so it fails here, where the
    decision can be revisited on purpose rather than drifted into.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"].get("optional-dependencies", {})
    assert not extras, (
        f"optional extras are back: {sorted(extras)} - every instrument's "
        f"library is meant to be in the one install")


def test_no_message_tells_an_operator_to_add_an_extra():
    """With no extras, `--extra <name>` is an instruction that fails.

    Searched in the production tree, because that is what an operator
    will be copying out of an error message.
    """
    sources = []
    for folder in (ROOT / "smuniversal_lab_suite", ROOT / "tools"):
        # Missing, it would scan as empty and pass.
        assert folder.is_dir(), f"{folder} does not exist"
        sources.extend(folder.rglob("*.py"))
        sources.extend(folder.rglob("*.ps1"))
    stale = [str(p.relative_to(ROOT)) for p in sources
             if "--extra" in p.read_text(encoding="utf-8")]
    assert not stale, f"these still tell an operator to use --extra: {stale}"


# ------------------------------------------------------------------
# minismu
# ------------------------------------------------------------------
def test_the_app_starts_without_minismu():
    """The whole fleet must not go down with one absent vendor library."""
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['minismu_py'] = None\n"
        "import smuniversal_lab_suite.core.base_app\n"
        "import smuniversal_lab_suite.drivers.registry\n"
        "from smuniversal_lab_suite.drivers.undalogic_minismu import UndalogicMiniSMU\n"
        "from smuniversal_lab_suite.core.transports.minismu_transport import MiniSMUTransport\n"
        "print('ok')\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_connecting_a_minismu_without_its_library_names_the_fix():
    """The failure an operator actually meets, and what it has to say.

    Two claims: it must be a `RuntimeError` carrying a sentence, not
    the `ImportError` from somewhere inside a vendor package - and the
    sentence has to name the command that fixes it, because on a broken
    install this message is the whole of the diagnosis.
    """
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['minismu_py'] = None\n"
        "from smuniversal_lab_suite.core.transports.minismu_transport import MiniSMUTransport\n"
        "try:\n"
        "    MiniSMUTransport().connect('COM9')\n"
        "except RuntimeError as exc:\n"
        "    print('RUNTIMEERROR', exc)\n"
        "except ImportError as exc:\n"
        "    print('IMPORTERROR', exc)\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.startswith("RUNTIMEERROR"), result.stdout
    assert "uv sync" in result.stdout, result.stdout
    assert "--extra" not in result.stdout, result.stdout


# ------------------------------------------------------------------
# usb - the silent one
# ------------------------------------------------------------------
def test_the_app_starts_without_the_usb_layer():
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['usb'] = None\n"
        "sys.modules['usb.core'] = None\n"
        "sys.modules['libusb_package'] = None\n"
        "import smuniversal_lab_suite.core.base_app\n"
        "import smuniversal_lab_suite.drivers.registry\n"
        "from smuniversal_lab_suite.core.transports.visa_transport import VisaTransport\n"
        "print('ok')\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_a_missing_usb_layer_is_reported_rather_than_looking_like_no_devices():
    """The scan says why it can see no USB instrument.

    Without it, a broken install reintroduces the U2722A fault -
    plugged in, working, absent from the dropdown, no error anywhere.
    """
    result = _in_a_fresh_process(
        "import sys\n"
        "sys.modules['usb'] = None\n"
        "sys.modules['usb.core'] = None\n"
        "from smuniversal_lab_suite.core.transports.visa_transport import usb_layer_note\n"
        "print(usb_layer_note())\n")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "uv sync" in result.stdout, result.stdout


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
        "from smuniversal_lab_suite.core.transports import visa_transport as vt\n"
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
    assert "uv sync" in py_line[0], py_line[0]

    default_line = [ln for ln in joined.split("|")
                    if ln.startswith("default:")]
    assert "usb" not in default_line[0].lower(), (
        f"a vendor backend brings its own USB layer, so the note does "
        f"not belong on its line: {default_line[0]}")


def test_the_note_is_absent_when_the_layer_is_present():
    """The control. A note that is always there says nothing.

    Skipped rather than failed where the layer is genuinely missing,
    which is a broken install - the thing every test above is about.
    """
    from smuniversal_lab_suite.core.transports.visa_transport import (
        usb_layer_note,
    )

    try:
        import libusb_package
        import usb.core  # noqa: F401 - probed, not used
    except ImportError:
        pytest.skip("the USB layer is not installed in this environment")
    if libusb_package.get_libusb1_backend() is None:
        pytest.skip("libusb-package supplied no backend on this machine")

    assert usb_layer_note() is None
