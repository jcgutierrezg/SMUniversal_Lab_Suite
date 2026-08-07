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
from devices.temperature_control import TemperatureController


class Experiment:
    # ---- declared by each subclass ----
    NAME = "Unnamed experiment"

    # role key -> human description, shown in the connection panel.
    # A single-SMU experiment declares one; the dual-SMU IV setup will
    # declare two and get a two-row connection panel with no extra work.
    ROLES = {}

    # ordered list of build_*_panel(experiment, parent) callables.
    PANELS = []

    def __init__(self, app):
        """`app` is the LabApp shell. The experiment reaches back through
        it for instruments, logging, and file paths."""
        self.app = app

        # The optional hot/cold stage. Constructed for every experiment
        # because constructing it costs nothing - no port is opened until
        # someone presses Connect on the temperature panel. Experiments
        # that don't include that panel simply never touch it.
        #
        # It lives here rather than in each experiment so that adding the
        # panel to a new experiment is one line in PANELS, with no way to
        # forget the matching shutdown - see shutdown_devices().
        self.temp_ctrl = TemperatureController()

        # Completed runs waiting to be saved. Nothing reaches disk until
        # the operator presses Save, so bad runs can be deleted first -
        # see core/run_store.py for why, and for what that costs.
        self.run_store = RunStore()

    # ---- convenience passthroughs, so measurement code reads cleanly ----
    @property
    def log(self):
        """Write a timestamped line to the console."""
        return self.app.log

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

    def on_close(self):
        """Called before the window closes. Override to stop timers or
        put hardware in a safe state."""

    # Used to name saved files and title their header block. Override.
    CSV_SLUG = "run"
    CSV_TITLE = "Lab measurement suite"

    def current_sample_name(self):
        """Sample name as it gets used in filenames - trimmed, spaces
        replaced. One definition so the table, the store and the saved
        file can never disagree about which sample a run belongs to."""
        return (self.sample_name_var.get() or "sample").strip().replace(" ", "_")

    def calculated_fields(self):
        """Derived results to embed in the saved CSV header. Override.

        Returns an ordered mapping; empty by default so an experiment
        that computes nothing still saves its raw data.
        """
        return {}

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
        written = []
        try:
            for sample in self.run_store.samples():
                runs = self.run_store.runs_for(sample)
                calculated = self.calculated_fields() if sample == current else None
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
        """Put the side-channel devices in a safe state and release them.

        Called by the app *after* on_close(), and deliberately not part
        of it: a subclass that overrides on_close() and forgets to call
        super() would otherwise leave a heater running. Making it a
        separate hook the app calls itself removes that possibility.

        The PID is switched off for the same reason disconnect_role()
        calls safe_output_off() on an SMU - hardware left driving with
        nothing watching it is the worse failure. Remove the pid_off()
        call if you ever want the stage held at temperature after the
        window closes.
        """
        # Stop the temperature readout refreshing before the widgets go
        # away, or the last scheduled tick fires into a dead interpreter.
        poll_id = getattr(self, "_temp_poll_id", None)
        if poll_id is not None:
            try:
                self.app.root.after_cancel(poll_id)
            except Exception:
                pass
            self._temp_poll_id = None

        try:
            if self.temp_ctrl.is_connected():
                self.temp_ctrl.pid_off()
        except Exception:
            pass
        try:
            self.temp_ctrl.close()
        except Exception:
            pass
