"""
The experiment contract.

An experiment owns three things:
  ROLES   - which instruments it needs, and what it calls them
  PANELS  - which GUI panels it wants, in order
  run()   - the measurement sequence itself

Everything else (connecting, logging, saving, threading, limit checks)
belongs to the app shell in core/base_app.py and is inherited free.

Adding a panel later is a two-step job: write the builder function, add
it to PANELS. Adding a whole experiment is a folder in experiments/ plus
a line in main.py.

On variants: for measurements that grew over time (the IV scripts being
the case in point), prefer one experiment whose optional features are
extra entries in PANELS over separate subclasses. Subclass only when the
*sequence* genuinely forks - and then override a single named step, not
run() as a whole.
"""
import os
from tkinter import ttk

from tkinter import messagebox

from core.run_store import RunStore, build_sample_csv
from core.run_control import DEFAULT_POLICY, RunController


class Experiment:
    # ---- declared by each subclass ----
    NAME = "Unnamed experiment"

    # Short label for the notebook tab. Falls back to NAME, which is
    # right for a one-tab window and too long once there are two.
    TAB_NAME = None

    # role key -> human description, shown in the connection panel.
    # A single-SMU experiment declares one; the dual-SMU IV setup will
    # declare two and get a two-row connection panel with no extra work.
    ROLES = {}

    # ordered list of build_*_panel(experiment, parent) callables.
    PANELS = []

    # ---- what the app shell provides on this experiment's behalf ----
    # Wave 5b moved two things out of the experiments and up to the
    # window, and both are declarations rather than code so that adding
    # or removing one is a single visible line.

    # Does this experiment sit on the hot/cold stage? The app builds one
    # stage panel per window if any hosted experiment says yes, and owns
    # the single `TemperatureController` behind it - two tabs each
    # holding their own would be two objects opening one COM port.
    USES_TEMP_STAGE = False

    # Which session-strip fields this experiment reads. Recognised:
    # "sample" and "thickness". An experiment listing a field must not
    # build its own widget for it; one quantity, one box, one variable.
    # The Ossila 4PP lists neither, because its thickness is part of a
    # geometry panel that means something slightly different by it.
    SESSION_FIELDS = ()

    # Quantities this experiment can hand to another tab in the same
    # window (Wave 5c). Van der Pauw declares "sheet_resistance"; Hall
    # asks the window for whoever provides it.
    #
    # A capability rather than a class reference, and the difference is
    # the point. `experiment_of(VanDerPauwExperiment)` would make Hall
    # import Van der Pauw - you could not open a Hall tab without
    # dragging the other module in, and the two would stop being two
    # experiments that share a window and become one fused unit. Asking
    # for a *quantity* keeps the dependency pointing at the calculation
    # layer, which both already depend on. The 4PP also computes a sheet
    # resistance; the day it shares a window with Hall, it declares the
    # same string and nothing else changes.
    PROVIDES = ()

    # What counts as a completed run. Overridden per experiment where
    # its own definition genuinely differs - a measurement that holds
    # the output on between runs needs
    # `CompletionPolicy(require_shutdown_confirmed=False)`, and it should
    # say why where it sets it. Everything else uses the shared one, so
    # no experiment quietly invents its own idea of success.
    COMPLETION_POLICY = DEFAULT_POLICY

    def __init__(self, app):
        """`app` is the LabApp shell. The experiment reaches back through
        it for instruments, logging, and file paths."""
        self.app = app

        # Completed runs waiting to be saved. Nothing reaches disk until
        # the operator presses Save, so bad runs can be deleted first -
        # see core/run_store.py for why, and for what that costs.
        self.run_store = RunStore()

        # The run lifecycle: one state machine, one run ID and one
        # cancellation token per run, and the atomic commit gate that
        # decides whether a run's readings are allowed into run_store at
        # all. See core/run_control.py.
        #
        # Wave 1 builds and tests this; the four existing experiments
        # still use their own `measuring` flags and are migrated onto it
        # one at a time in Wave 2, starting with the simplest. That is
        # deliberate - the review asks for the infrastructure to exist
        # and be provable before any scientific behaviour changes, so a
        # bad lifecycle design is found in a unit test rather than in
        # four half-converted experiments.
        self.run_controller = RunController(name=self.CSV_SLUG,
                                            policy=self.COMPLETION_POLICY,
                                            log=app.log)

    # ---- convenience passthroughs, so measurement code reads cleanly ----
    @property
    def log(self):
        """Write a timestamped line to the console."""
        return self.app.log

    @property
    def tab_label(self):
        """What the notebook tab says. `TAB_NAME` when a subclass set
        one, otherwise the full name - which is right for a one-tab
        window and only too long once there are two."""
        return self.TAB_NAME or self.NAME

    @property
    def temp_ctrl(self):
        """The window's temperature stage controller (Wave 5b).

        One per window, not one per experiment. Kept as an attribute
        here so that `self.temp_ctrl.status()` in a measurement reads
        the same as it did before the move.
        """
        return self.app.temp_ctrl

    @property
    def sample_name_var(self):
        """The session strip's sample-name variable (Wave 5b).

        Read-only on purpose. A panel that tries to assign its own
        variable over this gets an `AttributeError` at build time, which
        is exactly the failure worth having loudly: the alternative is a
        second box holding a second copy of the sample name, agreeing
        with the first until one day it doesn't.
        """
        return self.app.sample_name_var

    @property
    def thickness_entry_var(self):
        """The session strip's thickness variable, in micrometres.

        Read-only for the same reason as `sample_name_var`. One mounted
        film has one thickness; a Hall carrier density computed from a
        Van der Pauw thickness that has since been retyped is wrong in a
        way that looks entirely reasonable on screen.
        """
        return self.app.thickness_entry_var

    def instrument(self, role="source"):
        """Get the driver connected in `role`. Raises if nothing is
        connected there, which is the common cause of a run failing
        early - better a clear message than an AttributeError."""
        return self.app.require_instrument(role)

    # ---- hooks ----
    def build_panels(self, parent):
        """Create the three layout columns, then let the panels fill them.

        Monitors are wide and short; stacking every panel in one tall
        column fought that. The panels are therefore spread across three
        columns which read left to right in the order the work actually
        happens:

            col_left    what the sample is doing   diagram, position,
                                                   temperature stage
            col_mid     what to run                setup, Run/OFF
            col_right   what came out              results, calculation

        A panel chooses its column by packing into the matching
        attribute - there is no registry to keep in step, and the choice
        is visible on the first line of each panel file. Within a column,
        PANELS order is top-to-bottom order.

        The containers are made here rather than by the first panel so
        the PANELS list stays order-independent: reordering or removing a
        panel cannot break the ones after it.
        """
        columns = ttk.Frame(parent)
        columns.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self.col_left = ttk.Frame(columns)
        self.col_mid = ttk.Frame(columns)
        self.col_right = ttk.Frame(columns)

        for index, column in enumerate((self.col_left, self.col_mid, self.col_right)):
            column.grid(row=0, column=index, sticky="nsew",
                        padx=(0 if index == 0 else 12, 0))

        # Spare width goes to the results column - the table and the
        # calculation grid are the only things that benefit from it. The
        # other two are fixed-content forms that would only gain
        # whitespace.
        columns.grid_columnconfigure(2, weight=1)
        columns.grid_rowconfigure(0, weight=1)

        for builder in self.PANELS:
            builder(self, columns)

        self.on_panels_built()

    def on_panels_built(self):
        """Called once every panel exists. Override this for anything an
        experiment needs to do after its widgets are up - painting the
        corner diagram for the starting position, say.

        It exists so no experiment has to override build_panels() itself.
        An override that forgot to call super() would silently get no
        layout columns at all, and every panel would fail looking for
        them; a hook can't go wrong that way.
        """

    def on_connected(self, role, driver):
        """Called after an instrument connects. The default does nothing;
        override to push initial setup, or to refresh dropdowns from the
        driver's declared limits."""

    def run(self):
        """The measurement itself. Called on a background thread by the
        app, so it must not touch Tk widgets directly - use self.log()
        and self.app.ui() to get back to the main thread."""
        raise NotImplementedError

    # ---- run lifecycle ----
    def begin_run(self, parameters=None, metadata=None):
        """Start a run, or refuse with a message aimed at the operator.

        The shape a migrated experiment uses::

            with self.begin_run(parameters=snapshot) as run:
                run.enter(self.app.claim_instrument("source", run.run_id))
                run.start()
                ...
                run.confirm_shutdown(smu, log=self.log)
                run.commit(built_run, lambda r: self.app.ui(
                    self._record_run, row_values, r))

        Everything after the block - discarding provisional readings,
        releasing the instrument, recording a terminal status, returning
        to idle - happens whether the run succeeded, was cancelled, or
        threw.
        """
        self._log_interlock_note()
        return self.run_controller.begin(parameters=parameters,
                                         metadata=metadata)

    #: Set once a run has told the operator about the interlock, so a
    #: session of twenty runs produces one line rather than twenty. A
    #: warning repeated every run is a warning people learn to skip.
    _interlock_told = False

    def _log_interlock_note(self):
        """Say once per session that this instrument has an interlock.

        Printed at run start rather than at connect because that is when
        it could matter: the operator is about to source, and if the
        line is not held high a high-voltage run will simply refuse
        rather than fail in a way that names a cause.

        Wrapped in a try/except on purpose. This is a console
        convenience, and a convenience must never be able to stop a
        measurement starting.
        """
        if self._interlock_told:
            return
        try:
            driver = getattr(self.app, "instruments", {}).get("source")
            if driver is None:
                return
            note = driver.interlock_note()
            if not note:
                return
            self.log(f"{driver.DISPLAY_NAME}: {note}")
            self._interlock_told = True
        except Exception:
            pass

    def cancel_run(self, reason="operator pressed OFF"):
        """Mark the run in flight as cancelled. True if there was one.

        Cancellation and the output-off command are separate steps on
        purpose. This one is instant and cannot fail; sending the
        output-off talks to an instrument and can. Doing the flag first
        is what stops the race where the worker turns the output back on
        between the operator's press and the command arriving.
        """
        return self.run_controller.request_cancel(reason)

    def run_in_progress(self):
        """True while a run exists, including during its cleanup.

        This, not "is the worker thread alive", is what a Run button
        should be greyed out by: an instrument whose ownership has not
        been released is not free yet.
        """
        return self.run_controller.is_busy

    def refuse_if_sibling_busy(self):
        """True (and says so) if another tab is measuring. Wave 5b.

        The per-experiment interlock above answers "am *I* busy". This
        answers "is anybody in this window busy", which is the question
        that appeared the moment two measurements shared one SMU.

        It is a courtesy, not the guarantee. The guarantee is ownership:
        both tabs claim the same instrument key, and the second claim is
        refused with `InstrumentBusy` whatever the buttons look like.
        What this adds is *when* the refusal arrives - before the
        operator has been asked to go and set a switch box for a run
        that was never going to start.
        """
        other = self.app.busy_experiment(exclude=self)
        if other is None:
            return False
        messagebox.showwarning(
            "Measurement in progress",
            f"'{other.NAME}' is running on the same instrument.\n\n"
            f"Wait for it to finish, or press Stop on that tab.")
        return True

    def on_close(self):
        """Called before the window closes. Override to stop timers or
        put hardware in a safe state."""

    # Used to name saved files and title their header block. Override.
    CSV_SLUG = "run"
    CSV_TITLE = "Lab measurement suite"

    def current_sample_name(self):
        """Sample name as it gets used in filenames - trimmed, spaces
        replaced. One definition so the table, the store and the saved
        file can never disagree about which sample a run belongs to.

        Superseded by `current_sample_ref()` for anything that needs to
        say *which* sample rather than what it is called. Kept because
        Van der Pauw, Hall and the IV sweep still call it and Wave 3
        touches only 4PP; Wave 5 retires it.
        """
        return (self.sample_name_var.get() or "sample").strip().replace(" ", "_")

    def current_sample_ref(self):
        """The `SampleRef` for whatever is named in the sample box.

        **Main thread only.** It reads a Tk variable, which is exactly
        the thing a worker must not do - call it while building the
        parameter snapshot, at the Run press, and let the worker use the
        ref that comes back.

        Minting is lazy: a label that has been used before returns the
        same sample, so measuring one film repeatedly needs no ceremony.
        Two physically different samples that happen to share a label
        need `self.app.samples.new(label)` instead, which is what a
        "New sample" control will call when Wave 5 adds one.
        """
        from core.validation import label as clean_label
        text = clean_label(self.sample_name_var.get(), "Sample name",
                           default="sample")
        return self.app.samples.ref(text)

    def provide(self, name):
        """Hand `name` to another tab as a `ProvidedValue` (Wave 5c).

        Raises `CalculationRefused` when the quantity exists in
        principle but is not usable right now - not calculated yet, or
        stale. That is not an error path bolted on afterwards: a stale
        result cannot reach this experiment's own CSV, and it must not
        reach another experiment's arithmetic through a side door
        either.

        The message is written for a dialog, because that is where it
        ends up.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not provide {name!r}")

    def calculated_fields(self):
        """Derived results to embed in the saved CSV header. Override.

        Returns an ordered mapping; empty by default so an experiment
        that computes nothing still saves its raw data.
        """
        return {}

    def calculated_sample_id(self):
        """Sample identifier the calculated results belong to, or None.

        None means "this experiment cannot say", and `save_runs()` falls
        back to matching on the sample name - which is what Van der
        Pauw, Hall and the IV sweep still do. 4PP overrides it with the
        identifier off its `DerivedResult`, so its results follow the
        sample rather than the text box (§17). Wave 5 does the same for
        the other two ported experiments.
        """
        return None

    def ticked_items(self):
        """Treeview item ids currently ticked."""
        return [i for i in self.tree.get_children()
                if (self.tree.item(i, "text") or "") == "☑"]

    def save_runs(self):
        """Write every run in the table to CSV, one file per sample.

        Grouping by sample name is what makes the file useful later: a
        sample's runs belong together, and splitting them across files
        keyed by measurement number only makes them harder to plot.

        The calculated results are attached only to the sample currently
        named in the setup panel. The calculation panel holds one set of
        numbers, and they describe that sample - copying them onto every
        sample in the table would be inventing results for samples that
        were never calculated.
        """
        if not len(self.run_store):
            messagebox.showinfo("Nothing to save",
                                "There are no runs in the results table.")
            return

        current = self.current_sample_name()
        calc_sample_id = self.calculated_sample_id()
        written = []
        try:
            for sample in self.run_store.samples():
                runs = self.run_store.runs_for(sample)
                # Wave 4, §17: bind the derived result to the sample that
                # produced it rather than to whatever is in the name box.
                # The old rule compared the box against the group name,
                # so renaming the box between calculating and saving
                # filed the result under the wrong sample - or dropped it
                # entirely - and nothing said so.
                #
                # Only runs that actually carry a `sample_id` can be
                # held to this, and the test is made per group rather
                # than per experiment. A store can hold both kinds at
                # once - runs recorded before an experiment was wired
                # up, or rows put into the table directly - and matching
                # on identity against a group that has none would drop
                # the calculation from the file with nothing said, which
                # is the very failure this rule exists to prevent.
                #
                # The IV sweep still records no `sample_id`, so it takes
                # the name path throughout.
                identified = [r for r in runs if r.metadata.get("sample_id")]
                if calc_sample_id is not None and identified:
                    belongs = any(r.metadata["sample_id"] == calc_sample_id
                                  for r in identified)
                else:
                    belongs = (sample == current)
                calculated = self.calculated_fields() if belongs else None
                if calculated is None and len(self.run_store.samples()) > 1:
                    self.log(f"'{sample}': raw data only - the calculation "
                             f"panel currently refers to '{current}'")
                text = build_sample_csv(sample, runs, self.CSV_TITLE, calculated)
                path = self.app.unique_filename(f"{sample}_{self.CSV_SLUG}.csv")
                self.app.write_atomic(path, text)
                written.append(path)
                self.log(f"Saved {len(runs)} run(s) for '{sample}' to {path}")
        except Exception as e:
            self.log("Save failed:", e)
            messagebox.showerror("Save failed", str(e))
            return

        self.run_store.mark_saved()
        messagebox.showinfo(
            "Saved",
            f"{len(self.run_store)} run(s) written to "
            f"{len(written)} file(s):\n\n"
            + "\n".join(os.path.basename(p) for p in written))

    def delete_ticked(self):
        """Remove the ticked rows and their raw data.

        This is the point of not auto-saving: a run spoiled by a
        misaligned sample or a poor contact is deleted here and never
        reaches the disk at all.
        """
        ticked = self.ticked_items()
        if not ticked:
            messagebox.showinfo(
                "Nothing ticked",
                "Tick the runs you want to discard, then press Delete.")
            return

        if not messagebox.askyesno(
                "Delete runs",
                f"Discard {len(ticked)} run(s) and their raw readings?"):
            return

        self.run_store.remove(ticked)
        for item in ticked:
            self.tree.delete(item)
        self.log(f"Deleted {len(ticked)} run(s)")

    def clear_output(self):
        """Empty the results table completely."""
        if len(self.run_store) and self.run_store.has_unsaved:
            if not messagebox.askyesno(
                    "Clear results",
                    f"{len(self.run_store)} run(s) have not been saved.\n\n"
                    "Clear the table and discard them?"):
                return
        for item in list(self.tree.get_children()):
            self.tree.delete(item)
        self.run_store.clear()
        self.log("Results table cleared")

    def has_unsaved_runs(self):
        """True when the results table holds runs that aren't on disk.

        The app asks before closing on the strength of this. It is the
        safety net for not auto-saving: without it, closing the window
        after a long measurement would discard it silently.
        """
        return self.run_store.has_unsaved

    def shutdown_devices(self):
        """Put this experiment's *own* side-channel devices away.

        Empty by default, and the hot/cold stage is no longer here.

        Until Wave 5b every experiment closed its own
        `TemperatureController` from this hook. With one controller per
        window that becomes wrong in a way worth naming: the first tab
        torn down would close the port out from under the second, and
        the second would then close it again. The stage is shut down
        once, by `LabApp.shutdown_devices()`.

        The hook stays because the reason it exists still holds - the
        app calls it separately from `on_close()`, so a subclass that
        overrides `on_close()` and forgets `super()` cannot leave
        hardware driving. An experiment that acquires a device of its
        own puts the shutdown here.
        """
