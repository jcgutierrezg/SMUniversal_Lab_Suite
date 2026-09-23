"""
Run, the two ways to end a run early, the output lamp and progress.

Why this panel has three buttons when every other one has two
------------------------------------------------------------
Everywhere else in this suite, Stop means *cancel*: the run's data is
discarded whatever its progress. That rule is deliberate and it is
right for a sweep - half an IV curve is not a shorter IV curve, it is a
curve missing the part that would have told you something.

A fixed-source run is different in kind. Its readings are independent
samples of a sample's behaviour over time, so twenty minutes of a
sixty-minute run is twenty real minutes of data. Throwing that away
because the operator saw what they needed early would be discarding a
result, not a fragment.

So the two operations are separated and each gets its own verb:

    Finish and save     stop sampling now, put the output away, keep
                        what has been collected, commit it
    Stop and discard    the house Stop, unchanged - cancel, discard,
                        de-energise

Naming, not just behaviour, is the load-bearing part. "Stop" keeps the
same meaning it has on every other tab, so an operator moving between
tabs cannot lose a run by pressing the button they have pressed a
hundred times. The new operation is a new word.

Neither button talks to the instrument
--------------------------------------
Both set a flag and return. The worker notices at its next loop
boundary and de-energises **on the thread that owns the session**.

That is the whole reason the OFF buttons were removed from the other
tabs (decision W6-2): `off_pressed()` used to call
`safe_output_off()` from a second thread while the worker was
mid-`measure()` on the same VISA session - two threads, one session,
interleaved SCPI. "Finish and save" is a new control, but it is not a
new race: it is a flag, exactly as Stop is.

The cost is latency. The worker notices at the top of its next sample,
so a run with a 10 s interval can take up to one reading plus the
remainder of a wait to stop. The wait itself is cancellable, so in
practice it is one reading; `tests/test_fixed_source_lifecycle.py`
measures that bound rather than asserting it.
"""
from smuniversal_lab_suite.core.gui.run_controls import build_run_controls


def build_action_panel(exp, parent):
    """The shared run controls, with Finish between Run and Stop.

    Sets `exp.finish_btn` as well as everything `build_run_controls`
    sets.
    """
    return build_run_controls(
        exp, parent, stop_text="Stop and discard",
        extra=[("finish_btn", "Finish and save", exp.finish_pressed,
                "End the run now and keep what has been collected, as a "
                "run in the table. Unlike Stop and discard nothing is "
                "thrown away: twenty minutes of an hour's hold is twenty "
                "real minutes. The output is put away first.")])
