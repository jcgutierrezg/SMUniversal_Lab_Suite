"""
Connection panel - one row per role the experiment declares.

A single-SMU experiment gets one row; the dual-SMU IV setup will get two
from the same code, because the rows are generated from
experiment.ROLES rather than hardcoded.

Each row is: transport type, address (with a Refresh that asks the
transport what's available), Connect/Disconnect, and a status label that
shows the detected model once identified.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from core.transports.minismu_transport import MiniSMUTransport
from core.transports.ni_gpib_usb_hs_transport import NIUSBGPIBTransport
from core.transports.null_transport import NullTransport
from core.transports.serial_transport import SerialTransport

# The registry is reached through `app.registry` rather than imported,
# so the one-way dependency rule holds for core/gui/ too and a test can
# hand the app a registry holding a single fake driver. Wave 1.
from core.transports.visa_transport import VisaPyTransport, VisaTransport

# SMUs go over VISA; raw serial stays available for non-VISA devices and
# as a fallback when a VISA layer isn't cooperating. Demo needs no
# hardware at all - it resolves to the simulated DummySMU driver through
# the same *IDN? path as everything else.
DEFAULT_TRANSPORT = "VISA"

TRANSPORTS = {
    "VISA": VisaTransport,
    # Same class, pinned to pyvisa-py. Worth its own entry because a
    # vendor backend that opens an instrument and then misbehaves is
    # not something the merged listing can rescue - see the U2722A note
    # in core/transports/visa_transport.py.
    "VISA (pyvisa-py)": VisaPyTransport,
    # A deliberately separate hardware stack. Never a fallback from VISA:
    # selecting it opts into direct PyUSB/libusb control of GPIB-USB-HS.
    "NI GPIB-HS": NIUSBGPIBTransport,
    "Serial": SerialTransport,
    # Not a text transport: it wraps the vendor's Python library. See
    # core/transports/minismu_transport.py for why.
    #
    # It has to be picked deliberately, and the driver refuses anything
    # else: the MS01 answers *IDN? over plain serial, so choosing
    # "Serial" here connects fine and auto-detects correctly, then hands
    # the driver a transport it cannot drive.
    "miniSMU": MiniSMUTransport,
    "Demo": NullTransport,
}


def build_connection_panel(app, parent):
    """Build a connection row for every role in app.experiment.ROLES.
    Stores per-role widgets in app.conn_widgets."""
    frame = ttk.LabelFrame(parent, text="Instruments", padding=8)
    frame.grid(row=0, column=0, sticky="ew")
    frame.grid_columnconfigure(2, weight=1)

    app.conn_widgets = {}

    roles = app.experiment.ROLES or {"source": "SMU"}
    for row, (role, description) in enumerate(roles.items()):
        _build_row(app, frame, row, role, description)


def _build_row(app, frame, row, role, description):
    """One role's worth of connection controls."""
    ttk.Label(frame, text=f"{description}:").grid(row=row, column=0, sticky="w", pady=2)

    transport_var = tk.StringVar(value=DEFAULT_TRANSPORT)
    transport_combo = ttk.Combobox(
        frame, textvariable=transport_var, values=list(TRANSPORTS),
        state="readonly", width=11)
    transport_combo.grid(row=row, column=1, padx=(6, 6))

    address_var = tk.StringVar(value="")
    address_combo = ttk.Combobox(frame, textvariable=address_var, width=34)
    address_combo.grid(row=row, column=2, sticky="ew", padx=(0, 6))

    status = ttk.Label(frame, text="Not connected", foreground="red", width=28)
    status.grid(row=row, column=5, sticky="w", padx=(8, 0))

    widgets = {
        "transport_var": transport_var,
        "transport_combo": transport_combo,
        "address_var": address_var,
        "address_combo": address_combo,
        "status": status,
    }
    app.conn_widgets[role] = widgets

    ttk.Button(frame, text="Refresh", width=8,
               command=lambda: _refresh(app, role)).grid(row=row, column=3, padx=(0, 4))

    connect_btn = ttk.Button(frame, text="Connect", width=10,
                             command=lambda: _connect(app, role))
    connect_btn.grid(row=row, column=4)
    widgets["connect_btn"] = connect_btn

    # Changing transport is an explicit opt-in point. Clear an address
    # discovered by the previous transport before probing the newly chosen
    # one; in particular this is the only automatic path that probes the
    # direct GPIB-USB-HS backend.
    transport_combo.bind(
        "<<ComboboxSelected>>",
        lambda _event: _transport_changed(app, role),
    )

    # populate the address dropdown immediately so the user sees what's
    # plugged in without having to ask
    _refresh(app, role)


def _transport_changed(app, role):
    """Forget stale discovery state, then scan only the chosen transport."""
    w = app.conn_widgets[role]
    w["address_var"].set("")
    w["address_combo"]["values"] = ()
    _refresh(app, role)


def _refresh(app, role):
    """Ask the selected transport what addresses are available."""
    w = app.conn_widgets[role]
    transport_cls = TRANSPORTS[w["transport_var"].get()]
    found = transport_cls.list_available()
    choices = found
    choice_provider = getattr(transport_cls, "address_choices", None)
    if choice_provider is not None:
        choices = choice_provider()
    w["address_combo"]["values"] = choices
    if found and not w["address_var"].get():
        w["address_var"].set(found[0])
    app.log(f"[{role}] {len(found)} address(es) available")

    # Break the count down per backend. An empty dropdown has several
    # very different causes - no vendor library, pyvisa-py without
    # pyusb, an instrument enumerating as ::RAW - and they are
    # indistinguishable from the count alone. Only VISA transports have
    # more than one backend to report on.
    summary = getattr(transport_cls, "scan_summary", None)
    if summary is not None:
        for line in summary():
            app.log(f"[{role}]   {line}")


def _connect(app, role):
    """Connect, auto-detect the model, and update the row. Runs on a
    background thread - VISA connection can block for seconds."""
    w = app.conn_widgets[role]
    address = w["address_var"].get().strip()
    is_demo = w["transport_var"].get() == "Demo"
    if not address and not is_demo:
        messagebox.showwarning("No address", "Pick or type an instrument address first.")
        return

    if app.is_connected(role):
        app.disconnect_role(role)
        w["status"].config(text="Not connected", foreground="red")
        w["connect_btn"].config(text="Connect")
        app.log(f"[{role}] disconnected")
        return

    transport_cls = TRANSPORTS[w["transport_var"].get()]
    w["connect_btn"].config(state="disabled")
    app.log(f"[{role}] connecting to {address} ...")

    def task():
        try:
            driver = app.connect_role(role, transport_cls(), address)
            app.ui(w["status"].config,
                   text=driver.DISPLAY_NAME, foreground="green")
            app.ui(w["connect_btn"].config, text="Disconnect")
        except app.registry.UnknownInstrumentError as e:
            # instrument answered but nothing claims it - offer the
            # manual driver list rather than dead-ending
            app.log(f"[{role}] unrecognised instrument")
            app.ui(_offer_fallback, app, role, transport_cls, address, str(e),
                   "Unrecognised instrument")
        except Exception as e:
            # nothing answered at all: wrong address, cable out, VISA
            # backend missing. Demo mode is usually what you want here.
            app.log(f"[{role}] connection failed:", e)
            app.ui(_offer_fallback, app, role, transport_cls, address,
                   f"Could not connect to {address}.\n\n{e}",
                   "Connection failed")
        finally:
            app.ui(w["connect_btn"].config, state="normal")

    app.run_in_background(task)


def _offer_fallback(app, role, transport_cls, address, message, title):
    """Shown when a connection attempt doesn't yield a usable driver -
    either nothing answered, or something answered that no driver claims.

    Offers two ways forward instead of a dead end:
      - pick a driver by hand, if you know what's on the other end
      - run against the simulated sample, for developing with no hardware
    """
    w = app.conn_widgets[role]
    win = tk.Toplevel(app.root)
    win.title(title)
    win.transient(app.root)
    win.grab_set()

    ttk.Label(win, text=message, wraplength=430, justify="left").pack(
        padx=14, pady=(14, 10))
    ttk.Separator(win, orient="horizontal").pack(fill="x", padx=14)

    # --- option 1: demo ---
    demo_box = ttk.Frame(win)
    demo_box.pack(fill="x", padx=14, pady=(10, 4))
    ttk.Label(demo_box,
              text="Run a simulated instrument instead?",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    ttk.Label(demo_box, wraplength=430, justify="left", foreground="#555",
              text="Demo mode drives a simulated resistive sample. Every "
                   "part of the app works normally - only the hardware is "
                   "absent.").pack(anchor="w", pady=(2, 0))

    def use_demo():
        win.destroy()
        w["transport_var"].set("Demo")
        w["address_var"].set("<simulated sample>")
        _connect_with(app, role, NullTransport, "<simulated sample>", demo=True)

    ttk.Button(demo_box, text="Run demo instead",
               command=use_demo).pack(anchor="w", pady=(8, 0))

    ttk.Separator(win, orient="horizontal").pack(fill="x", padx=14, pady=(10, 0))

    # --- option 2: manual driver ---
    manual_box = ttk.Frame(win)
    manual_box.pack(fill="x", padx=14, pady=(10, 4))
    ttk.Label(manual_box, text="Or choose a driver manually:",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    names = [n for n in app.registry.all_driver_names()
             if "simulated" not in n.lower()]
    choice = tk.StringVar(value=names[0] if names else "")
    row = ttk.Frame(manual_box)
    row.pack(anchor="w", pady=(6, 0))
    ttk.Combobox(row, textvariable=choice, state="readonly", width=26,
                 values=names).pack(side="left", padx=(0, 6))

    def use_manual():
        driver_cls = app.registry.driver_by_display_name(choice.get())
        win.destroy()
        _connect_with(app, role, transport_cls, address,
                      driver_cls=driver_cls)

    ttk.Button(row, text="Use this driver", command=use_manual).pack(side="left")

    ttk.Button(win, text="Cancel", command=win.destroy).pack(pady=(12, 12))


def _connect_with(app, role, transport_cls, address, driver_cls=None, demo=False):
    """Shared connect-and-update helper for the fallback paths.

    With `driver_cls` given the driver is forced; otherwise normal
    *IDN? detection runs, which is what demo mode relies on (NullTransport
    identifies as the dummy, so it resolves through the usual route).
    """
    w = app.conn_widgets[role]

    def task():
        try:
            if driver_cls is None:
                driver = app.connect_role(role, transport_cls(), address)
            else:
                driver = app.connect_role_manual(role, transport_cls(),
                                                 address, driver_cls)
            if demo:
                label, colour = "DEMO - simulated", "#b26a00"
                app.log("Running in demo mode - readings are simulated, "
                        "not measured.")
            elif driver_cls is not None:
                label, colour = f"{driver.DISPLAY_NAME} (manual)", "orange"
            else:
                label, colour = driver.DISPLAY_NAME, "green"
            app.ui(w["status"].config, text=label, foreground=colour)
            app.ui(w["connect_btn"].config, text="Disconnect")
        except Exception as e:
            app.log(f"[{role}] connection failed:", e)
            app.ui(messagebox.showerror, "Connection failed", str(e))

    app.run_in_background(task)
