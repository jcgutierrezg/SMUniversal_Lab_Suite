"""
Driving a Hall run from a test, on the main thread.

The counterpart to `vdp_harness.py`, and shared for the same reason: a
harness copied between files is a harness that drifts, and then the
files stop testing the same thing.

This calls `_do_run()` directly rather than going through
`run_pressed()`, so it exercises neither the worker thread nor the
setup-confirmation dialog. That is the right trade for tests about
calculation, saving and grouping; the threaded path is
`test_hall_lifecycle.py`'s job. See `tests/README.md` for why the two
shapes are kept apart.
"""


def run_hall(exp, root, position, field_sign="+", points=3,
             level="100 \u00b5A", delay_ms="0"):
    """Drive one Hall run to completion and return its parameters.

    The drain matters: work handed back with `app.ui()` is queued and
    pumped by a timer the main thread owns, so a committed row is still
    in the queue when the assertions run unless it is drained.
    """
    exp.pos_var.set(position)
    exp.field_sign_var.set(field_sign)
    exp.points_var.set(str(points))
    exp.level_var.set(level)
    exp.delay_ms_var.set(delay_ms)
    params = exp._run_params()
    try:
        exp._do_run(params)
    finally:
        exp.app.drain_ui_now()
        for _ in range(60):
            root.update()
        exp.app.drain_ui_now()
    return params
