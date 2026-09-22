"""
Temperature stage panel - Seeeduino Xiao hot/cold stage.

Owned by the application, not by an experiment.

It always lived in core/gui/ because more than one experiment used the
same stage, but each experiment still built its own copy of this panel
and held its own `TemperatureController`. In a one-experiment window
that was merely redundant. In the combined Van der Pauw + Hall window it
would have been **two controllers opening one COM port** - a failure
that happens at the bench and not in the suite, because no test has a
serial stage attached.

So the controller lives on `LabApp` and this panel is built once per
window, into a rail beside the tabs. It takes the app directly and
touches no experiment at all, which also makes the one-way dependency
rule trivially true rather than carefully maintained: core/ imports
nothing from experiments/.

Widgets attach to the app as `app.temp_*`.

This panel carries its own connect controls rather than using the
app-wide connection panel at the top of the window. That isn't
inconsistency, it's a different kind of device:

  - The connection panel drives *roles*, and a role means an instrument
    that answers *IDN? and resolves to a driver. The Xiao answers no such
    thing.
  - The stage is optional. Not every experiment has one attached, and a
    missing stage must never block a measurement.

So it connects itself, here, and the rest of the app neither knows nor
cares whether it's plugged in.

Two pieces, because the stage is *set* occasionally and *watched*
continuously. The strip in the top row is the watching half: the
temperature, the setpoint and what the stage is doing, on one line that
stays visible, including mid-run. Everything that commands the stage -
the port, Connect, the setpoint, PID - is behind the Stage button, in a
window of its own.

That split is what gave the experiment's own panels the left column
back. The controls were a 200 px rail down every window for the sake of
a dialogue that happens twice a session.

Polling carries on whether that window is open or not, because the
strip is what it feeds.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from smuniversal_lab_suite.core.gui.theme import theme_for
from smuniversal_lab_suite.core.gui.tooltips import tip
from smuniversal_lab_suite.core.transports.serial_transport import (
    SerialTransport,
)
from smuniversal_lab_suite.devices.temperature_control import (
    MAX_SETPOINT_C,
    MIN_SETPOINT_C,
)

# 5 Hz. The board reports at 10 Hz, so this can't miss a change for long,
# and it's slow enough to be invisible in CPU terms.
POLL_MS = 200

#: What the stage is doing, as a label style. Heating and cooling carry
#: meaning of their own, so - like the carrier types - they keep their
#: own hues in both modes rather than taking the experiment's accent.
STATE_STYLES = {
    "HEATING": "Hot.Bold.TLabel",
    "COOLING": "Cold.Bold.TLabel",
    "IDLE": "Hint.Bold.TLabel",
    "FAULT": "Warn.Bold.TLabel",
}


def build_temp_strip(app, parent):
    """The always-visible half: one line, no controls.

    Sets app.temp_readout_var, app.temp_sp_var, app.temp_state_var,
    app.temp_readout_label, app.temp_state_label and app.temp_btn.
    Returns the frame.
    """
    frame = ttk.Frame(parent, padding=(10, 4))
    app.temp_frame = frame

    ttk.Label(frame, text="Stage", style="Hint.TLabel").pack(side="left")

    app.temp_readout_var = tk.StringVar(value="--")
    app.temp_readout_label = ttk.Label(frame,
                                       textvariable=app.temp_readout_var,
                                       style="Bold.TLabel")
    app.temp_readout_label.pack(side="left", padx=(8, 0))

    app.temp_sp_var = tk.StringVar(value="SP --")
    ttk.Label(frame, textvariable=app.temp_sp_var,
              style="Hint.TLabel").pack(side="left", padx=(8, 0))

    app.temp_state_var = tk.StringVar(value="not connected")
    app.temp_state_label = ttk.Label(frame, textvariable=app.temp_state_var,
                                     style="Bold.TLabel")
    app.temp_state_label.pack(side="left", padx=(8, 0))

    app.temp_btn = ttk.Button(frame, text="Stage...", width=9,
                              command=lambda: open_stage_window(app))
    app.temp_btn.pack(side="left", padx=(10, 0))
    tip(app.experiment, app.temp_btn,
        "The stage's controls - port, Connect, setpoint and PID - in a "
        "window of its own. The reading beside this button is live "
        "whether that window is open or not.")

    # Nothing to enable until that window exists.
    app._temp_controls = []
    app.temp_port_var = tk.StringVar(value="")
    app.temp_setpoint_var = tk.StringVar(value="25")
    _refresh_ports(app)
    _schedule_poll(app)
    return frame


def open_stage_window(app):
    """Open the stage's controls, or raise them if they are open."""
    window = getattr(app, "temp_window", None)
    if window is not None:
        try:
            if window.winfo_exists():
                window.deiconify()
                window.lift()
                return window
        except tk.TclError:
            pass              # destroyed with its parent
    app.temp_window = _build_stage_window(app)
    return app.temp_window


def _build_stage_window(app):
    """The commanding half, built on demand."""
    window = tk.Toplevel(app.root)
    window.title("Temperature stage")
    window.resizable(False, False)
    theme_for(app.root).paint_toplevel(window)

    frame = ttk.Frame(window, padding=10)
    frame.pack(fill="both", expand=True)

    # ---- connection ----
    ttk.Label(frame, text="Port:").grid(row=0, column=0, sticky="e",
                                        padx=(0, 6), pady=2)
    app.temp_port_combo = ttk.Combobox(frame, textvariable=app.temp_port_var,
                                       width=18)
    app.temp_port_combo.grid(row=0, column=1, columnspan=2, sticky="ew",
                             pady=2)

    conn_buttons = ttk.Frame(frame)
    conn_buttons.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))
    ttk.Button(conn_buttons, text="Refresh", width=8,
               command=lambda: _refresh_ports(app)).pack(side="left")
    connected = app.temp_ctrl.is_connected()
    app.temp_connect_btn = ttk.Button(
        conn_buttons, text="Disconnect" if connected else "Connect",
        width=10, command=lambda: _toggle_connect(app))
    app.temp_connect_btn.pack(side="left", padx=(4, 0))

    ttk.Separator(frame, orient="horizontal").grid(
        row=2, column=0, columnspan=3, sticky="ew", pady=8)

    # ---- setpoint and PID ----
    ttk.Label(frame, text="Setpoint (°C):").grid(row=3, column=0, sticky="e",
                                                 padx=(0, 6), pady=2)
    setpoint_entry = ttk.Entry(frame, textvariable=app.temp_setpoint_var,
                               width=8)
    setpoint_entry.grid(row=3, column=1, sticky="w", pady=2)
    # Enter in the box does the same as the button - saves a mouse trip
    setpoint_entry.bind("<Return>", lambda _event: _set_setpoint(app))
    set_btn = ttk.Button(frame, text="Set", width=6,
                         command=lambda: _set_setpoint(app))
    set_btn.grid(row=3, column=2, sticky="w", padx=(4, 0), pady=2)

    pid_row = ttk.Frame(frame)
    pid_row.grid(row=4, column=1, columnspan=2, sticky="w", pady=(4, 0))
    on_btn = ttk.Button(pid_row, text="PID ON", width=8,
                        command=lambda: _pid(app, True))
    on_btn.pack(side="left")
    off_btn = ttk.Button(pid_row, text="PID OFF", width=8,
                         command=lambda: _pid(app, False))
    off_btn.pack(side="left", padx=(4, 0))

    ttk.Label(frame, style="Small.Hint.TLabel",
              text=f"Range {MIN_SETPOINT_C:g} to {MAX_SETPOINT_C:g} °C").grid(
        row=5, column=1, columnspan=2, sticky="w", pady=(4, 0))

    # Everything that needs a live connection, disabled until there is
    # one. Re-applied every time the window is built, because the state
    # that decides it lives on the controller, not on these widgets.
    app._temp_controls = [setpoint_entry, set_btn, on_btn, off_btn]
    _set_controls_enabled(app, connected)
    _refresh_ports(app)

    def on_close():
        # The widgets go; the connection, the PID and the polling stay.
        app._temp_controls = []
        app.temp_port_combo = None
        app.temp_connect_btn = None
        app.temp_window = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", on_close)
    return window


# ---- connection ----
    ttk.Label(frame, text="Port:").pack(anchor="w")

    app.temp_port_var = tk.StringVar(value="")
    # Width chosen against the budget, not by eye: the rail stands
    # beside the experiment's own three columns, so every pixel here is
    # a pixel of window width. Long POSIX device paths scroll rather
    # than widen the panel.
    app.temp_port_combo = ttk.Combobox(frame, textvariable=app.temp_port_var,
                                       width=10)
    app.temp_port_combo.pack(fill="x", pady=(2, 4))

    conn_buttons = ttk.Frame(frame)
    conn_buttons.pack(fill="x")
    ttk.Button(conn_buttons, text="Refresh", width=7,
               command=lambda: _refresh_ports(app)).pack(side="left")
    app.temp_connect_btn = ttk.Button(conn_buttons, text="Connect", width=9,
                                      command=lambda: _toggle_connect(app))
    app.temp_connect_btn.pack(side="left", padx=(4, 0))

    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)

    # ---- setpoint ----
    ttk.Label(frame, text="Setpoint (°C):").pack(anchor="w")

    setpoint_row = ttk.Frame(frame)
    setpoint_row.pack(fill="x", pady=(2, 4))
    app.temp_setpoint_var = tk.StringVar(value="25")
    setpoint_entry = ttk.Entry(setpoint_row, textvariable=app.temp_setpoint_var,
                               width=8)
    setpoint_entry.pack(side="left")
    # Enter in the box does the same as the button - saves a mouse trip
    setpoint_entry.bind("<Return>", lambda _event: _set_setpoint(app))
    set_btn = ttk.Button(setpoint_row, text="Set", width=6,
                         command=lambda: _set_setpoint(app))
    set_btn.pack(side="left", padx=(4, 0))

    pid_row = ttk.Frame(frame)
    pid_row.pack(fill="x")
    on_btn = ttk.Button(pid_row, text="PID ON", width=7,
                        command=lambda: _pid(app, True))
    on_btn.pack(side="left")
    off_btn = ttk.Button(pid_row, text="PID OFF", width=7,
                         command=lambda: _pid(app, False))
    off_btn.pack(side="left", padx=(4, 0))

    ttk.Label(frame, style="Small.Hint.TLabel",
              text=f"Range {MIN_SETPOINT_C:g} to {MAX_SETPOINT_C:g} °C").pack(
        anchor="w", pady=(4, 0))

    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)

    # ---- live readout ----
    app.temp_readout_var = tk.StringVar(value="--")
    app.temp_readout_label = ttk.Label(frame, textvariable=app.temp_readout_var,
                                       style="Readout.TLabel",
                                       anchor="center")
    app.temp_readout_label.pack(fill="x")

    app.temp_sp_var = tk.StringVar(value="SP --")
    ttk.Label(frame, textvariable=app.temp_sp_var, anchor="center").pack(fill="x")

    app.temp_state_var = tk.StringVar(value="not connected")
    app.temp_state_label = ttk.Label(frame, textvariable=app.temp_state_var,
                                     style="Bold.TLabel",
                                     anchor="center")
    app.temp_state_label.pack(fill="x")

    # Everything that needs a live connection, disabled until there is one
    app._temp_controls = [setpoint_entry, set_btn, on_btn, off_btn]
    _set_controls_enabled(app, False)

    _refresh_ports(app)
    _schedule_poll(app)


# ---- connection ----
def _refresh_ports(app):
    """Repopulate the COM port list. Reuses the transport layer's port
    enumeration - the one piece of it that genuinely applies here.

    Also runs once at start-up, when the stage window does not exist:
    the log line is worth having in every session, because "0 serial
    port(s) available" is the first thing to read when a stage that was
    plugged in does not appear.
    """
    ports = SerialTransport.list_available()
    combo = getattr(app, "temp_port_combo", None)
    if combo is not None:
        try:
            combo["values"] = ports
        except tk.TclError:
            pass              # the window closed under us
    if ports and not app.temp_port_var.get():
        app.temp_port_var.set(ports[0])
    app.log(f"[stage] {len(ports)} serial port(s) available")


def _connect_button(app, **options):
    """Configure the Connect button if it is there.

    It lives in the stage window, which the operator can close at any
    point - including while a connection attempt is in flight on a
    worker thread. The connection is the controller's; the button is
    only how it was asked for.
    """
    button = getattr(app, "temp_connect_btn", None)
    if button is None:
        return
    try:
        button.config(**options)
    except tk.TclError:
        pass                  # the window closed under us


def _toggle_connect(app):
    """Connect or disconnect the stage."""
    controller = app.temp_ctrl

    if controller.is_connected():
        controller.close()
        _connect_button(app, text="Connect")
        _set_controls_enabled(app, False)
        app.log("[stage] disconnected")
        return

    port = app.temp_port_var.get().strip()
    if not port:
        messagebox.showwarning("No port", "Pick a serial port for the stage first.")
        return

    _connect_button(app, state="disabled")
    app.log(f"[stage] connecting to {port} ...")

    def task():
        try:
            controller.connect(port)
            app.ui(_connect_button, app, text="Disconnect")
            app.ui(_set_controls_enabled, app, True)
            app.log(f"[stage] connected on {port}")
        except Exception as e:
            # A stage that won't connect is an inconvenience, not a
            # blocked measurement - say so and carry on.
            app.log("[stage] connection failed:", e)
            app.ui(messagebox.showerror, "Stage connection failed",
                       f"Could not open {port}.\n\n{e}\n\n"
                       f"The measurement will still run without it.")
        finally:
            app.ui(_connect_button, app, state="normal")

    app.run_in_background(task)


def _set_controls_enabled(app, enabled):
    """Grey out the command widgets when there's nothing to command."""
    state = "normal" if enabled else "disabled"
    for widget in app._temp_controls:
        try:
            widget.config(state=state)
        except tk.TclError:
            pass


# ---- commands ----
def _set_setpoint(app):
    """Validate and send the setpoint from the entry box."""
    text = (app.temp_setpoint_var.get() or "").strip()
    try:
        value = app.temp_ctrl.set_setpoint(text)
    except ValueError as e:
        messagebox.showerror("Invalid setpoint", str(e))
        return
    except ConnectionError as e:
        messagebox.showwarning("Stage not connected", str(e))
        return
    except Exception as e:
        app.log("[stage] setpoint failed:", e)
        messagebox.showerror("Stage error", str(e))
        return
    app.log(f"[stage] setpoint -> {value:.1f} °C")


def _pid(app, turn_on):
    """PID ON / OFF buttons."""
    try:
        if turn_on:
            app.temp_ctrl.pid_on()
            app.log("[stage] PID ON")
        else:
            app.temp_ctrl.pid_off()
            app.log("[stage] PID OFF")
    except ConnectionError as e:
        messagebox.showwarning("Stage not connected", str(e))
    except Exception as e:
        app.log("[stage] command failed:", e)
        messagebox.showerror("Stage error", str(e))


# ---- live readout ----
def _schedule_poll(app):
    """Kick off the readout refresh loop on the Tk main thread.

    The pending callback id is kept on the app so shutdown can
    cancel it. Without that, a tick scheduled just before the window
    closes fires into a dead interpreter and Tk prints an "invalid
    command name" complaint that looks like a crash but isn't.
    """
    def tick():
        # The window can still go away between scheduling and firing.
        try:
            if not app.temp_readout_label.winfo_exists():
                return
        except tk.TclError:
            return
        _update_readout(app)
        app._temp_poll_id = app.root.after(POLL_MS, tick)

    app._temp_poll_id = app.root.after(POLL_MS, tick)


def _update_readout(app):
    """Copy the latest snapshot into the labels.

    Three distinct conditions get three distinct displays, because they
    call for three different actions:
        not connected  - nothing to do
        stale          - check the cable / board
        faulted        - check the thermocouple
    """
    controller = app.temp_ctrl

    if not controller.is_connected():
        app.temp_readout_var.set("--")
        app.temp_sp_var.set("SP --")
        app.temp_state_var.set("not connected")
        app.temp_state_label.config(style="Bold.TLabel")
        return

    status = controller.status()

    if status.is_stale:
        # Port open but the board has gone quiet. Showing the last known
        # number without flagging it would be worse than showing nothing.
        app.temp_readout_var.set(status.temp_text())
        app.temp_state_var.set("no data")
        app.temp_state_label.config(style="Warn.Bold.TLabel")
    else:
        app.temp_readout_var.set(status.temp_text())
        app.temp_state_var.set(status.state.title())
        app.temp_state_label.config(
            style=STATE_STYLES.get(status.state, "Hint.Bold.TLabel"))

    app.temp_sp_var.set(
        "SP --" if status.setpoint_c is None else f"SP {status.setpoint_c:.1f} °C")
