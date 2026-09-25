"""
The plotter window.

Three columns, the same landscape arrangement every window in the suite
uses (house rule 1): the open files and their runs on the left, the plot
in the middle, and what the selection is on the right.

    +-------------+------------------------------+----------------+
    | files       |  view  [options]             | Details        |
    |  runs  [x]  |                              | Compare        |
    |  runs  [ ]  |        figure                | Data           |
    |             |                              |                |
    |             |  toolbar            notes    |                |
    +-------------+------------------------------+----------------+

Ticking a run puts it on the plot; selecting a row puts it in the
details. The two are deliberately separate: comparing three runs while
reading the settings of a fourth is an ordinary thing to want.

Nothing here writes a file unless asked. "Save figure...", "Export
data..." and "Save table..." are the only outputs, and each asks
where (house rule 3).

It never opens an instrument, so it does not take the single-instance
lock: data can be looked at while a measurement window is running. See
`core/launcher.py`.
"""
from __future__ import annotations

import glob
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("Agg")            # no separate GUI backend; Tk hosts the canvas

import numpy as np
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure

from smuniversal_lab_suite.core.gui.app_icon import apply_window_icon
from smuniversal_lab_suite.core.gui.theme import (
    blend,
    set_dark_title_bar,
    theme_for,
)
from smuniversal_lab_suite.core.gui.tooltips import Tooltips
from smuniversal_lab_suite.plotter import (
    describe,
    detect,
    export,
    style,
    views,
)
from smuniversal_lab_suite.plotter.reader import UnreadableFile, load
from smuniversal_lab_suite.plotter.session import Session

TITLE = "CSV plotter - SMUniversal Lab Suite"
UNTICKED = "☐"
TICKED = "☑"
#: The pointer must be this close to a point, in pixels, for the hover
#: label to name it. About half the 24 px minimum hit target.
HOVER_RADIUS_PX = 12
#: Rows put into the Data tab. A long Fixed source run can hold tens of
#: thousands of readings; a table that long is not read, it is scrolled
#: past, and filling it costs seconds.
DATA_ROW_LIMIT = 2000

#: The one per-run value worth seeing in the file list, by experiment.
HEADLINE = {
    detect.IV_SWEEP.key: ("resistance_ohm", "Ω"),
    detect.FIXED_SOURCE.key: ("interval_achieved_s", "s"),
    detect.OSSILA_4PP.key: ("sheet_resistance_ohm_sq", "Ω/□"),
    detect.VAN_DER_PAUW.key: ("R_ave_ohm", "Ω"),
    detect.HALL.key: ("V_plus_V", "V"),
}


class PlotterWindow:
    def __init__(self, root, paths=()):
        self.root = root
        self.session = Session()
        self._file_items: dict[str, object] = {}
        self._run_items: dict[str, tuple] = {}
        self._focus = None               # (file, run or None)
        self._view_for_kinds: dict[frozenset, str] = {}
        self._option_vars: dict[tuple[str, str], tk.BooleanVar] = {}
        #: (view, choice) -> the value in force. A value, not a Tk
        #: variable: the list it is chosen from is rebuilt on every
        #: redraw, from whatever runs are ticked.
        self._choices: dict[tuple[str, str], str | None] = {}
        self._current_views: list[views.View] = []
        self._hover = None

        root.title(TITLE)
        width = min(1440, root.winfo_screenwidth() - 60)
        height = min(880, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(980, 600)

        # Hover help, as in every measurement window. Always on here:
        # the plotter has no console strip to hold the switch, and a
        # tooltip waits for the pointer to rest, so it stays out of the
        # way of anyone who knows the window.
        self.tooltips = Tooltips(root)

        self._build()
        if paths:
            self.open_paths(list(paths))
        self.refresh()

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _tip(self, widget, text, name=None):
        """Hover help on `widget`; returns it, so a build line can pack."""
        return self.tooltips.attach(widget, text, name=name)

    def _build(self):
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(fill="x")
        self._tip(ttk.Button(bar, text="Open files...",
                             command=self.ask_files),
                  "Choose saved CSV files to open. Files from any window "
                  "can be open together; the first file's runs are "
                  "plotted straight away.").pack(side="left")
        self._tip(ttk.Button(bar, text="Open folder...",
                             command=self.ask_folder),
                  "Open every CSV in a folder at once - a day's work, "
                  "for example.").pack(side="left", padx=(6, 0))
        self._tip(ttk.Button(bar, text="Close file",
                             command=self.close_selected_file),
                  "Close the file selected in the list. The file on disk "
                  "is not touched.").pack(side="left", padx=(6, 0))
        self._tip(ttk.Button(bar, text="Close all",
                             command=self.close_all),
                  "Close every open file. Nothing on disk is "
                  "touched.").pack(side="left", padx=(6, 0))
        self._tip(ttk.Button(bar, text="Reload", command=self.reload),
                  "Read the open files again, and open any newer saves of "
                  "them. A session still measuring saves a new numbered "
                  "file each time, so this keeps up with it.").pack(
                      side="left", padx=(18, 0))
        self._tip(ttk.Button(bar, text="Save figure...",
                             command=self.save_figure),
                  "Save the plot as an image. It asks where; nothing is "
                  "written otherwise.").pack(side="right")
        # The one control here that is about the window rather than the
        # data. Its label is the mode it switches *to*.
        self.mode_btn = ttk.Button(
            bar, width=7, command=lambda: theme_for(self.root).toggle())
        self._tip(self.mode_btn,
                  "Switch between the dark and light look. The plot stays "
                  "on white paper either way, as it will be saved.",
                  name="Light / Dark")
        self.mode_btn.pack(side="right", padx=(18, 12))
        self._tip(ttk.Button(bar, text="Export data...",
                             command=self.export_data),
                  "Write the ticked runs' readings to one CSV, for a "
                  "spreadsheet or another program. It asks where; the "
                  "measurement files are never overwritten.").pack(
                      side="right", padx=(0, 6))

        panes = self.panes = tk.PanedWindow(self.root, orient="horizontal",
                                            sashwidth=6, sashrelief="flat")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        left = ttk.Frame(panes)
        centre = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, minsize=260, width=380)
        panes.add(centre, minsize=420, stretch="always")
        # Wider than the file list: the Compare tab puts a column per
        # ticked run side by side, and at 380 the second was cut off.
        panes.add(right, minsize=260, width=440)

        self._build_file_list(left)
        self._build_plot(centre)
        self._build_details(right)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 2),
                  style="Hint.TLabel").pack(fill="x")

        # The chrome follows the theme; the figures do not - see
        # `_repaint`.
        theme_for(self.root).on_change(self._repaint, widget=self.root)

    def _repaint(self, theme):
        """Follow a mode switch.

        The figures are deliberately left on paper. They are the
        plotter's output - what gets saved and put in a report - and
        the palette they use was checked for colour vision on that
        ground, so a dark copy would be a palette nobody has validated.
        """
        palette = theme.palette
        self.panes.configure(background=palette.rule)
        self.details.configure(background=palette.field,
                               foreground=palette.ink,
                               insertbackground=palette.ink)
        self.details.tag_configure("label", foreground=palette.ink2)
        self.tree.tag_configure("unreadable", foreground=palette.muted)
        self.compare_tree.tag_configure(
            "differs", background=blend(theme.accent, palette.field, 0.78))
        self.mode_btn.configure(text="Light" if theme.is_dark else "Dark")
        set_dark_title_bar(self.root, theme.is_dark)

    def _build_file_list(self, parent):
        frame = ttk.LabelFrame(parent, text="Files and runs", padding=6)
        frame.pack(fill="both", expand=True)
        self._tip(frame, "Every open file, and the runs inside it. The box "
                  "beside a run puts it on the plot; selecting a row shows "
                  "its settings in Details and its readings in Data.")
        ttk.Label(frame, text="Click a box to plot the run; select a row "
                  "to read it.", style="Hint.TLabel",
                  wraplength=280).grid(row=2, column=0, columnspan=2,
                                       sticky="w", pady=(4, 0))

        self.tree = ttk.Treeview(frame, columns=("points", "headline"),
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="File / run")
        self.tree.heading("points", text="Points")
        self.tree.heading("headline", text="Key value")
        self.tree.column("#0", width=170, stretch=True)
        self.tree.column("points", width=64, anchor="e", stretch=False)
        self.tree.column("headline", width=116, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("file", font="SMUBold")
        self._tip(self.tree,
                  "Click a run's box, or press Space, to plot it; click a "
                  "row to read it. Points is how many readings the run "
                  "has; Key value is its headline result - a resistance, "
                  "a sheet resistance.", name="File list")

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<space>", self._on_tree_space)

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew",
                     pady=(6, 0))
        self._tip(ttk.Button(buttons, text="Tick file's runs",
                             command=self.tick_selected_file),
                  "Plot every run in the selected file.").pack(side="left")
        self._tip(ttk.Button(buttons, text="Untick all",
                             command=self.untick_all),
                  "Take every run off the plot.").pack(side="left",
                                                        padx=(6, 0))

    def _build_plot(self, parent):
        frame = ttk.LabelFrame(parent, text="Plot", padding=6)
        frame.pack(fill="both", expand=True, padx=6)
        self._tip(frame, "The ticked runs, drawn in the chosen view. Notes "
                  "under the plot say what was left out of it, and why.")

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        view_help = ("How the ticked runs are drawn. Only views that suit "
                     "every ticked run are offered, and the line under it "
                     "says what the view shows.")
        self._tip(ttk.Label(controls, text="View:"),
                  view_help).pack(side="left")
        self.view_var = tk.StringVar()
        self.view_combo = ttk.Combobox(controls, textvariable=self.view_var,
                                       state="readonly", width=28)
        self._tip(self.view_combo, view_help)
        self.view_combo.pack(side="left", padx=(4, 10))
        self.view_combo.bind("<<ComboboxSelected>>", self._on_view_chosen)
        self.view_help_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.view_help_var,
                  style="Hint.TLabel").pack(fill="x", pady=(2, 0))

        # A row of their own: a view with two drop-downs and a checkbox
        # does not fit beside the view list on a laptop screen, and a
        # control pushed off the edge of a frame is simply not there.
        self.options_frame = ttk.Frame(frame)
        self.options_frame.pack(fill="x", pady=(4, 4))

        # The notes and the toolbar are packed before the canvas, from
        # the bottom: pack hands out space in order, so a canvas packed
        # first with expand=True leaves them nothing on a short window.
        self.notes_var = tk.StringVar()
        self.notes_label = ttk.Label(frame, textvariable=self.notes_var,
                                     style="Hint.TLabel",
                                     justify="left", wraplength=600)
        self.notes_label.pack(side="bottom", fill="x", pady=(4, 0))

        self.figure = Figure(figsize=(7, 5), dpi=100,
                             facecolor=style.SURFACE)
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        toolbar_frame = ttk.Frame(frame)
        toolbar_frame.pack(side="bottom", fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame,
                                            pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="left", fill="x")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._tip(self.canvas.get_tk_widget(),
                  "Rest the pointer near a point to read its values. Zoom "
                  "and pan with the toolbar below; its home button puts "
                  "the view back.", name="Plot")
        frame.bind("<Configure>", lambda e: self.notes_label.configure(
            wraplength=max(200, e.width - 20)))

    def _build_details(self, parent):
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill="both", expand=True)
        self._tip(self.tabs, "Details: everything recorded about the "
                  "selected run. Compare: the ticked runs' settings side "
                  "by side. Data: the selected run's readings.",
                  name="Tabs")

        details = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(details, text="Details")
        self.details = tk.Text(details, wrap="word", borderwidth=0,
                               highlightthickness=0, padx=6, pady=6,
                               font="TkDefaultFont")
        scroll = ttk.Scrollbar(details, orient="vertical",
                               command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.details.tag_configure("heading", font="SMUHeading",
                                   spacing1=8, spacing3=2)
        # Flagged lines carry a symbol and bold ink rather than a status
        # colour alone, so they read the same in greyscale.
        self.details.tag_configure("flag", font="SMUBold")
        self.details.configure(state="disabled")
        self._tip(self.details, "Everything recorded about the selected "
                  "run: the settings it was taken with, its results, and "
                  "anything flagged about it.", name="Details")

        compare = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(compare, text="Compare")
        # Two rows, not one: the checkbox and both buttons side by side
        # need more than the pane's default width, and the last button
        # was cut to "Cop" there.
        top = ttk.Frame(compare)
        top.pack(fill="x")
        actions = ttk.Frame(compare)
        actions.pack(fill="x", pady=(4, 0))
        self.only_differences_var = tk.BooleanVar(value=False)
        self._tip(ttk.Checkbutton(top, text="Only settings that differ",
                                  variable=self.only_differences_var,
                                  command=self.refresh_compare),
                  "Hide the settings every ticked run shares, leaving the "
                  "ones that could explain a difference between "
                  "them.").pack(side="left")
        self._tip(ttk.Button(actions, text="Copy table",
                             command=self.copy_compare_table),
                  "Copy the comparison to the clipboard, ready to paste "
                  "into a spreadsheet.").pack(side="left")
        self._tip(ttk.Button(actions, text="Save table...",
                             command=self.save_compare_table),
                  "Save the comparison as a CSV. It asks "
                  "where.").pack(side="left", padx=(6, 0))
        self.compare_tree = self._scrolled_tree(compare)
        self._tip(self.compare_tree,
                  "The ticked runs' settings side by side, one column per "
                  "run. A setting that differs between them is marked ≠ "
                  "and shaded.", name="Comparison table")

        data = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(data, text="Data")
        self.data_title_var = tk.StringVar(value="Select a run.")
        ttk.Label(data, textvariable=self.data_title_var,
                  style="Hint.TLabel").pack(fill="x")
        self.data_tree = self._scrolled_tree(data)
        self._tip(self.data_tree,
                  f"The selected run's readings - the first "
                  f"{DATA_ROW_LIMIT} rows. Every row is in the file, and "
                  f"in Export data.", name="Readings table")

    @staticmethod
    def _scrolled_tree(parent):
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True, pady=(4, 0))
        tree = ttk.Treeview(holder, show="headings")
        ys = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        return tree

    # ------------------------------------------------------------------
    # opening and closing files
    # ------------------------------------------------------------------
    def ask_files(self):
        paths = filedialog.askopenfilenames(
            parent=self.root, title="Open saved CSV files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if paths:
            self.open_paths(list(paths))

    def ask_folder(self):
        folder = filedialog.askdirectory(parent=self.root,
                                         title="Open every CSV in a folder")
        if folder:
            self.open_paths(sorted(glob.glob(os.path.join(folder, "*.csv"))))

    def open_paths(self, paths):
        """Open each path; report the ones that could not be read."""
        was_empty = not self.session.ticked_series()
        opened = []
        refused = []
        for path in paths:
            try:
                stored = load(path)
            except (UnreadableFile, OSError, UnicodeDecodeError) as exc:
                refused.append(f"{os.path.basename(path)}: {exc}")
                continue
            if self.session.add(stored):
                opened.append(stored)

        if was_empty:
            # Something on the plot straight away: the first opened
            # file's runs, up to the eight that keep their own colours.
            for stored in opened:
                runs = self.session.runs_of(stored)
                if runs:
                    for run in runs[:len(style.CATEGORICAL)]:
                        self.session.tick(run.record_id)
                    break

        if opened:
            self._focus = (opened[0], None)
        self.refresh()
        if refused:
            self.status_var.set(
                f"Opened {len(opened)} file(s); {len(refused)} could not "
                f"be read.")
        if refused:
            shown = refused[:10]
            more = len(refused) - len(shown)
            messagebox.showwarning(
                "Some files were not opened",
                "\n\n".join(shown)
                + (f"\n\n...and {more} more." if more else ""),
                parent=self.root)
        return opened

    def close_selected_file(self):
        stored = self._selected_file()
        if stored is None:
            return
        self.session.remove(stored)
        if self._focus and self._focus[0] is stored:
            self._focus = None
        self.refresh()

    def close_all(self):
        self.session.clear()
        self._focus = None
        self.refresh()

    def reload(self):
        """Re-read the open files, and open later saves of them.

        A measurement session saves again and again under one sample
        name, each Save a new `_N` file; without this the plotter shows
        whatever existed when it was opened.
        """
        focus = None
        if self._focus is not None:
            stored, run = self._focus
            focus = (stored.path, run.record_id if run else None)

        new_files, problems = self.session.reload(load)

        self._focus = None
        if focus is not None:
            path, record_id = focus
            for stored in self.session.files:
                if stored.path != path:
                    continue
                run = next((r for r in stored.runs
                            if r.record_id == record_id), None)
                self._focus = (stored, run)
        self.refresh()
        self.status_var.set(
            f"Reloaded {len(self.session.files) - len(new_files)} file(s)"
            + (f", opened {len(new_files)} newer save(s): "
               + ", ".join(os.path.basename(f.path) for f in new_files)
               if new_files else ", no newer saves")
            + (f"; {len(problems)} problem(s)" if problems else "") + ".")
        if problems:
            messagebox.showwarning("Reload", "\n\n".join(problems[:10]),
                                   parent=self.root)

    # ------------------------------------------------------------------
    # exports - written only where asked (house rule 3)
    # ------------------------------------------------------------------
    def export_data(self):
        series = self.session.ticked_series()
        if not series:
            messagebox.showinfo("Nothing to export",
                                "Tick runs to export their readings.",
                                parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export the ticked runs' readings",
            defaultextension=".csv",
            initialfile=self._figure_name().replace(".png", "_data.csv"),
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        text = export.build_readings_csv(series, self.view_var.get())
        if self._write(path, text):
            self.status_var.set(f"Exported {len(series)} run(s) to {path}")

    def copy_compare_table(self):
        series = self.session.ticked_series()
        if not series:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(export.build_compare_table(
            series, "\t", self.only_differences_var.get()))
        self.status_var.set(f"Copied the settings of {len(series)} run(s) "
                            f"- paste into a spreadsheet.")

    def save_compare_table(self):
        series = self.session.ticked_series()
        if not series:
            messagebox.showinfo("Nothing to save",
                                "Tick runs to compare their settings.",
                                parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save the settings table",
            defaultextension=".csv",
            initialfile=self._figure_name().replace(".png", "_settings.csv"),
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        text = export.build_compare_table(
            series, ",", self.only_differences_var.get())
        if self._write(path, text):
            self.status_var.set(f"Saved the settings table to {path}")

    def _write(self, path, text):
        # A path that is an open file refuses to become an export: a
        # plotter export has no `schema` line and could not be opened
        # again in place of the measurement it overwrote.
        if any(os.path.normcase(os.path.abspath(path))
               == os.path.normcase(os.path.abspath(f.path))
               for f in self.session.files):
            messagebox.showerror(
                "Not saved",
                "That is one of the open data files. An export cannot "
                "replace a saved measurement - choose another name.",
                parent=self.root)
            return False
        try:
            export.write_text(path, text)
        except OSError as exc:
            messagebox.showerror("Not saved", str(exc), parent=self.root)
            return False
        return True

    # ------------------------------------------------------------------
    # the file list
    # ------------------------------------------------------------------
    def _selected_file(self):
        selection = self.tree.selection()
        if not selection:
            return None
        item = selection[0]
        if item in self._file_items:
            return self._file_items[item]
        if item in self._run_items:
            return self._run_items[item][0]
        return None

    def _rebuild_tree(self):
        open_state = {id(self._file_items[i]): self.tree.item(i, "open")
                      for i in self._file_items}
        selected = self.tree.selection()
        selected_key = None
        if selected:
            item = selected[0]
            if item in self._file_items:
                selected_key = ("file", id(self._file_items[item]))
            elif item in self._run_items:
                selected_key = ("run", self._run_items[item][1].record_id)

        self.tree.delete(*self.tree.get_children())
        self._file_items.clear()
        self._run_items.clear()
        reselect = None
        for number, stored in enumerate(self.session.files):
            runs = self.session.runs_of(stored)
            duplicates = self.session.duplicates_in(stored)
            text = os.path.basename(stored.path)
            count = "table" if stored.is_summary else f"{len(runs)} runs"
            if duplicates:
                count += f" (+{duplicates} shown elsewhere)"
            file_item = self.tree.insert(
                "", "end", iid=f"file{number}", text=text,
                values=(count, stored.kind.name), tags=("file",),
                open=open_state.get(id(stored), True))
            self._file_items[file_item] = stored
            if selected_key == ("file", id(stored)):
                reselect = file_item
            key, unit = HEADLINE.get(stored.kind.key, ("", ""))
            for index, run in enumerate(runs):
                mark = TICKED if self.session.is_ticked(run.record_id) \
                    else UNTICKED
                headline = describe.eng(run.number(key), unit, 4) \
                    if key else ""
                item = self.tree.insert(
                    file_item, "end", iid=f"file{number}run{index}",
                    text=f"{mark} {run.label}",
                    values=(len(run), headline))
                self._run_items[item] = (stored, run)
                if selected_key == ("run", run.record_id):
                    reselect = item
        if reselect is not None:
            self.tree.selection_set(reselect)
            self.tree.see(reselect)

    def _on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        if item not in self._run_items:
            return
        # Only a click on the box itself toggles; a click on the name
        # selects, so reading a run's details does not plot it.
        if self.tree.identify_column(event.x) != "#0":
            return
        x, _y, _w, _h = self.tree.bbox(item, "#0") or (0, 0, 0, 0)
        depth_indent = 20 * 2
        if event.x - x > depth_indent + 16:
            return
        self._toggle(item)

    def _on_tree_space(self, _event):
        selection = self.tree.selection()
        if selection and selection[0] in self._run_items:
            self._toggle(selection[0])
        return "break"

    def _toggle(self, item):
        _stored, run = self._run_items[item]
        self.session.toggle(run.record_id)
        self.refresh()

    def _on_tree_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        if item in self._file_items:
            self._focus = (self._file_items[item], None)
        elif item in self._run_items:
            self._focus = self._run_items[item]
        self.refresh_details()
        self.refresh_data()

    def tick_selected_file(self):
        stored = self._selected_file()
        if stored is None:
            return
        for run in self.session.runs_of(stored):
            self.session.tick(run.record_id)
        self.refresh()

    def untick_all(self):
        for series in self.session.ticked_series():
            self.session.untick(series.run.record_id)
        self.refresh()

    # ------------------------------------------------------------------
    # the plot
    # ------------------------------------------------------------------
    def refresh(self):
        """Redraw everything from the session. Cheap enough to call on
        every change, and a pure function of the session, so the list,
        the plot and the details cannot drift apart."""
        self._rebuild_tree()
        self.refresh_plot()
        self.refresh_details()
        self.refresh_compare()
        self.refresh_data()
        files = len(self.session.files)
        runs = len(self.session.visible_runs())
        ticked = len(self.session.ticked_series())
        self.status_var.set(f"{files} file(s), {runs} run(s), "
                            f"{ticked} plotted.")

    def _chosen_view(self, series):
        available = views.views_for(series)
        self._current_views = available
        if not available:
            return None
        kinds = frozenset(s.file.kind.key for s in series)
        wanted = self._view_for_kinds.get(kinds)
        for view in available:
            if view.key == wanted:
                return view
        return available[0]

    def refresh_plot(self):
        series = self.session.ticked_series()
        view = self._chosen_view(series)
        self.view_combo.configure(
            values=[v.title for v in self._current_views])
        self.view_var.set(view.title if view else "")
        self.view_help_var.set(view.description if view else "")
        self._build_options(view, series)

        options = {}
        if view is not None:
            options = {o.key: self._option_var(view, o).get()
                       for o in view.options}
            options.update({c.key: self._choices.get((view.key, c.key))
                            for c in view.choices})
        self._hover = None
        notes = views.render(self.figure, view, series, options)
        self.notes_var.set("\n".join(notes))
        self.canvas.draw_idle()

    def _option_var(self, view, option):
        key = (view.key, option.key)
        if key not in self._option_vars:
            self._option_vars[key] = tk.BooleanVar(value=option.default)
        return self._option_vars[key]

    def _build_options(self, view, series):
        for child in self.options_frame.winfo_children():
            child.destroy()
        if view is None:
            return
        for choice in view.choices:
            values, current = views.choice_values(
                view, choice, series, self._choices.get((view.key,
                                                         choice.key)))
            self._choices[(view.key, choice.key)] = current
            labels = [label for _value, label in values]
            by_label = dict((label, value) for value, label in values)
            ttk.Label(self.options_frame,
                      text=f"{choice.label}:").pack(side="left")
            var = tk.StringVar(value=dict(values).get(current, ""))
            combo = ttk.Combobox(self.options_frame, textvariable=var,
                                 values=labels, state="readonly",
                                 width=max(12, min(28, max(
                                     (len(label) for label in labels),
                                     default=12))))
            combo.pack(side="left", padx=(4, 10))
            self._tip(combo, f"{choice.label}, for this view. The list "
                      "offers only what the ticked runs hold; changing it "
                      "redraws the plot.")

            def chosen(_event=None, key=(view.key, choice.key), var=var,
                       by_label=by_label):
                self._choices[key] = by_label.get(var.get())
                self.refresh_plot()

            combo.bind("<<ComboboxSelected>>", chosen)
        for option in view.options:
            self._tip(ttk.Checkbutton(self.options_frame, text=option.label,
                                      variable=self._option_var(view,
                                                                option),
                                      command=self.refresh_plot),
                      f"{option.label}, on this view. Changing it redraws "
                      "the plot.").pack(side="left", padx=(0, 8))

    def _on_view_chosen(self, _event=None):
        title = self.view_var.get()
        series = self.session.ticked_series()
        for view in self._current_views:
            if view.title == title:
                kinds = frozenset(s.file.kind.key for s in series)
                self._view_for_kinds[kinds] = view.key
        self.refresh_plot()

    def _on_hover(self, event):
        """Name the nearest point under the pointer.

        Hover adds to the plot and never gates a value: every number is
        also in the Data tab and the toolbar's readout.
        """
        ax = event.inaxes
        best = None
        if ax is not None and event.x is not None:
            for line in ax.get_lines():
                label = line.get_gid()
                if not label:
                    continue
                data = np.asarray(line.get_xydata(), dtype=float)
                if not len(data):
                    continue
                pixels = ax.transData.transform(data)
                distance = np.hypot(pixels[:, 0] - event.x,
                                    pixels[:, 1] - event.y)
                distance[~np.isfinite(distance)] = np.inf
                index = int(np.argmin(distance))
                if distance[index] <= HOVER_RADIUS_PX and (
                        best is None or distance[index] < best[0]):
                    best = (distance[index], label, data[index])

        if self._hover is not None and (best is None
                                        or self._hover.axes is not ax):
            self._hover.remove()
            self._hover = None
            self.canvas.draw_idle()
        if best is None:
            return
        _distance, label, (x, y) = best
        text = f"{label}\n{ax.format_xdata(x)},  {ax.format_ydata(y)}"
        if self._hover is None:
            self._hover = ax.annotate(
                text, xy=(x, y), xytext=(12, 12),
                textcoords="offset points", fontsize=8, color=style.INK,
                bbox={"boxstyle": "round,pad=0.4",
                      "facecolor": style.SURFACE, "edgecolor": style.AXIS,
                      "linewidth": 0.75},
                zorder=10)
        else:
            self._hover.xy = (x, y)
            self._hover.set_text(text)
        self.canvas.draw_idle()

    def save_figure(self):
        if not self.session.ticked_series():
            messagebox.showinfo("Nothing to save",
                                "Tick runs to plot before saving a figure.",
                                parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save figure",
            defaultextension=".png",
            initialfile=self._figure_name(),
            filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"),
                       ("PDF document", "*.pdf")])
        if not path:
            return
        if self._hover is not None:
            self._hover.remove()
            self._hover = None
        try:
            self.figure.savefig(path, dpi=200, facecolor=style.SURFACE)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Figure not saved", str(exc),
                                 parent=self.root)
            return
        self.status_var.set(f"Saved figure to {path}")

    def _figure_name(self):
        series = self.session.ticked_series()
        samples = []
        for s in series:
            sample = s.run.text("sample_label") or s.file.sample
            if sample and sample not in samples:
                samples.append(sample)
        view = self.view_var.get() or "plot"
        stem = "_".join(samples[:3]) or "plot"
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in f"{stem}_{view}")
        return f"{safe}.png"

    # ------------------------------------------------------------------
    # the right-hand tabs
    # ------------------------------------------------------------------
    def refresh_details(self):
        text = self.details
        text.configure(state="normal")
        text.delete("1.0", "end")
        if self._focus is None:
            text.insert("end", "Select a file or a run on the left.",
                        "label")
        else:
            stored, run = self._focus
            sections = describe.file_sections(
                stored, self.session.duplicates_in(stored))
            if stored.is_summary:
                sections.append(("Summary", [
                    describe.Fact(
                        f"{row.get('measurement', '')}: "
                        f"{row.get('quantity', '')}",
                        f"{row.get('value', '')} {row.get('unit', '')}"
                        .strip())
                    for row in stored.rows]))
            if run is not None:
                sections += describe.run_sections(stored, run)
            for heading, facts in sections:
                text.insert("end", heading + "\n", "heading")
                for fact in facts:
                    if fact.flagged:
                        text.insert("end", "⚠ " + fact.value + "\n",
                                    "flag")
                    else:
                        text.insert("end", fact.label + ": ", "label")
                        text.insert("end", fact.value + "\n")
        text.configure(state="disabled")

    def refresh_compare(self):
        tree = self.compare_tree
        tree.delete(*tree.get_children())
        series = self.session.ticked_series()
        columns = ["setting"] + [f"run{i}" for i in range(len(series))]
        tree.configure(columns=columns)
        tree.heading("setting", text="Setting")
        tree.column("setting", width=150, stretch=False)
        for i, s in enumerate(series):
            tree.heading(f"run{i}", text=s.label)
            tree.column(f"run{i}", width=130, stretch=False)
        if not series:
            return
        rows = describe.compare_rows([(s.file, s.run) for s in series])
        only_differences = self.only_differences_var.get()
        for key, label, texts, differs in rows:
            if only_differences and not differs:
                continue
            # The mark is in the text as well as the background, so a
            # difference does not rest on a tint alone.
            name = f"≠ {label}" if differs else label
            tree.insert("", "end", values=[name] + texts,
                        tags=("differs",) if differs else ())

    def refresh_data(self):
        tree = self.data_tree
        tree.delete(*tree.get_children())
        run = self._focus[1] if self._focus else None
        if run is None:
            tree.configure(columns=())
            self.data_title_var.set("Select a run to see its readings.")
            return
        columns = list(run.readings)
        tree.configure(columns=columns)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=110, stretch=False)
        count = len(run)
        shown = min(count, DATA_ROW_LIMIT)
        for index in range(shown):
            tree.insert("", "end", values=[
                _cell(run.readings[c][index]) for c in columns])
        self.data_title_var.set(
            f"{run.label}: {count} reading(s)"
            + (f", first {shown} shown" if shown < count else ""))


def _cell(value):
    if isinstance(value, float):
        return "" if not np.isfinite(value) else f"{value:.9g}"
    return str(value)


def main(paths=()):
    """Open the plotter on its own root and run until it is closed."""
    root = tk.Tk()
    apply_window_icon(root)
    PlotterWindow(root, paths)
    root.mainloop()
