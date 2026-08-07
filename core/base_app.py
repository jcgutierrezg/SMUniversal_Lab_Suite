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
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core import driver_registry
from core.limits import LimitError
from core.gui.connection_panel import build_connection_panel
from core.gui.console_panel import build_console_panel


class LabApp:
    """Hosts one experiment. Construct with the experiment class, not an
    instance - the app builds it once the window exists."""

    def __init__(self, root, experiment_cls):
        self.root = root
        self.experiment = experiment_cls(self)
        root.title(self.experiment.NAME)

        # role key -> connected driver instance
        self.instruments = {}
        # role key -> transport instance (kept so we can close them)
        self.transports = {}

        self.storage_path = os.path.expanduser("~")
        self._fs_lock = threading.Lock()
        self.next_meas_number = 1

        self._build_ui()
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
        UI update from there goes through here."""
        self.root.after(0, lambda: fn(*args, **kwargs))

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
        thread."""
        msg = " ".join(str(a) for a in args)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full = f"[{ts}] {msg}\n"

        def _append():
            self.console.configure(state="normal")
            self.console.insert("end", full)
            self.console.see("end")
            self.console.configure(state="disabled")
        self.root.after(0, _append)

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
            driver, idn = driver_registry.identify(transport)
        except Exception:
            transport.close()
            raise
        self.transports[role] = transport
        self.instruments[role] = driver
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
        """
        try:
            driver.reset()
            self.log(f"[{role}] instrument reset to a known state")
        except Exception as exc:
            self.log(f"[{role}] WARNING: reset failed ({exc}). The "
                     f"instrument may be in whatever state it was left in.")

    def disconnect_role(self, role):
        """Close and forget whatever is connected in `role`. Turns the
        output off first - leaving an SMU sourcing into a disconnected
        app is how samples get cooked."""
        driver = self.instruments.pop(role, None)
        if driver is not None:
            driver.safe_output_off()
        transport = self.transports.pop(role, None)
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

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
        """Wrap a measurement so limit failures surface as a dialog
        instead of a console line the user might miss."""
        def wrapper():
            try:
                fn()
            except LimitError as e:
                self.log("Refused:", e)
                self.ui(messagebox.showerror, "Outside instrument limits", str(e))
            except ConnectionError as e:
                self.log("Not connected:", e)
                self.ui(messagebox.showwarning, "Not connected", str(e))
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
        for role in list(self.instruments):
            self.disconnect_role(role)
        self.root.destroy()
