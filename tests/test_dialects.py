"""End-to-end: same experiment code, two dialects, verified numbers."""
import pytest

pytestmark = [pytest.mark.gui]

import tkinter as tk
from core.transports.base import Transport
from core.base_app import LabApp
from core.parameters import VanDerPauwParameters
from experiments.vanderpauw.experiment import VanDerPauwExperiment
from drivers.keithley_2450 import Keithley2450
from drivers.keithley_2611a import Keithley2611A

class FakeTransport(Transport):
    """Pretends to be an instrument. Logs writes; returns a fixed
    V/I pair so resistance comes out to exactly 1234.0 ohm."""
    def __init__(self, idn):
        super().__init__(); self.idn = idn; self.sent = []; self.connected = True
    def connect(self, address, **kw): self.connected = True
    def close(self): self.connected = False
    def _write(self, t): self.sent.append(t)
    def _read(self, timeout_s):
        last = self.sent[-1] if self.sent else ""
        if "IDN" in last: return self.idn
        # Field order is part of the dialect. SCPI :READ? answers
        # voltage-first; TSP's smu.measure.iv() answers *current* first,
        # which the 2611A driver documents and handles. Before Wave 0a
        # this fake returned the SCPI order to both drivers, so the 2611A
        # correctly parsed I as V and returned 1/1234 - and the script
        # printed "identical R: False" and exited 0 regardless.
        if "measure.iv" in last:
            return "1.000000E-04,1.234000E-01"   # I=100uA, V=0.1234
        return "1.234000E-01,1.000000E-04"       # V=0.1234, I=100uA

EXPECTED_OHM = 1234.0


def test_two_dialects_agree(check):
    results = {}
    for drv_cls, idn in [(Keithley2450, "KEITHLEY,MODEL 2450,1,1.0"),
                         (Keithley2611A, "Keithley, Model 2611A, 1, 3.0")]:
        root = tk.Tk()
        app = LabApp(root, VanDerPauwExperiment)
        e = app.experiment
        t = FakeTransport(idn)
        drv = drv_cls(t)
        app.transports["source"] = t
        app.instruments["source"] = drv
        e.on_connected("source", drv)
        root.update()

        t.sent.clear()
        # Wave 5a-i: `_polarity_block` takes a run context and a frozen
        # parameter snapshot rather than loose arguments. A real run
        # context is opened here rather than a stub, because the block
        # now checkpoints and sleeps through it - a stub would be a
        # second implementation of the thing under test.
        #
        # The run is deliberately never committed. This file is about
        # what goes out on the wire, not about the commit gate, and the
        # instrument is a fake that cannot confirm a shutdown.
        params = VanDerPauwParameters(
            sample=app.samples.ref("dialects"), position=1,
            level_a=1e-4, points_n=3, delay_s=0.0, compliance_v=0.3)
        with e.begin_run(parameters=params) as run:
            run.start()
            r = e._polarity_block(run, drv, params, +1)
        results[drv_cls.DISPLAY_NAME] = (r, list(t.sent))
        root.destroy()

    print("=== Same experiment code, two command dialects ===\n")
    for name, (r, sent) in results.items():
        print(f"{name}:  averaged R = {r}")
        for c in sent[:5]:
            print(f"     -> {c}")
        print()

    vals = [r for r, _ in results.values()]
    print("Both drivers returned identical R:", vals[0] == vals[1], "=", vals[0])

    check("both drivers returned identical R", vals[0] == vals[1],
          f"{vals[0]} vs {vals[1]}")
    check("and it is the resistance the fake transport implies",
          abs(vals[0] - EXPECTED_OHM) < 1e-6, f"{vals[0]} vs {EXPECTED_OHM}")
    check("the two dialects differ on the wire",
          [tuple(x) for _, x in results.values()][0]
          != [tuple(x) for _, x in results.values()][1])
