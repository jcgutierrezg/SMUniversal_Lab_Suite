"""
Temperature stage panel - Seeeduino Xiao hot/cold stage.

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

Widgets attach to the experiment as exp.temp_* so the experiment can
reach them, matching the pattern used by the other panels.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from core.transports.serial_transport import SerialTransport
from devices.temperature_control import MIN_SETPOINT_C, MAX_SETPOINT_C

# 5 Hz. The board reports at 10 Hz, so this can't miss a change for long,
# and it's slow enough to be invisible in CPU terms.
POLL_MS = 200

STATE_COLOURS = {
    "HEATING": "#c62828",
    "COOLING": "#1565c0",
    "IDLE": "#555555",
    "FAULT": "#b26a00",
}


def build_temp_panel(exp, parent):
    """Build the temperature stage panel.

    Sets exp.temp_port_var, exp.temp_port_combo, exp.temp_connect_btn,
    exp.temp_setpoint_var, exp.temp_readout_var, exp.temp_sp_var,
    exp.temp_state_var and the control widgets in exp._temp_controls.
    """
    frame = ttk.LabelFrame(exp.right, text="Temperature stage (optional)",
                           padding=8)
    frame.pack(fill="x", pady=(8, 0))

    # ---- connection row ----
    conn = ttk.Frame(frame)
    conn.pack(fill="x")

    ttk.Label(conn, text="Port:").pack(side="left")

    exp.temp_port_var = tk.StringVar(value="")
    exp.temp_port_combo = ttk.Combobox(conn, textvariable=exp.temp_port_var,
                                       width=12)
    exp.temp_port_combo.pack(side="left", padx=(6, 4))

    ttk.Button(conn, text="Refresh", width=8,
               command=lambda: _refresh_ports(exp)).pack(side="left", padx=(0, 4))

    exp.temp_connect_btn = ttk.Button(conn, text="Connect", width=10,
                                      command=lambda: _toggle_connect(exp))
    exp.temp_connect_btn.pack(side="left")

    # ---- setpoint row ----
    setrow = ttk.Frame(frame)
    setrow.pack(fill="x", pady=(8, 0))

    ttk.Label(setrow, text="Setpoint (°C):").pack(side="left")

    exp.temp_setpoint_var = tk.StringVar(value="25")
    setpoint_entry = ttk.Entry(setrow, textvariable=exp.temp_setpoint_var, width=8)
    setpoint_entry.pack(side="left", padx=(6, 4))
    # Enter in the box does the same as the button - saves a mouse trip
    setpoint_entry.bind("<Return>", lambda _event: _set_setpoint(exp))

    set_btn = ttk.Button(setrow, text="Set", width=5,
                         command=lambda: _set_setpoint(exp))
    set_btn.pack(side="left", padx=(0, 12))

    on_btn = ttk.Button(setrow, text="PID ON", width=8,
                        command=lambda: _pid(exp, True))
    on_btn.pack(side="left", padx=(0, 4))

    off_btn = ttk.Button(setrow, text="PID OFF", width=8,
                         command=lambda: _pid(exp, False))
    off_btn.pack(side="left")

    ttk.Label(frame, foreground="#777",
              text=f"Range {MIN_SETPOINT_C:g} to {MAX_SETPOINT_C:g} °C").pack(
        anchor="w", pady=(2, 0))

    # ---- live readout ----
    readout = ttk.Frame(frame)
    readout.pack(fill="x", pady=(8, 0))

    exp.temp_readout_var = tk.StringVar(value="--")
    exp.temp_readout_label = ttk.Label(readout, textvariable=exp.temp_readout_var,
                                       font=("TkDefaultFont", 20, "bold"),
                                       width=8, anchor="w")
    exp.temp_readout_label.pack(side="left")

    right = ttk.Frame(readout)
    right.pack(side="left", padx=(4, 0))

    exp.temp_sp_var = tk.StringVar(value="SP --")
    ttk.Label(right, textvariable=exp.temp_sp_var).pack(anchor="w")

    exp.temp_state_var = tk.StringVar(value="not connected")
    exp.temp_state_label = ttk.Label(right, textvariable=exp.temp_state_var,
                                     font=("TkDefaultFont", 9, "bold"))
    exp.temp_state_label.pack(anchor="w")

    # Everything that needs a live connection, disabled until there is one
    exp._temp_controls = [setpoint_entry, set_btn, on_btn, off_btn]
    _set_controls_enabled(exp, False)

    _refresh_ports(exp)
    _schedule_poll(exp)


# ---- connection ----
def _refresh_ports(exp):
    """Repopulate the COM port list. Reuses the transport layer's port
    enumeration - the one piece of it that genuinely applies here."""
    ports = SerialTransport.list_available()
    exp.temp_port_combo["values"] = ports
    if ports and not exp.temp_port_var.get():
        exp.temp_port_var.set(ports[0])
    exp.log(f"[stage] {len(ports)} serial port(s) available")


def _toggle_connect(exp):
    """Connect or disconnect the stage."""
    controller = exp.temp_ctrl

    if controller.is_connected():
        controller.close()
        exp.temp_connect_btn.config(text="Connect")
        _set_controls_enabled(exp, False)
        exp.log("[stage] disconnected")
        return

    port = exp.temp_port_var.get().strip()
    if not port:
        messagebox.showwarning("No port", "Pick a serial port for the stage first.")
        return

    exp.temp_connect_btn.config(state="disabled")
    exp.log(f"[stage] connecting to {port} ...")

    def task():
        try:
            controller.connect(port)
            exp.app.ui(exp.temp_connect_btn.config, text="Disconnect")
            exp.app.ui(_set_controls_enabled, exp, True)
            exp.log(f"[stage] connected on {port}")
        except Exception as e:
            # A stage that won't connect is an inconvenience, not a
            # blocked measurement - say so and carry on.
            exp.log("[stage] connection failed:", e)
            exp.app.ui(messagebox.showerror, "Stage connection failed",
                       f"Could not open {port}.\n\n{e}\n\n"
                       f"The measurement will still run without it.")
        finally:
            exp.app.ui(exp.temp_connect_btn.config, state="normal")

    exp.app.run_in_background(task)


def _set_controls_enabled(exp, enabled):
    """Grey out the command widgets when there's nothing to command."""
    state = "normal" if enabled else "disabled"
    for widget in exp._temp_controls:
        try:
            widget.config(state=state)
        except tk.TclError:
            pass


# ---- commands ----
def _set_setpoint(exp):
    """Validate and send the setpoint from the entry box."""
    text = (exp.temp_setpoint_var.get() or "").strip()
    try:
        value = exp.temp_ctrl.set_setpoint(text)
    except ValueError as e:
        messagebox.showerror("Invalid setpoint", str(e))
        return
    except ConnectionError as e:
        messagebox.showwarning("Stage not connected", str(e))
        return
    except Exception as e:
        exp.log("[stage] setpoint failed:", e)
        messagebox.showerror("Stage error", str(e))
        return
    exp.log(f"[stage] setpoint -> {value:.1f} °C")


def _pid(exp, turn_on):
    """PID ON / OFF buttons."""
    try:
        if turn_on:
            exp.temp_ctrl.pid_on()
            exp.log("[stage] PID ON")
        else:
            exp.temp_ctrl.pid_off()
            exp.log("[stage] PID OFF")
    except ConnectionError as e:
        messagebox.showwarning("Stage not connected", str(e))
    except Exception as e:
        exp.log("[stage] command failed:", e)
        messagebox.showerror("Stage error", str(e))


# ---- live readout ----
def _schedule_poll(exp):
    """Kick off the readout refresh loop on the Tk main thread."""
    def tick():
        # The window can go away between scheduling and firing.
        try:
            if not exp.temp_readout_label.winfo_exists():
                return
        except tk.TclError:
            return
        _update_readout(exp)
        exp.app.root.after(POLL_MS, tick)

    exp.app.root.after(POLL_MS, tick)


def _update_readout(exp):
    """Copy the latest snapshot into the labels.

    Three distinct conditions get three distinct displays, because they
    call for three different actions:
        not connected  - nothing to do
        stale          - check the cable / board
        faulted        - check the thermocouple
    """
    controller = exp.temp_ctrl

    if not controller.is_connected():
        exp.temp_readout_var.set("--")
        exp.temp_sp_var.set("SP --")
        exp.temp_state_var.set("not connected")
        exp.temp_state_label.config(foreground="#777777")
        return

    status = controller.status()

    if status.is_stale:
        # Port open but the board has gone quiet. Showing the last known
        # number without flagging it would be worse than showing nothing.
        exp.temp_readout_var.set(status.temp_text())
        exp.temp_state_var.set("no data")
        exp.temp_state_label.config(foreground="#b26a00")
    else:
        exp.temp_readout_var.set(status.temp_text())
        exp.temp_state_var.set(status.state.title())
        exp.temp_state_label.config(
            foreground=STATE_COLOURS.get(status.state, "#555555"))

    exp.temp_sp_var.set(
        "SP --" if status.setpoint_c is None else f"SP {status.setpoint_c:.1f} °C")
