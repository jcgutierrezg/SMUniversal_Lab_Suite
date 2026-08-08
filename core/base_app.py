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
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from drivers import registry as default_driver_registry
from core.identity import SampleRegistry
from core.limits import LimitError
from core.ownership import (InstrumentBlocked, InstrumentBusy,
                            default_ownership, key_for_transport)
from core.run_control import RunRejected
from core.gui.connection_panel import build_connection_panel
from core.gui.console_panel import build_console_panel


#: How often the main thread drains work queued by measurement threads.
#: Fast enough that a progress line looks live, slow enough to cost
#: nothing when idle.
UI_PUMP_MS = 10


class LabApp:
    """Hosts one experiment. Construct with the experiment class, not an
    instance - the app builds it once the window exists.

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
                 samples=None):
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
        self.experiment = experiment_cls(self)
        root.title(self.experiment.NAME)

        # role key -> connected driver instance
        self.instruments = {}
        # role key -> transport instance (kept so we can close them)
        self.transports = {}
        # role key -> ownership key for the physical connection behind it
        self.instrument_keys = {}

        self.storage_path = os.path.expanduser("~")
        self._fs_lock = threading.Lock()
        self.next_meas_number = 1

        # Work handed back from measurement threads. Drained by the main
        # thread on a timer - see `ui()` for why it is a queue and not a
        # direct `after()` call.
        self._ui_queue = queue.Queue()
        self._ui_pump_id = None

        self._build_ui()
        self._schedule_ui_pump()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- UI construction ----
    def _build_ui(self):
        """Connection panel on top, the experiment's own panels in the
        middle, console at the bottom."""
        # Weights all the way down, so dragging the window bigger gives
        # the space to the panels rather than leaving a grey border.
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=8)
        main.grid(sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)      # the experiment's panels

        build_connection_panel(self, main)

        body = ttk.Frame(main)
        body.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.experiment.build_panels(body)

        build_console_panel(self, main)

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

        Only for the drain loop itself, which is already on the main
        thread and must not re-enqueue while it is emptying.
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._append_console(f"[{ts}] {message}\n")
        except Exception:
            pass

    # ---- instrument connection ----
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
        """
        key = self.instrument_keys.get(role)
        detail = getattr(report, "detail", "") or "no further detail"
        self.log(f"[{role}] EMERGENCY: output shutdown could not be "
                 f"confirmed - {detail}")
        if key:
            self.ownership.block(
                key, f"The output could not be confirmed off ({detail}).")
        self.ui(messagebox.showwarning, "Output shutdown not confirmed",
                f"The output on '{self.experiment.ROLES.get(role, role)}' "
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
        can't leave a half-written data file behind."""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

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
    def on_close(self):
        """Let the experiment clean up, put every instrument in a safe
        state, then close.

        Asks first if there are measurements that haven't been saved.
        Runs are held in memory until the operator saves them, so closing
        is the one routine action that can throw away real work.
        """
        try:
            if self.experiment.has_unsaved_runs():
                keep_open = messagebox.askyesno(
                    "Unsaved measurements",
                    f"{len(self.experiment.run_store)} run(s) in the results "
                    "table have not been saved.\n\n"
                    "Close anyway and discard them?")
                if not keep_open:
                    return
        except Exception:
            pass
        try:
            self.experiment.on_close()
        except Exception:
            pass
        try:
            self.experiment.shutdown_devices()
        except Exception:
            pass
        self._stop_ui_pump()
        for role in list(self.instruments):
            self.disconnect_role(role)
        self.root.destroy()
