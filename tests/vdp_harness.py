"""
Driving a Van der Pauw run from a test, on the main thread.

Shared rather than copied because three files need it - `test_saving`,
`test_hall_handoff` and `test_demo_mode` - and a harness that drifts
between them is a harness that stops testing the same thing. Same
reasoning as `stage_blocking_smu.py`; imported by bare name, the way
pytest puts the tests directory on the path.
"""


def run_vdp(exp, root, position, points=5, level="100 \u00b5A", delay_ms="0"):
    """Drive one Van der Pauw run to completion on the main thread.

    Wave 5a-i: `_do_run` takes a frozen parameter snapshot rather than
    five positional arguments, and opens its own `begin_run()` block.
    This harness still calls it directly rather than going through
    `run_pressed()`, so it does not exercise the worker thread or the
    position-confirmation dialog - that is fine for what these files are
    about, and the threaded path is covered in `test_vdp_lifecycle.py`.

    The drain matters: work handed back with `app.ui()` is queued and
    pumped by a timer the main thread owns, so a committed row is still
    sitting in the queue when the assertions run unless it is drained
    explicitly.
    """
    exp.pos_var.set(position)
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
