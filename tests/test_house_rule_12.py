import sys, os

"""House rule 12, on every experiment: configure before energising.

Wave 6b, decision W6b-3. Review §33 - "compliance configured before
output-on" and "source-function change while output is active".

`test_iv_lifecycle.py` already enforces this for the IV sweep, which is
where the rule came from. This file extends it to Van der Pauw, Hall and
Ossila 4PP, which were checked by hand during Wave 6 and had nothing
stopping them regressing.

Why the experiments are run rather than the methods inspected
------------------------------------------------------------
Ordering is not a property of any single driver method. Every call can
be individually correct and the sequence still put a compliance after
the output came on. So each experiment is driven through a recording
proxy and the resulting order inspected - the orchestra playing the
piece, rather than each musician checked alone.

Driven through `_do_run()` rather than `run_pressed()` on purpose.
`run_pressed()` goes through the UI gate, which can raise a modal
dialog, and a modal dialog under a virtual display hangs the runner
instead of failing it. A hung test reads as an infrastructure problem in
CI, which is worse than a red one.
"""
import tkinter as tk

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

from core.base_app import LabApp
from core.transports.null_transport import NullTransport
from experiments.vanderpauw.experiment import VanDerPauwExperiment
from experiments.hall.experiment import HallExperiment
from experiments.ossila_4pp.experiment import Ossila4PPExperiment


#: Anything that configures the instrument. If one of these lands
#: between an output_on and its output_off, the rule is broken.
CONFIG_CALLS = {
    "set_source_function", "set_current_limit", "set_voltage_limit",
    "set_current_range", "set_voltage_range", "set_remote_sense",
    "set_nplc", "set_output_off_mode", "set_voltage_protection",
    "set_source_delay",
}

#: (label, class, name of the method that builds a parameter snapshot).
#: The builders are not uniformly named across the experiments - Van der
#: Pauw and Hall call theirs `_run_params`, 4PP calls its `_sweep_params`
#: - so the name is carried here rather than guessed at.
EXPERIMENTS = [
    ("Van der Pauw", VanDerPauwExperiment, "_run_params"),
    ("Hall", HallExperiment, "_run_params"),
    ("Ossila 4PP", Ossila4PPExperiment, "_sweep_params"),
]


class Recorder:
    """Passes through to the real driver, writing down call order."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def recorded(*a, **kw):
            self.calls.append(name)
            return attr(*a, **kw)
        return recorded

    def while_energised(self):
        out, live = [], False
        for name in self.calls:
            if name == "output_on":
                live = True
            elif name in ("output_off", "safe_output_off"):
                live = False
            elif live:
                out.append(name)
        return out


def drive(root, experiment_cls, params_method):
    app = LabApp(root, experiment_cls)
    app.connect_role("source", NullTransport(), "demo")
    root.update_idletasks()
    exp = app.experiment
    rec = Recorder(app.instruments["source"])
    app.instruments["source"] = rec

    params = getattr(exp, params_method)()
    if hasattr(exp, "_check_limits"):
        exp._check_limits(params)
    exp._do_run(params)
    for _ in range(60):
        root.update()
    return exp, rec


@pytest.mark.parametrize("label,cls,params_method", EXPERIMENTS,
                         ids=[e[0] for e in EXPERIMENTS])
def test_nothing_is_configured_while_the_sample_is_live(check, label, cls,
                                                        params_method):
    root = tk.Tk()
    try:
        exp, rec = drive(root, cls, params_method)

        # Control. Without it, an experiment that failed before it ever
        # energised would pass this file trivially - the exact shape of
        # "an assertion that would be true whether or not the thing
        # worked".
        check(f"{label}: the output was actually turned on",
              "output_on" in rec.calls,
              f"calls were {rec.calls[:12]}")
        check(f"{label}: the instrument was actually configured",
              any(c in CONFIG_CALLS for c in rec.calls),
              "nothing was configured")

        offenders = [c for c in rec.while_energised() if c in CONFIG_CALLS]
        check(f"{label}: no configuration under a live output",
              not offenders, ", ".join(sorted(set(offenders))))
    finally:
        root.destroy()


@pytest.mark.parametrize("label,cls,params_method", EXPERIMENTS,
                         ids=[e[0] for e in EXPERIMENTS])
def test_the_source_function_never_changes_while_energised(check, label, cls,
                                                           params_method):
    """Called out separately in §33, and it is the worst of the set.

    A source-function change under a live output is a compliance change
    under a live output: on every instrument here the limit that applies
    belongs to the function being sourced, so switching function swaps
    in a limit this run may never have written.
    """
    root = tk.Tk()
    try:
        exp, rec = drive(root, cls, params_method)
        check(f"{label}: the output was actually turned on",
              "output_on" in rec.calls)
        offenders = [c for c in rec.while_energised()
                     if c == "set_source_function"]
        check(f"{label}: the source function never changes while energised",
              not offenders, f"{len(offenders)} times")
    finally:
        root.destroy()
