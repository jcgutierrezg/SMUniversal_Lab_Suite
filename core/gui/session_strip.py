"""
The session strip - what is true of the whole window, not of one tab.

Before this existed, four panel files each built their own "Next #" and
"Save path" rows and assigned the resulting variables onto the *app*::

    exp.app.measnum_var = tk.IntVar(...)      # in a panel

That worked while a window held one experiment and stopped working the
moment it held two: the second tab's panel silently rebound the app
attribute, `take_meas_number()` then updated only the second tab's box,
and the first tab's counter froze at whatever it last showed. No error,
no wrong number - just a readout that quietly stopped being true. Same
shape as the `thickness_m` / `thickness_um` mismatch that once shipped:
two names for one thing, and nothing that could notice they disagreed.

So the variables are created once, in `LabApp.__init__`, and this builds
the widgets that show them.

What belongs here
-----------------
State that is a property of the *session* rather than of a measurement:

    sample name     one mounted film, measured by Van der Pauw and then
                    by Hall, is one sample - `core/identity.py` has said
                    always has been, and now the box says so too
    thickness       the same physical number in both calculations
    next #          one counter per window
    save path       one folder per session

Which of the first two appear is decided by the hosted experiments'
`SESSION_FIELDS`, because an experiment that carries its own thickness
in a geometry panel (the Ossila 4PP) must not be given a second box
claiming to hold the same quantity. "Next #" and the save path are
unconditional: every experiment has always used both.

Why one shared variable rather than two kept in step
----------------------------------------------------
`Experiment.sample_name_var` is a property returning the app's variable,
so both tabs read the *same object*. Two variables synchronised by a
trace would work until the ordering went wrong once - and the failure
would be a Hall calculation carrying a Van der Pauw thickness, which
reads exactly like a correct one.
"""
from tkinter import ttk


def build_session_strip(app, parent, fields=()):
    """Build the strip above the tabs.

    `fields` is the union of the hosted experiments' `SESSION_FIELDS`;
    recognised entries are "sample" and "thickness".

    Sets app.session_strip, and app.sample_entry / app.thickness_entry
    where those fields were asked for.
    """
    # A bare frame with a rule under it rather than a LabelFrame: the
    # border and title cost about thirty vertical pixels, and vertical
    # pixels are the scarce resource this window budgets for.
    holder = ttk.Frame(parent)
    holder.grid(row=0, column=0, sticky="ew")
    holder.grid_columnconfigure(0, weight=1)

    frame = ttk.Frame(holder)
    frame.grid(row=0, column=0, sticky="ew")
    ttk.Separator(holder, orient="horizontal").grid(
        row=1, column=0, sticky="ew", pady=(6, 0))
    app.session_strip = holder

    column = 0

    def cell(widget, pad=(0, 16)):
        nonlocal column
        widget.grid(row=0, column=column, sticky="w", padx=pad)
        column += 1

    if "sample" in fields:
        cell(ttk.Label(frame, text="Sample name:"), (0, 6))
        app.sample_entry = ttk.Entry(frame, textvariable=app.sample_name_var,
                                     width=18)
        cell(app.sample_entry, (0, 6))
        # A reminder, not a mechanism, and the distinction is honest.
        #
        # The name in this box is what `core/identity.py` mints a sample
        # identifier from, so two physically different coupons typed
        # under one name are *one sample* as far as every check in the
        # suite is concerned - including the mixed-sample refusal, which
        # then has nothing to refuse. Van der Pauw's sheet resistance
        # would carry over onto the wrong coupon and every number would
        # look right.
        #
        # `SampleRegistry.new()` exists to mint a distinct identifier
        # under an unchanged label, and nothing calls it. A few words
        # are the proportionate answer, on the grounds that
        # bench labelling is disciplined; if that stops being true, the
        # fix is a "New sample" button here rather than more wording.
        #
        # On the same row on purpose. As its own row it cost 20 vertical
        # pixels, which was more than the CI runner's font metrics had
        # left in the layout budget - see `tests/test_layout.py`.
        cell(ttk.Label(frame, text="(one per mounted sample)",
                       foreground="#777777"))

    if "thickness" in fields:
        cell(ttk.Label(frame, text="Thickness (\u00b5m):"), (0, 6))
        app.thickness_entry = ttk.Entry(
            frame, textvariable=app.thickness_entry_var, width=10)
        cell(app.thickness_entry)

    cell(ttk.Label(frame, text="Next #:"), (0, 6))
    app.measnum_entry = ttk.Entry(frame, textvariable=app.measnum_var,
                                  width=5, state="readonly")
    cell(app.measnum_entry)

    cell(ttk.Button(frame, text="Save path...", width=11,
                    command=app.select_path), (0, 6))
    app.path_entry = ttk.Entry(frame, textvariable=app.path_display_var,
                               width=30, state="readonly")
    app.path_entry.grid(row=0, column=column, sticky="ew")
    frame.grid_columnconfigure(column, weight=1)

    return frame


def bound_variable(widget):
    """The name of the Tk variable `widget` actually displays.

    The test suite needs this, and the reason is worth
    keeping next to the code. Asserting that two experiments *and* the
    app agree on which variable object is the sample name does not catch
    the failure it was written for: a panel doing
    `exp.app.sample_name_var = tk.StringVar(...)` rebinds the attribute,
    all three go on agreeing, and the only thing left pointing at the
    original is the widget the operator is typing into. The box then
    does nothing and every reader sees the default forever.

    So the question a test has to ask is not "do the readers agree" but
    "is the box the operator types in wired to the variable the readers
    read". This answers it.
    """
    try:
        return str(widget.cget("textvariable"))
    except Exception:
        return ""
