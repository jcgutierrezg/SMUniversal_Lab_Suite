"""
The application shell.

Owns everything that is the same for every experiment: instrument
connections, the console, file saving, background threading, and the
limit gate that runs before any measurement. Experiments plug into it
and supply only their own panels and sequencing.

Dependency direction is one-way and worth guarding:

    experiments/  ->  drivers/  ->  core/transports/

Nothing in core/ may import from experiments/, and no driver may import
an experiment. If that ever feels necessary, something is in the wrong
layer.
"""
import datetime
import os
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from enum import Enum
from tkinter import ttk, messagebox, filedialog

from drivers import registry as default_driver_registry
from core.event_log import EventLog

#: Distinguishes "not supplied" from an explicit `event_log=None`, which
#: means "record nothing". A plain `None` default could not tell them
#: apart, and a test that wanted logging off would silently get a real
#: log writing into the developer's state directory.
_UNSET = object()
from core.identity import SampleRegistry
from core.limits import LimitError
from core.ownership import (InstrumentBlocked, InstrumentBusy,
                            default_ownership, key_for_transport)
from core.run_control import RunRejected
from core.run_store import build_sample_summary
from core.gui.connection_panel import build_connection_panel
from core.gui.console_panel import build_console_panel
from core.gui.session_strip import build_session_strip
from core.gui.temp_panel import build_temp_panel
from core.run_control import ShutdownStatus
from devices.temperature_control import (StageShutdownReport,
                                         TemperatureController)


#: How often the main thread drains work queued by measurement threads.
#: Fast enough that a progress line looks live, slow enough to cost
#: nothing when idle.
UI_PUMP_MS = 10

#: How long the close path waits for measurement workers to finish
#: cleaning up before it goes on without them.
#:
#: Bounded on purpose, and the bound is the whole design. Waiting
#: forever turns a wedged worker into a window that cannot be closed,
#: which an operator answers by killing the process - and that skips
#: every de-energise this path exists to perform. Five seconds is
#: generous against ordinary cleanup (an output-off and an error-queue
#: read) and short enough that nobody reaches for Task Manager.
#:
#: Expiry is not swallowed. It is logged and put in front of the
#: operator, because the runs that outlast it are exactly the ones whose
#: instrument state nobody can vouch for.
CLEANUP_TIMEOUT_S = 5.0

#: How often that wait re-checks, and drains the UI queue while it does.
#: Draining is not politeness: a worker's cleanup posts through `ui()`,
#: so a main thread that blocked without draining would be waiting on
#: work it was itself holding up - see docs/rules/08-ui-is-a-queue.md.
CLEANUP_POLL_S = 0.02


class ClosePhase(str, Enum):
    """The steps of closing the window, in the order they happen.

    Named and recorded so that shutdown is something a test - and a
    console log - can observe, rather than a sequence of side effects
    that either all happened or silently did not.
    """

    REFUSED_TO_CLOSE = "refused-to-close"
    REFUSED_NEW_RUNS = "refused-new-runs"
    CANCELLED_RUNS = "cancelled-runs"
    WAITED_FOR_IDLE = "waited-for-idle"
    DE_ENERGISED = "de-energised"
    DISCONNECTED = "disconnected"
    DESTROYED = "destroyed"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class UnsavedState:
    """How much unsaved work the window holds, and what it could not read.

    Three-valued rather than a count, because a count has no way to say
    "I do not know" and the difference matters: unsaved runs live only
    in memory, so closing is the one routine action that can throw away
    a morning's measuring.

    `unknown` carries one line per experiment whose store could not be
    read. A non-empty `unknown` means the number in `count` is a floor,
    not a total, and the close path treats it as a refusal rather than
    as a zero.
    """

    count: int = 0
    unknown: tuple = ()

    @property
    def is_known(self):
        return not self.unknown


class LabApp:
    """Hosts one or more experiments in one window.

    Construct with an experiment class, or a list of them - not with
    instances; the app builds them once the window exists.

        LabApp(root, VanDerPauwExperiment)                  # one tab
        LabApp(root, [VanDerPauwExperiment, HallExperiment]) # two tabs

    Wave 5b made the second form possible, after the operator note that a
    Van der Pauw run *always* immediately precedes a Hall measurement on
    the same mounted sample with the same contacts. That is one session,
    not two programs.

    What "one session" means concretely
    -----------------------------------
    Everything the two measurements share is owned here, once, and the
    tabs are two views onto it:

        instrument connections   already app-level
        sample identity          already app-level (`samples`)
        sample name, thickness   the session strip (Wave 5b)
        the temperature stage    `temp_ctrl` (Wave 5b)
        measurement number,
        save folder, console     app-level

    What stays per experiment is what genuinely differs: the results
    table's columns, the arithmetic, the saved CSV, and the run
    identifier - which carries the experiment's name, so a file can still
    say which measurement produced it.

    The temperature stage is the one that had to move rather than merely
    ought to. Both experiments used to build `build_temp_panel` and hold
    their own `TemperatureController`; two tabs would have been two
    controllers opening one COM port, which fails at the bench and not in
    the suite.

    Two collaborators are handed in rather than imported:

    `registry`
        Which drivers exist. Importing it here was the last violation of
        the one-way dependency rule - the registry imports all seven
        driver modules, so `core` reaching for it made core depend on
        drivers. The default argument keeps `main.py` unchanged while
        letting a test hand over a registry holding one fake.

    `ownership`
        Who is allowed to command which instrument. Shared across every
        window in the process by default, because two experiment windows
        on one GPIB address are two Python objects and one instrument.
    """

    def __init__(self, root, experiment_cls, registry=None, ownership=None,
                 samples=None, title=None, event_log=_UNSET):
        self.root = root
        self.registry = registry or default_driver_registry
        self.ownership = ownership or default_ownership()
        # Who the samples are. Application-scoped rather than per
        # experiment, and injected for the same reason the registry and
        # the ownership manager are: a sample measured in Van der Pauw
        # and then in Hall is one sample, and Wave 5's carry-over of a
        # sheet resistance between the two is only provable if both
        # windows agree on what that sample is. A test can hand over its
        # own registry and get deterministic identifiers.
        self.samples = samples or SampleRegistry()

        # role key -> connected driver instance
        self.instruments = {}
        # One operational log per window (review §26). Injected for
        # tests; otherwise it finds the per-machine state directory
        # itself. `None` disables logging entirely, which is what the
        # unit tests of other subsystems want.
        self.event_log = (event_log if event_log is not _UNSET
                          else EventLog(log=self.log))
        # role key -> transport instance (kept so we can close them)
        self.transports = {}
        # role key -> ownership key for the physical connection behind it
        self.instrument_keys = {}

        self.storage_path = os.path.expanduser("~")
        self._fs_lock = threading.Lock()
        self.next_meas_number = 1

        # The save-collision pre-flight (Wave 5c-ii). Whether this
        # session's summary file for the current sample may overwrite an
        # existing one. Decided once, at the first run that finds files
        # already under the sample's name, and re-armed whenever the
        # sample name or the save folder changes - because either makes
        # the earlier answer meaningless. `None` means "not yet asked
        # for this (sample, folder)". See `summary_collision_decision`.
        #
        # `_summary_context` remembers the (sample, folder) the decision
        # was taken for, so a Tk write that does not change the name -
        # re-typing the same value, or a trace firing on focus - does
        # not wipe a decision that is still valid. Re-arming on every
        # keystroke would silently turn a chosen overwrite back into a
        # suffix by the time Save ran.
        self._summary_overwrite = False
        self._summary_decided_for = None
        self._summary_context = None

        # The optional hot/cold stage, owned here rather than by each
        # experiment. One window, one serial port, one controller - see
        # the class docstring. Constructing it costs nothing; no port is
        # opened until someone presses Connect on the stage panel.
        self.temp_ctrl = TemperatureController()
        self._temp_poll_id = None

        # Session state shared by every tab. Created before the
        # experiments so that a panel can bind to these variables and an
        # experiment's `on_panels_built()` can put a trace on them.
        self.sample_name_var = tk.StringVar(master=root, value="sample")
        # A new sample name makes any earlier collision decision
        # meaningless (Wave 5c-ii) - but only a *different* name does.
        # The trace fires on every write, including re-setting the box to
        # the value it already holds, so `note_sample_context_changed`
        # compares against the last (sample, folder) it acted on and does
        # nothing on a no-op. Re-arming on those would silently turn a
        # chosen overwrite back into a suffix before Save ran.
        self._summary_context = ("sample", self.storage_path)
        self.sample_name_var.trace_add(
            "write", lambda *_: self.note_sample_context_changed())
        self.thickness_entry_var = tk.StringVar(master=root, value="1")
        self.measnum_var = tk.IntVar(master=root, value=self.next_meas_number)
        self.path_display_var = tk.StringVar(master=root,
                                             value=self.storage_path)

        # Work handed back from measurement threads. Drained by the main
        # thread on a timer - see `ui()` for why it is a queue and not a
        # direct `after()` call.
        self._ui_queue = queue.Queue()
        self._ui_pump_id = None

        # Shutdown state. `_closing` is the gate that refuses new runs
        # once the close path has started - a run begun between the
        # cancellation sweep and the disconnect would be a worker
        # nothing is waiting for. `close_log` is what that path
        # recorded, so a test can assert on the sequence rather than on
        # its side effects.
        self._closing = False
        self.close_log = []

        classes = ([experiment_cls] if isinstance(experiment_cls, type)
                   else list(experiment_cls))
        if not classes:
            raise ValueError("LabApp needs at least one experiment class.")
        self.experiments = [cls(self) for cls in classes]
        self._active_index = 0
        self.notebook = None

        if title is None:
            title = (self.experiments[0].NAME if len(self.experiments) == 1
                     else " + ".join(e.tab_label for e in self.experiments))
        root.title(title)

        self._build_ui()
        self._watch_run_states()
        self._schedule_ui_pump()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- which experiment the operator is looking at ----
    @property
    def experiment(self):
        """The experiment on the visible tab.

        Kept as a singular attribute-shaped property so that every
        caller written before Wave 5b - the connection panel reading
        `ROLES`, and a good deal of the test suite - goes on working
        unchanged in a one-tab window, which is the only shape those
        callers ever see.
        """
        return self.experiments[self._active_index]

    def experiment_of(self, cls):
        """The hosted instance of `cls`, or None.

        How one tab finds another without reaching through the notebook.
        Wave 5c's in-memory handoff of a sheet resistance from Van der
        Pauw to Hall is the first caller.
        """
        for exp in self.experiments:
            if isinstance(exp, cls):
                return exp
        return None

    def provider_of(self, quantity, exclude=None):
        """The hosted experiment that can supply `quantity`, or None.

        Wave 5c's sheet-resistance handoff goes through here rather than
        through `experiment_of(VanDerPauwExperiment)`. Hall asks the
        window "who has a sheet resistance?" instead of naming Van der
        Pauw, so neither experiment module imports the other and the two
        stay separable - see `Experiment.PROVIDES`.

        `exclude` is the asking experiment. Nothing today provides what
        it also consumes, but an experiment answering its own question
        would be a loop that produced a result citing itself as its own
        upstream, and that is cheaper to prevent than to notice.
        """
        for exp in self.experiments:
            if exp is not exclude and quantity in exp.PROVIDES:
                return exp
        return None

    # ---- the run gate (Wave 5b) ----
    def busy_experiment(self, exclude=None):
        """The experiment holding a run right now, or None.

        The house rule above the per-experiment interlocks: the tabs
        share one SMU, so one measurement runs at a time in a window.

        Ownership already refuses the second run - both tabs reach for
        the same instrument key and the loser gets `InstrumentBusy`. This
        exists so the refusal arrives *before* the operator has confirmed
        a switch-box position and a claim has been attempted, and so the
        other tab's Run button is visibly out of action rather than
        merely disappointing.
        """
        for exp in self.experiments:
            if exp is not exclude and exp.run_in_progress():
                return exp
        return None

    def _watch_run_states(self):
        """Re-evaluate the run gate whenever any run changes state.

        Observers fire on whichever thread caused the change, which for
        a measurement is a worker - hence the bounce through `ui()`
        rather than touching a widget here.
        """
        for exp in self.experiments:
            exp.run_controller.observe(
                lambda _state, _run: self.ui(self._refresh_run_gate))

    def _refresh_run_gate(self):
        """Grey the Run button on every tab that is not the busy one.

        The busy experiment is left alone: it manages its own Run/Stop
        pair through `_enter_run_ui()` and `_end_run()`, and two
        authorities over one widget is how a button ends up permanently
        disabled after an unlucky ordering.
        """
        busy = self.busy_experiment()
        for exp in self.experiments:
            button = getattr(exp, "run_btn", None)
            if button is None or exp is busy:
                continue
            try:
                button.config(state="disabled" if busy else "normal")
            except Exception:
                pass

    # ---- UI construction ----
    def _build_ui(self):
        """Connection panel on top, then the shared session strip, then
        the stage rail beside the experiment tabs, console at the bottom.

            +-------------------------------------------+
            | Instruments                               |
            +-------------------------------------------+
            | Sample | Thickness | Next # | Save path    |
            +---------+---------------------------------+
            | Temp    | [ Van der Pauw | Hall ]          |
            | stage   |   the tab's three columns        |
            +---------+---------------------------------+
            | Console                                   |
            +-------------------------------------------+

        Tabs rather than one scrollable page. Stop must never scroll
        off-screen; `test_layout.py` reads `winfo_reqheight()`, which a
        scrolled canvas would make a tautology; and matplotlib canvases
        inside a scrolling Canvas eat wheel events. None of that is a
        one-way door - a scrolled layout later is the same work.
        """
        # Weights all the way down, so dragging the window bigger gives
        # the space to the panels rather than leaving a grey border.
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=8)
        main.grid(sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)      # the experiment's panels

        build_connection_panel(self, main)

        # Row 1 of `main` holds the strip *and* the work area, so the
        # console panel's hardcoded rows 2 and 3 stay where they were.
        body = ttk.Frame(main)
        body.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        # The strip is built only when a hosted experiment asks for one
        # of its fields. Vertical pixels are the scarcest thing in this
        # window - `test_layout.py` exists because of it - and a strip
        # showing nothing but a save path would spend 40 of them on the
        # two experiments that keep their own.
        fields = set()
        for exp in self.experiments:
            fields.update(exp.SESSION_FIELDS)
        if fields:
            build_session_strip(self, body, fields)

        work = ttk.Frame(body)
        work.grid(row=1, column=0, sticky="nsew",
                  pady=(6, 0) if fields else (0, 0))
        work.grid_rowconfigure(0, weight=1)

        # The stage is part of the sample's environment, so it sits
        # beside the tabs rather than inside one of them: switching from
        # Van der Pauw to Hall must not change what is holding the
        # sample at temperature.
        column = 0
        if any(exp.USES_TEMP_STAGE for exp in self.experiments):
            rail = ttk.Frame(work)
            rail.grid(row=0, column=0, sticky="ns", padx=(0, 10))
            build_temp_panel(self, rail)
            column = 1
        work.grid_columnconfigure(column, weight=1)

        if len(self.experiments) == 1:
            # No notebook for a single experiment. A tab strip with one
            # unclickable tab is 32 px of vertical budget spent on
            # nothing, and the four single-experiment windows have no
            # 32 px to spare - see `test_layout.py`.
            host = ttk.Frame(work)
            host.grid(row=0, column=column, sticky="nsew")
            self.experiments[0].build_panels(host)
        else:
            self.notebook = ttk.Notebook(work)
            self.notebook.grid(row=0, column=column, sticky="nsew")
            for exp in self.experiments:
                tab = ttk.Frame(self.notebook)
                self.notebook.add(tab, text=exp.tab_label)
                exp.build_panels(tab)
            self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        build_console_panel(self, main)

    def _on_tab_changed(self, _event=None):
        """Track which tab is in front, so `self.experiment` is honest."""
        try:
            self._active_index = self.notebook.index("current")
        except Exception:
            return
        self._refresh_run_gate()

    # ---- threading helpers ----
    def ui(self, fn, *args, **kwargs):
        """Run `fn` on the Tk main thread. Measurement code runs on a
        background thread and must not touch widgets directly, so any
        UI update from there goes through here.

        Wave 3 changed how. This used to call `self.root.after(0, ...)`
        directly from the worker, and `after()` is **not safe to call
        from another thread**: it registers a Tcl command, and Tcl is
        single-threaded. The application got away with it because the
        main thread sits inside `mainloop()`, where Tcl's own thread
        handoff covers for it - but the moment anything drives the loop
        with `update()` instead, the same call raises

            RuntimeError: main thread is not in main loop

        which is how Wave 3's threaded tests found it. A latent
        thread-safety bug that only a particular event-loop arrangement
        was hiding is worth removing rather than working around in the
        test.

        So workers now put work on a queue, and the main thread drains
        it on a timer it owns. Nothing off-thread touches Tcl at all.
        The cost is up to `UI_PUMP_MS` of latency on a progress line,
        which is invisible next to a settle delay.
        """
        self._ui_queue.put((fn, args, kwargs))

    def _drain_ui(self):
        """Run everything workers have queued. Main thread, on a timer.

        Each callback is isolated: one that raises must not stop the
        rest of the queue or kill the pump, or the window would stop
        updating and look like a hang.
        """
        while True:
            try:
                fn, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                # Console-only: a dialog here could fire hundreds of
                # times from a bad loop.
                self._log_direct(f"UI callback failed: {exc}")
        self._schedule_ui_pump()

    def _schedule_ui_pump(self):
        """Re-arm the drain. Silent if the window has gone.

        The existence check is not belt and braces: a timer left armed
        across `root.destroy()` fires into a dead interpreter, and Tcl
        reports that as `invalid command name ..._drain_ui` on stderr -
        noise in every test that closes a window without going through
        `on_close()`.
        """
        try:
            if not self.root.winfo_exists():
                self._ui_pump_id = None
                return
            self._ui_pump_id = self.root.after(UI_PUMP_MS, self._drain_ui)
        except Exception:
            self._ui_pump_id = None

    def _stop_ui_pump(self):
        pump_id, self._ui_pump_id = self._ui_pump_id, None
        if pump_id is not None:
            try:
                self.root.after_cancel(pump_id)
            except Exception:
                pass

    def drain_ui_now(self):
        """Run queued UI work immediately. Main thread only.

        For tests and for shutdown, where waiting for the next tick
        would mean asserting against a window that has not caught up.
        """
        while True:
            try:
                fn, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                self._log_direct(f"UI callback failed: {exc}")

    def run_in_background(self, fn, on_error=None):
        """Run `fn` on a daemon thread, reporting exceptions to the
        console rather than losing them silently in a dead thread."""
        def wrapper():
            try:
                fn()
            except Exception as e:
                self.log("Error:", e)
                if on_error is not None:
                    self.ui(on_error, e)
        threading.Thread(target=wrapper, daemon=True).start()

    # ---- logging ----
    def log(self, *args):
        """Append a timestamped line to the console. Safe from any
        thread - it goes through the same queue as `ui()`, for the same
        reason."""
        msg = " ".join(str(a) for a in args)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._ui_queue.put((self._append_console, (f"[{ts}] {msg}\n",), {}))

    def _append_console(self, full):
        self.console.configure(state="normal")
        self.console.insert("end", full)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _log_direct(self, message):
        """Write to the console without going through the queue.

        Two callers, both on the main thread and both for the same
        reason: the queue is not going to be drained again.

        * the drain loop itself, which must not re-enqueue while it is
          emptying;
        * the tail of `on_close()`, after `_stop_ui_pump()`. Anything
          queued from there is discarded by `root.destroy()`, and the
          messages at that point are the ones about hardware.
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._append_console(f"[{ts}] {message}\n")
        except Exception:
            pass

    # ---- instrument connection ----
    def instrument_identities(self):
        """`{role: what is connected}` for the operational log.

        The driver's display name and address rather than the raw
        `*IDN?` string: §26 asks for instrument identity so that a fault
        can be attributed to a box, and "which SMU was this?" is
        answered by the model and the port. A full `*IDN?` also carries
        a firmware revision that changes under the log's feet without
        the instrument having changed.
        """
        out = {}
        for role, driver in self.instruments.items():
            name = getattr(type(driver), "DISPLAY_NAME", type(driver).__name__)
            address = self.instrument_keys.get(role, "")
            out[role] = f"{name} @ {address}" if address else name
        return out

    def connect_role(self, role, transport, address, **connect_kwargs):
        """Open `transport` at `address`, identify what's there, and
        store the resulting driver under `role`.

        Auto-detection via *IDN? means the user picks an address, not a
        model. Returns the driver.
        """
        self.disconnect_role(role)
        transport.connect(address, **connect_kwargs)
        try:
            driver, idn = self.registry.identify(transport)
        except Exception:
            transport.close()
            raise
        self.transports[role] = transport
        self.instruments[role] = driver
        self.instrument_keys[role] = key_for_transport(transport)
        self.log(f"[{role}] connected: {idn}")
        self._initialise_driver(role, driver)
        self.experiment.on_connected(role, driver)
        return driver

    def connect_role_manual(self, role, transport, address, driver_cls, **connect_kwargs):
        """Same as connect_role, but with the driver chosen by hand -
        the fallback when *IDN? isn't recognised."""
        self.disconnect_role(role)
        transport.connect(address, **connect_kwargs)
        driver = driver_cls(transport)
        self.transports[role] = transport
        self.instruments[role] = driver
        self.instrument_keys[role] = key_for_transport(transport)
        self.log(f"[{role}] connected as {driver_cls.DISPLAY_NAME} (manual)")
        self._initialise_driver(role, driver)
        self.experiment.on_connected(role, driver)
        return driver

    def _initialise_driver(self, role, driver):
        """Put a freshly connected instrument into a known state.

        Every driver's reset() is where its housekeeping lives - the
        interlock line, line frequency, terminal selection, reading
        format. Until this call existed, none of it ran: reset() was
        written, documented and tested, and then never invoked from
        anywhere in the app.

        The consequence was worst on the GSM-20H10, whose reset()
        disables the output-enable interlock. Without that, an
        instrument with nothing wired to the rear-panel interlock pin
        refuses to turn its output on at all - so the first bench run
        would have failed with no clear reason why.

        Failures here are logged rather than raised: a reset that didn't
        take is worth knowing about, but it shouldn't turn a working
        connection into a dead one.

        What it does now do is **block runs on that instrument** (Wave 1,
        issue A9). "The instrument may be in whatever state it was left
        in" was always the right description and the wrong response: a
        measurement built on an unknown starting state is not a
        measurement, and on the GSM-20H10 a reset that did not run
        leaves the output interlock enabled so the output never comes on
        at all. The connection stays open - you can still talk to it,
        run the checkup, and retry - but a run that claims ownership is
        refused with the reason, until a reconnect resets it cleanly.
        """
        key = self.instrument_keys.get(role)
        try:
            driver.reset()
            self.log(f"[{role}] instrument reset to a known state")
            if key and self.ownership.unblock(key):
                self.log(f"[{role}] previous block cleared by a successful "
                         f"reset")
        except Exception as exc:
            reason = (f"The mandatory reset failed ({exc}), so the "
                      f"instrument's state is unknown.")
            self.log(f"[{role}] WARNING: reset failed ({exc}). Runs on this "
                     f"instrument are blocked until it reconnects cleanly.")
            if key:
                self.ownership.block(key, reason)

    def disconnect_role(self, role):
        """Close and forget whatever is connected in `role`. Turns the
        output off first - leaving an SMU sourcing into a disconnected
        app is how samples get cooked."""
        driver = self.instruments.pop(role, None)
        if driver is not None:
            driver.safe_output_off()
        key = self.instrument_keys.pop(role, None)
        if key is not None and self.ownership.force_release(key):
            # Normally a run releases its own claim during cleanup, so
            # this only fires when something was disconnected out from
            # under a live run. Worth a line rather than a silence.
            self.log(f"[{role}] released an instrument claim still held at "
                     f"disconnect")
        transport = self.transports.pop(role, None)
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    # ---- instrument ownership ----
    def instrument_key(self, role="source"):
        """The ownership key for whatever is connected in `role`.

        Names the physical connection, not the driver object, so two
        windows on one address collide as they should. See
        core/ownership.py.
        """
        key = self.instrument_keys.get(role)
        if key is None:
            raise ConnectionError(
                f"No instrument connected for "
                f"'{self.experiment.ROLES.get(role, role)}'.")
        return key

    def claim_instrument(self, role, run_id):
        """Take exclusive control of `role`'s instrument for a run.

        Hand the result to `RunContext.enter()` so it is released as
        part of run cleanup - that ordering is what makes the UI return
        to idle only after the instrument is free::

            session = run.enter(app.claim_instrument("source", run.run_id))

        Raises `InstrumentBusy` or `InstrumentBlocked`, both carrying a
        message written for a dialog box.
        """
        label = f"{self.experiment.ROLES.get(role, role)} ({self.instrument_key(role)})"
        return self.ownership.claim(self.instrument_key(role), run_id, label)

    def report_uncertain_shutdown(self, role, report):
        """Handle an output that could not be confirmed off (issue A10).

        This is the one ending that is not just "the run is spoiled".
        The instrument may still be energised into a sample, so it gets
        a console line, a modal warning, and a block on the connection
        that only a reconnect clears. Nothing else in the suite blocks
        an instrument on the strength of one bad run, and nothing else
        should.

        Two versions of the same handling. `report.link_lost` means the
        link stopped answering rather than the instrument reporting a
        fault, which needs a reconnect on top of a look at the front
        panel.
        """
        key = self.instrument_keys.get(role)
        detail = getattr(report, "detail", "") or "no further detail"
        described = self.experiment.ROLES.get(role, role)

        if getattr(report, "link_lost", False):
            # Same handling, different words. The operator response
            # differs: an instrument that reported a fault needs
            # looking at, while a link that stopped answering needs
            # looking at AND reconnecting before anything can run. A
            # message that only said "could not be confirmed" would
            # leave someone pressing Start and wondering why it is
            # refused.
            self.log(f"[{role}] EMERGENCY: the link stopped answering - "
                     f"{detail}")
            if key:
                self.ownership.block(
                    key, f"The link stopped answering mid-run and the "
                         f"output could not be confirmed off ({detail}) "
                         f"Reconnect the instrument.")
            self.ui(messagebox.showwarning, "The instrument stopped answering",
                    f"The link to '{described}' stopped answering partway "
                    f"through the run.\n\n{detail}\n\n"
                    f"An output-off was sent and will normally have reached "
                    f"the instrument, but it could not be confirmed - check "
                    f"the front panel before touching the fixture.\n\n"
                    f"This run has been discarded; readings taken after the "
                    f"link went would not have belonged to the points that "
                    f"asked for them. Runs already in the table are "
                    f"untouched.\n\nReconnect the instrument, then start "
                    f"the run again.")
            return

        self.log(f"[{role}] EMERGENCY: output shutdown could not be "
                 f"confirmed - {detail}")
        if key:
            self.ownership.block(
                key, f"The output could not be confirmed off ({detail}).")
        self.ui(messagebox.showwarning, "Output shutdown not confirmed",
                f"The output on '{described}' "
                f"could not be confirmed off.\n\n{detail}\n\n"
                f"The instrument may still be energised. Check it before "
                f"continuing; runs are blocked until it is reconnected.")

    def require_instrument(self, role="source"):
        """Return the driver in `role`, or raise with a message aimed at
        the user rather than at a stack trace."""
        driver = self.instruments.get(role)
        if driver is None:
            description = self.experiment.ROLES.get(role, role)
            raise ConnectionError(f"No instrument connected for '{description}'.")
        return driver

    def is_connected(self, role="source"):
        """True if `role` has a live instrument."""
        return role in self.instruments

    # ---- the limit gate ----
    def check_source_point(self, role="source", current=None, voltage=None):
        """Validate a requested operating point against the connected
        instrument's declared limits, before anything is sourced.

        This is the hard gate: it runs on every path that turns an output
        on, and refuses rather than clipping. Raises LimitError with a
        message meant for a dialog box.
        """
        driver = self.require_instrument(role)
        driver.validate_source_point(current=current, voltage=voltage)

    def guard_run(self, fn):
        """Wrap a measurement so the refusals surface as a dialog
        instead of a console line the user might miss.

        Four refusals, each with its own wording, because they call for
        different things from the operator: the point is outside what
        the instrument can do, nothing is connected, somebody else is
        using the instrument, or the instrument needs checking before it
        is used again.
        """
        def wrapper():
            if self._closing:
                # The first step of the close path, enforced at the one
                # place every run starts. A run that began after the
                # cancellation sweep would be a worker nobody is waiting
                # for, energising an instrument whose transport is about
                # to be closed.
                self.log("Run refused: the window is closing.")
                return
            try:
                fn()
            except LimitError as e:
                self.log("Refused:", e)
                self.ui(messagebox.showerror, "Outside instrument limits", str(e))
            except ConnectionError as e:
                self.log("Not connected:", e)
                self.ui(messagebox.showwarning, "Not connected", str(e))
            except InstrumentBlocked as e:
                self.log("Blocked:", e)
                self.ui(messagebox.showerror, "Instrument blocked", str(e))
            except InstrumentBusy as e:
                self.log("Busy:", e)
                self.ui(messagebox.showwarning, "Instrument in use", str(e))
            except RunRejected as e:
                self.log("Run refused:", e)
                self.ui(messagebox.showwarning, "Cannot start", str(e))
        return wrapper

    # ---- the save-collision pre-flight (Wave 5c-ii) ----
    def summary_collision_decision(self, sample_name):
        """Ask, at most once per (sample, folder), what to do if data
        for this sample already exists in the save folder.

        Returns True to let the run proceed, False to abort it.

        **Why at the run and not the save.** By the time a run is saved
        it already carries the sample identity it was measured under,
        and renaming the box afterwards does not retroactively fix it -
        it just files the runs under two names. Caught here, a mistyped
        sample name costs one dialog before twenty minutes of measuring
        rather than a tangled folder afterwards. That early warning is
        the check's real value; the overwrite question is the smaller
        half.

        **What the answer actually controls.** Only the summary file can
        overwrite - every data CSV auto-suffixes and is safe whatever is
        chosen here. So the three options reduce to: regenerate the one
        summary in place, or suffix it too, or stop and rename.

        Shared across tabs on purpose. A Van der Pauw run followed by a
        Hall run on the same mounted sample must not ask twice, so the
        decision lives on the app and is keyed by (sample, folder). It
        re-arms when either changes.
        """
        key = (sample_name, self.storage_path)
        if self._summary_decided_for == key:
            return True                # already answered for this pair

        existing = self._existing_files_for(sample_name)
        if not existing:
            # Nothing to collide with. Record the decision so a later
            # run under the same name doesn't re-scan, and default to
            # overwriting the summary this session creates.
            self._summary_decided_for = key
            self._summary_overwrite = True
            return True

        newest = max(existing, key=os.path.getmtime)
        when = datetime.datetime.fromtimestamp(
            os.path.getmtime(newest)).strftime("%Y-%m-%d")
        choice = self._ask_summary_collision(sample_name, len(existing), when)

        if choice == "cancel":
            self.log(f"Run cancelled: data for '{sample_name}' already "
                     f"exists in this folder")
            return False
        self._summary_overwrite = (choice == "same")
        self._summary_decided_for = key
        self.log(f"'{sample_name}': "
                 + ("summary will be regenerated" if self._summary_overwrite
                    else "summary will be kept separate"))
        return True

    def _existing_files_for(self, sample_name):
        """Files in the save folder whose name starts with this sample's
        slug. Matches *any* file for the sample - a data CSV is enough to
        warn on, and the summary may not exist yet if nobody has pressed
        Calculate before."""
        try:
            entries = os.listdir(self.storage_path)
        except OSError:
            return []
        prefix = f"{sample_name}_"
        return [os.path.join(self.storage_path, name) for name in entries
                if name.startswith(prefix) and name.endswith((".csv", ".txt"))]

    def _ask_summary_collision(self, sample_name, count, when):
        """The three-way question. Returns 'same', 'separate' or
        'cancel'.

        **Goes through `messagebox`, deliberately.** The first version
        built its own `Toplevel` with `grab_set()` and `wait_window()`,
        which looked nicer - three buttons saying what they do rather
        than Yes/No/Cancel - and was untestable in exactly the way this
        codebase already had a rule about. Every GUI test neutralises
        dialogs by monkeypatching the `messagebox` module inside the
        module under test; a hand-rolled window bypasses that seam, so
        any headless test that pressed Run with a matching file in the
        save folder blocked forever with nothing on screen to say why.

        The button labels are the price. The message carries the meaning
        instead, which is a poor trade in isolation and an easy one
        against a suite that can hang.

        Split into its own method so tests can drive the three outcomes
        directly without reasoning about which answer maps to which
        button.
        """
        answer = messagebox.askyesnocancel(
            "Data already exists",
            f"Data for '{sample_name}' already exists in this folder - "
            f"{count} file(s), most recent {when}.\n\n"
            f"Your measurement data is always kept: new files are added "
            f"alongside the old ones whatever you choose here. This only "
            f"affects the one-page summary file.\n\n"
            f"Yes - same sample: regenerate the summary, replacing the "
            f"old one.\n"
            f"No - keep separate: write a new summary alongside it.\n"
            f"Cancel - stop, so you can change the sample name first.")
        if answer is None:
            return "cancel"
        return "same" if answer else "separate"

    def note_sample_context_changed(self):
        """Re-arm the collision pre-flight if the sample name or the save
        folder has actually changed.

        Guarded against no-op writes on purpose. The sample-name trace
        fires on every write to the variable, including re-typing the
        same name or a programmatic set to the current value; re-arming
        on those would discard a decision that is still perfectly valid
        and silently drop the session back to suffixing. Only a genuine
        change to a different (sample, folder) pair clears it.
        """
        try:
            sample = (self.sample_name_var.get() or "").strip()
        except Exception:
            sample = ""
        context = (sample, self.storage_path)
        if context == self._summary_context:
            return
        self._summary_context = context
        self._summary_decided_for = None
        self._summary_overwrite = False

    # ---- file handling ----
    def select_path(self):
        """Pick a save folder, then create/use a YYMMDD-dated subfolder
        inside it."""
        base = filedialog.askdirectory(title="Select folder to save measurements",
                                       initialdir=self.storage_path)
        if not base:
            return
        dated = os.path.join(base, datetime.datetime.now().strftime("%y%m%d"))
        try:
            os.makedirs(dated, exist_ok=True)
            self.storage_path = dated
        except Exception as e:
            self.log("Could not create dated folder:", e)
            self.storage_path = base
        if hasattr(self, "path_display_var"):
            self.path_display_var.set(self.storage_path)
        self.note_sample_context_changed()
        self.log("Save path:", self.storage_path)

    def unique_filename(self, base_name, folder=None):
        """A path in `folder` that doesn't exist yet, adding _1, _2, ...
        before the extension. Stops a rerun from overwriting the last
        one."""
        folder = folder or self.storage_path
        base, ext = os.path.splitext(base_name)
        candidate = os.path.join(folder, base_name)
        n = 1
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{base}_{n}{ext}")
            n += 1
        return candidate

    def write_atomic(self, path, text):
        """Write via a .tmp file then rename, so an interrupted save
        can't leave a half-written data file behind.

        `newline=""` because the builder decides the line endings, not
        the platform. `core.run_store` sets `lineterminator="\\n"` on
        both CSV writers and joins both `#` headers with `"\\n"`,
        deliberately and with a test saying so - and then text mode
        translated every one of them to CRLF on Windows, so the code
        that produced the file and the file on disk disagreed. Nothing
        detected it: `test_the_files_are_written_with_lf_endings`
        inspects the string in memory, which is the side of the boundary
        that was already right.

        Which of the two to change was a real decision. RFC 4180
        specifies CRLF, so CRLF on disk was defensible; what was not
        defensible is that neither end had decided. Settled as LF, for
        three reasons. Files written on Linux have always been LF, so no
        reader can ever have depended on CRLF and none needs changing -
        `csv`, `pandas.read_csv` and Excel all take either. A file whose
        bytes depend on which bench machine saved it cannot be compared,
        checksummed or diffed against another, which is the same
        argument `build_id` in the header is there to make. And a writer
        that silently rewrites its input is the wrong shape regardless
        of which ending wins: `write_atomic` is asked to put *this text*
        on disk.

        Pinned at byte level by `test_snapshot_saving.py`, on the file
        rather than on the string.
        """
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)

    # ---- the per-sample summary (Wave 5c-ii) ----
    def write_sample_summary(self, sample_name, sample_id):
        """Regenerate one sample's summary file after a tab has saved.

        Spans both measurements of a sample, so the *app* writes it and
        not either experiment - a per-experiment writer would produce
        two half-summaries. Each hosted experiment is asked what it
        would contribute (`summary_contribution`), and the numbers come
        from memory, so a section calculated on either tab appears the
        moment that tab saves.

        **The one file in the suite that can replace itself.** Every
        data CSV auto-suffixes through `unique_filename` and cannot be
        lost; this is derived from files that are all still on disk, so
        overwriting the previous summary loses nothing that isn't
        recoverable from the headers. Whether it overwrites or suffixes
        is the operator's call, taken once at the first run and held on
        `self._summary_overwrite` - see `summary_collision_decision`.

        Three things it will not do:

        - **Write an all-empty summary.** If nothing has been calculated
          for this sample on any tab, the file is skipped rather than a
          good summary being replaced by a page of "not calculated".
        - **Abort the save.** A `PermissionError` - the summary open in
          Excel, which on Windows is a certainty rather than a
          hypothesis - is logged and swallowed. The data CSVs are
          already safely written by the time this runs; a summary that
          could not be refreshed is a stale convenience file, not lost
          data.
        - **Claim a section that is stale.** `summary_contribution`
          reads through `calculated_fields()`, which returns nothing for
          a stale result, so a stale half reads as "not calculated"
          rather than as a number the experiment's own CSV would refuse.
        """
        sections = []
        any_calculated = False
        for exp in self.experiments:
            if not exp.SUMMARY_QUANTITIES:
                continue
            rows = exp.summary_contribution(sample_id)
            title = exp.CSV_TITLE
            if rows:
                any_calculated = True
            sections.append((title, rows))

        if not any_calculated:
            return None

        text = build_sample_summary(sample_name, sample_id, sections)
        if self._summary_overwrite:
            path = os.path.join(self.storage_path, f"{sample_name}_summary.csv")
        else:
            path = self.unique_filename(f"{sample_name}_summary.csv")

        try:
            self.write_atomic(path, text)
        except PermissionError as e:
            self.log(f"Summary not updated ({os.path.basename(path)} is "
                     f"open elsewhere): {e}")
            return None
        self.log(f"Summary written to {os.path.basename(path)}")
        return path

    def take_meas_number(self):
        """Claim the next measurement number. Locked, because a run can
        be triggered while another is finishing."""
        with self._fs_lock:
            n = self.next_meas_number
            self.next_meas_number += 1
        if hasattr(self, "measnum_var"):
            self.ui(self.measnum_var.set, self.next_meas_number)
        return n

    # ---- shutdown ----
    @property
    def is_closing(self):
        """True once the close path has started refusing new runs."""
        return self._closing

    def _note_close(self, phase, detail=""):
        """Record one step of the close path. Observation, not control."""
        self.close_log.append((phase, detail))

    def unsaved_state(self):
        """Unsaved runs across every tab, or an explicit "unknown".

        Counted over all of them, not just the visible one. Before Wave
        5b `on_close()` asked `self.experiment` - singular - which in a
        two-tab window would have discarded the other tab's measurements
        without mentioning them.

        **Read from the store, and never zero by accident.** The count
        comes from `run_store.has_unsaved`, which is a plain property
        over a dict, rather than from `has_unsaved_runs()`, which is an
        overridable method an experiment could give a body that talks to
        something. An experiment whose store cannot be read is named in
        `unknown` instead of being counted as nothing: a guard that
        turns its own failure into "there is no unsaved data" is a guard
        that discards work precisely when something is already wrong.
        """
        total = 0
        unknown = []
        for exp in self.experiments:
            label = getattr(exp, "NAME", type(exp).__name__)
            try:
                store = exp.run_store
                if store.has_unsaved:
                    total += len(store)
            except Exception as exc:
                unknown.append(f"{label}: {type(exc).__name__}: {exc}")
        return UnsavedState(total, tuple(unknown))

    def unsaved_run_count(self):
        """How many unsaved runs the window holds, as a number.

        The display-only view of `unsaved_state()`. It cannot raise, and
        it cannot report "unknown" either - so nothing that has to
        *decide* anything may use it. The close path calls
        `unsaved_state()`.
        """
        return self.unsaved_state().count

    def _unsaved_data_guard_allows_closing(self):
        """The safety net that stops a long measurement being discarded.

        Returns True only when closing is known to be safe: either there
        is nothing unsaved, or the operator has been asked and said to
        discard it.

        **Unknown is not safe.** Both failure endings - a store that
        could not be read, and a confirmation dialog that raised - leave
        the window open and put a diagnostic in front of the operator.
        The alternative was what shipped: an exception anywhere in here
        was swallowed and the window closed anyway, so the one path that
        can destroy a morning's measuring was also the one path with no
        error handling at all.
        """
        state = self.unsaved_state()

        if not state.is_known:
            detail = "; ".join(state.unknown)
            self.log(f"CLOSE REFUSED: cannot tell whether there are "
                     f"unsaved measurements - {detail}")
            self._note_close(ClosePhase.REFUSED_TO_CLOSE, detail)
            self._warn(
                messagebox.showerror, "Cannot close safely",
                f"The window cannot tell whether the results tables hold "
                f"measurements that have not been saved, so it has not "
                f"closed.\n\n{detail}\n\nSave or clear the results, then "
                f"close again. If this repeats, copy the console before "
                f"ending the process - the runs are only in memory.")
            return False

        if not state.count:
            return True

        try:
            discard = messagebox.askyesno(
                "Unsaved measurements",
                f"{state.count} run(s) in the results table(s) have not "
                "been saved.\n\n"
                "Close anyway and discard them?")
        except Exception as exc:
            detail = (f"the confirmation dialog raised "
                      f"{type(exc).__name__}: {exc}")
            self.log(f"CLOSE REFUSED: {detail}")
            self._note_close(ClosePhase.REFUSED_TO_CLOSE, detail)
            return False

        if not discard:
            # Includes a dialog that answered with nothing at all. The
            # question was "may I throw this away", and silence is not
            # a yes.
            return False
        return True

    def _wait_for_runs_to_finish(self, timeout_s=None):
        """Wait, bounded, for every run to reach idle. Names those that didn't.

        Idle rather than "the worker thread ended": `RunController`
        reaches IDLE only after cleanup has run, which is where the
        output is put away and instrument ownership is released. That is
        the fact the disconnect below depends on.

        The loop drains the UI queue on every pass. Workers hand their
        last progress lines and their commit back through `ui()`, so a
        main thread that blocked on `wait_for_idle()` alone would be
        holding up the very queue it was waiting for - and a worker that
        posts before finishing would never be drained at all. See
        docs/rules/08-ui-is-a-queue.md.

        Returns the names of the experiments still busy when the budget
        ran out, so the caller can say which rather than that something
        was.

        `timeout_s` defaults to `CLEANUP_TIMEOUT_S`, resolved at the
        call rather than in the signature: a bound baked into a default
        argument is one a test cannot shorten, and an unshortenable
        bound is one whose expiry never gets a test.
        """
        if timeout_s is None:
            timeout_s = CLEANUP_TIMEOUT_S
        deadline = time.monotonic() + max(0.0, timeout_s)
        pending = list(self.experiments)
        while True:
            self.drain_ui_now()
            pending = [exp for exp in pending
                       if not exp.run_controller.wait_for_idle(timeout=0)]
            if not pending or time.monotonic() >= deadline:
                break
            time.sleep(CLEANUP_POLL_S)
        self.drain_ui_now()
        return [getattr(exp, "NAME", type(exp).__name__) for exp in pending]

    def _warn(self, dialog, title, message):
        """Show a shutdown warning now, on this thread, and keep it up.

        Not through `ui()`. Every other dialog in this class is queued
        because it is raised from a worker; these are raised from
        `on_close()` on the main thread, and the UI pump is about to
        stop and the window about to be destroyed. A queued warning
        about a heater would be discarded by `root.destroy()` with
        nothing on screen - which is fault 28's quiet half, in the one
        message that concerns somebody reaching into a fixture.

        A modal blocks here until it is dismissed, which is the point:
        the window does not disappear out from under the warning.
        """
        try:
            dialog(title, message)
        except Exception as exc:
            # The console is the last resort, and it is still on screen
            # at this point in the close path.
            self._log_direct(f"could not show '{title}': {exc}")

    def _stage_pid_off(self):
        """Switch the stage PID off and report whether it agreed.

        Returns a `StageShutdownReport` whatever happens. The two
        endings that are not the controller's own answer are both
        UNCERTAIN, because both leave the same question open:

        * a stage object with no `confirm_pid_off()` - a fake, or a
          future device - cannot say what its heater is doing, and a
          missing method is not evidence that nothing is on;
        * an exception out of `confirm_pid_off()` itself, which is
          already the guarded call, so anything escaping it is unplanned.
        """
        confirm = getattr(self.temp_ctrl, "confirm_pid_off", None)
        if confirm is None:
            return StageShutdownReport(
                ShutdownStatus.UNCERTAIN,
                "the temperature controller in use cannot report whether "
                "OFF was accepted")
        try:
            return confirm()
        except Exception as exc:
            return StageShutdownReport(
                ShutdownStatus.UNCERTAIN,
                f"switching the stage PID off raised "
                f"{type(exc).__name__}: {exc}")

    def shutdown_devices(self):
        """Put the shared side-channel devices in a safe state.

        The temperature stage lives here rather than on an experiment
        because one window has one of it. Called from `on_close()` after
        every experiment has had its own `on_close()`, and deliberately
        not part of any of them: a subclass that overrode `on_close()`
        and forgot to call `super()` would otherwise leave a heater
        running.

        The PID is switched off for the same reason `disconnect_role()`
        calls `safe_output_off()` on an SMU - hardware left driving with
        nothing watching it is the worse failure. Remove the
        `confirm_pid_off()` call if you ever want the stage held at
        temperature after the window closes.

        **The port is closed after the answer, not instead of it.**
        Closing first would make an unconfirmed OFF unreportable and
        unretryable: the link the warning is about would already be
        gone. Returns the report so the caller - and a test - can see
        which of the three endings happened.
        """
        # Stop the readout refreshing before the widgets go away, or the
        # last scheduled tick fires into a dead interpreter.
        poll_id, self._temp_poll_id = self._temp_poll_id, None
        if poll_id is not None:
            try:
                self.root.after_cancel(poll_id)
            except Exception:
                # Cleanup only, and safe: an id Tk has already forgotten
                # cannot fire, so failing to cancel it leaves nothing
                # scheduled and nothing energised.
                pass

        report = self._stage_pid_off()
        if report.uncertain:
            self.log(f"STAGE SHUTDOWN UNCERTAIN: {report.detail}")
            self._note_close(ClosePhase.DE_ENERGISED, report.detail)
            self._warn(
                messagebox.showwarning,
                "Temperature stage may still be heating",
                f"The hot/cold stage could NOT be confirmed switched "
                f"off.\n\n{report.detail}.\n\nSwitch the stage off at the "
                f"controller itself before leaving the bench. This "
                f"application is closing and will not be watching it.")
        else:
            if report.detail:
                self.log(f"Temperature stage: {report.detail}")
            self._note_close(ClosePhase.DE_ENERGISED, str(report.status))

        try:
            self.temp_ctrl.close()
        except Exception as exc:
            # Not silent, and not a second warning either. The heater
            # question was already answered above; a port that refuses
            # to close is a leaked handle in a process that is exiting.
            self.log(f"Temperature stage: the port did not close cleanly "
                     f"({exc}).")
        return report

    def on_close(self):
        """Close the window, in bounded steps, without leaving hardware on.

        The order is the safety argument, and every step is observable
        in `close_log`:

        1. **Refuse new runs.** `_closing` gates `guard_run`, so nothing
           can start a measurement after the cancellation sweep below.
        2. **Cancel every run**, from the app itself and then through
           each experiment's `on_close()`. Both, because a subclass that
           overrides without calling up must not be able to leave a
           worker running, and an app-level reordering must not either.
        3. **Wait for idle**, bounded, draining the UI queue while it
           waits. A run reaches IDLE only after its cleanup has put the
           output away and released ownership, so this is what stops a
           worker racing the transport teardown below and losing its
           shutdown and event-log state.
        4. **De-energise the shared devices**, and say so out loud if
           the stage could not be confirmed off.
        5. **Disconnect the transports**, then destroy the window.

        Before any of it, the unsaved-measurement guard: runs are held
        in memory until the operator saves them, so closing is the one
        routine action that can throw away real work. That guard can
        refuse, and a refusal leaves the window open and untouched -
        which is why `_closing` is put back.
        """
        if self._closing:
            # A second WM_DELETE_WINDOW while the first is still walking
            # the steps. Re-entering would cancel twice and destroy
            # twice; the first call is already committed to closing.
            return

        self._closing = True
        self._note_close(ClosePhase.REFUSED_NEW_RUNS)

        if not self._unsaved_data_guard_allows_closing():
            self._closing = False
            return

        cancelled = []
        for exp in self.experiments:
            if exp.run_controller.request_cancel("window closing"):
                cancelled.append(getattr(exp, "NAME", type(exp).__name__))
        for exp in self.experiments:
            try:
                exp.on_close()
            except Exception as exc:
                self.log(f"[{getattr(exp, 'NAME', exp)}] on_close() raised "
                         f"{type(exc).__name__}: {exc}. Its run was already "
                         f"cancelled above.")
        self._note_close(ClosePhase.CANCELLED_RUNS, ", ".join(cancelled))

        budget = CLEANUP_TIMEOUT_S
        stragglers = self._wait_for_runs_to_finish(budget)
        self._note_close(ClosePhase.WAITED_FOR_IDLE, ", ".join(stragglers))
        if stragglers:
            named = ", ".join(stragglers)
            self.log(f"SHUTDOWN: {named} did not finish cleaning up within "
                     f"{budget:g} s. Closing anyway.")
            self._warn(
                messagebox.showwarning,
                "A measurement did not stop",
                f"'{named}' was still cleaning up {budget:g} seconds after "
                f"being cancelled, and the window is closing without "
                f"it.\n\nIts instrument was not confirmed to have been put "
                f"away. Check the front panel before touching the fixture.")

        for exp in self.experiments:
            try:
                exp.shutdown_devices()
            except Exception as exc:
                self.log(f"[{getattr(exp, 'NAME', exp)}] shutdown_devices() "
                         f"raised {type(exc).__name__}: {exc}.")
        self.shutdown_devices()

        self._stop_ui_pump()
        disconnected = []
        for role in list(self.instruments):
            try:
                self.disconnect_role(role)
                disconnected.append(role)
            except Exception as exc:
                # `_log_direct`, not `log`: the pump has stopped, so
                # anything queued from here on is never drained.
                self._log_direct(f"[{role}] did not disconnect cleanly: "
                                 f"{exc}")
        self._note_close(ClosePhase.DISCONNECTED, ", ".join(disconnected))

        self._note_close(ClosePhase.DESTROYED)
        self.root.destroy()
