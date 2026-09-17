"""
The plotter window, driven the way an operator would.

The drawing and the details are tested headless in
`test_plotter_views.py`; this file is about the wiring between the file
list, the plot, the tabs and the dialogs.
"""
import pytest

pytestmark = [pytest.mark.gui]

import os
import tkinter as tk

from matplotlib.backend_bases import MouseEvent
from plotter_files import FIXED_TITLE, fixed_run, iv_run, write

import smuniversal_lab_suite.plotter.window as window_module
from smuniversal_lab_suite.plotter.reader import load
from smuniversal_lab_suite.plotter.window import (
    TICKED,
    UNTICKED,
    PlotterWindow,
)


class Dialogs:
    def __init__(self, save_to=None):
        self.calls = []
        self.save_to = save_to

    def showwarning(self, title, message, **kw):
        self.calls.append(("warning", title, message))

    def showinfo(self, title, message, **kw):
        self.calls.append(("info", title, message))

    def showerror(self, title, message, **kw):
        self.calls.append(("error", title, message))

    def asksaveasfilename(self, **kw):
        self.calls.append(("save", kw.get("initialfile")))
        return self.save_to or ""


@pytest.fixture
def dialogs(monkeypatch):
    recorder = Dialogs()
    monkeypatch.setattr(window_module, "messagebox", recorder)
    monkeypatch.setattr(window_module, "filedialog", recorder)
    return recorder


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


def _runs_in_tree(w):
    return {w.tree.item(i, "text"): i for i in w._run_items}


def test_opening_files_plots_the_first_one(check, tmp_path, root, dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv",
               [iv_run("fwd"), iv_run("rev", minutes=1)])
    fs = write(tmp_path, "filmA_fixed_source.csv", [fixed_run()],
               title=FIXED_TITLE)
    w = PlotterWindow(root, [iv, fs])
    root.update()

    items = _runs_in_tree(w)
    check("both files listed", len(w._file_items) == 2)
    check("the first file's runs are ticked",
          f"{TICKED} fwd" in items and f"{TICKED} rev" in items, items)
    check("the other file's run is not", f"{UNTICKED} hold" in items, items)
    check("an IV view is chosen", w.view_var.get() == "I–V curves",
          w.view_var.get())
    check("the plot has the two runs",
          len([line for line in w.figure.axes[0].lines
               if line.get_gid()]) == 2)
    check("nothing asked", dialogs.calls == [], dialogs.calls)


def test_ticking_across_experiments_explains_itself(check, tmp_path, root,
                                                    dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv", [iv_run("fwd")])
    fs = write(tmp_path, "filmA_fixed_source.csv", [fixed_run()],
               title=FIXED_TITLE)
    w = PlotterWindow(root, [iv, fs])
    w._toggle(_runs_in_tree(w)[f"{UNTICKED} hold"])
    root.update()
    check("only the comparison is offered",
          list(w.view_combo.cget("values")) == ["Saved value by run"],
          w.view_combo.cget("values"))
    check("and chosen", w.view_var.get() == "Saved value by run")
    combos = [c for c in w.options_frame.winfo_children()
              if c.winfo_class() == "TCombobox"]
    check("with its value and axis drop-downs", len(combos) == 2)
    check("both runs plotted",
          len([line for line in w.figure.axes[0].lines
               if line.get_gid()]) == 2)

    against = combos[1]
    against.set("Sample")
    against.event_generate("<<ComboboxSelected>>")
    root.update()
    check("a choice redraws the plot",
          [t.get_text() for t in w.figure.axes[0].get_xticklabels()]
          == ["filmA"])
    w.refresh()
    check("and is remembered across redraws",
          w._choices.get(("compare_values", "against")) == "sample")

    w._toggle(_runs_in_tree(w)[f"{TICKED} fwd"])
    root.update()
    check("unticking the IV run brings the Fixed source views",
          w.view_var.get() == "Measured against time", w.view_var.get())


def test_the_chosen_view_and_its_options_are_remembered(check, tmp_path,
                                                        root, dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv", [iv_run("fwd")])
    w = PlotterWindow(root, [iv])
    w.view_var.set("|I| against V (log)")
    w._on_view_chosen()
    w.untick_all()
    w._toggle(_runs_in_tree(w)[f"{UNTICKED} fwd"])
    root.update()
    check("same view after re-ticking",
          w.view_var.get() == "|I| against V (log)", w.view_var.get())
    check("drawn on a log axis", w.figure.axes[0].get_yscale() == "log")


def test_selecting_a_run_fills_details_compare_and_data(check, tmp_path,
                                                        root, dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv",
               [iv_run("fwd"), iv_run("rev", minutes=1, sensing="2-wire")])
    w = PlotterWindow(root, [iv])
    item = _runs_in_tree(w)[f"{TICKED} rev"]
    w.tree.selection_set(item)
    w._on_tree_select()
    root.update()

    details = w.details.get("1.0", "end")
    check("run details shown", "Run: rev" in details and "Sensing: 2-wire"
          in details, details[:400])
    check("file details shown", "Experiment: IV sweep" in details)
    rows = {w.compare_tree.item(i, "values")[0]
            for i in w.compare_tree.get_children()}
    check("the difference is marked in text", "≠ Sensing" in rows, rows)
    check("data rows", len(w.data_tree.get_children()) == 11)


def test_an_unreadable_file_is_reported_and_the_rest_open(check, tmp_path,
                                                          root, dialogs):
    good = write(tmp_path, "filmA_iv_sweep.csv", [iv_run()])
    bad = tmp_path / "notes.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    w = PlotterWindow(root, [good, str(bad)])
    check("the good file opened", len(w.session.files) == 1)
    warnings = [c for c in dialogs.calls if c[0] == "warning"]
    check("one warning naming the bad file",
          len(warnings) == 1 and "notes.csv" in warnings[0][2], dialogs.calls)


def test_closing_a_file_removes_its_runs_from_the_plot(check, tmp_path, root,
                                                       dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv", [iv_run()])
    w = PlotterWindow(root, [iv])
    w.tree.selection_set(next(iter(w._file_items)))
    w.close_selected_file()
    root.update()
    check("no files", w.session.files == [])
    check("nothing plotted", w.figure.axes == [])


def test_save_figure_writes_only_where_asked(check, tmp_path, root, dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv", [iv_run()])
    w = PlotterWindow(root, [iv])
    before = set(os.listdir(tmp_path))

    w.save_figure()               # cancelled: empty path
    check("cancel writes nothing", set(os.listdir(tmp_path)) == before)

    dialogs.save_to = str(tmp_path / "out.png")
    w.save_figure()
    check("written", os.path.exists(tmp_path / "out.png"))
    check("offered a name from the sample and view",
          dialogs.calls[0][1].startswith("filmA_"), dialogs.calls)


def test_hovering_names_the_nearest_point(check, tmp_path, root, dialogs):
    iv = write(tmp_path, "filmA_iv_sweep.csv", [iv_run("fwd")])
    w = PlotterWindow(root, [iv])
    root.update()
    w.canvas.draw()
    ax = w.figure.axes[0]
    line = next(line for line in ax.lines if line.get_gid())
    x, y = line.get_xydata()[3]
    px, py = ax.transData.transform((x, y))
    w._on_hover(MouseEvent("motion_notify_event", w.canvas, px + 2, py + 2))
    check("a label appears", w._hover is not None)
    check("naming the run", w._hover is not None
          and w._hover.get_text().startswith("filmA · fwd"))

    w._on_hover(MouseEvent("motion_notify_event", w.canvas, 0, 0))
    check("and goes away off the data", w._hover is None)


def test_reload_opens_a_later_save(check, tmp_path, root, dialogs):
    first = iv_run("fwd")
    path = write(tmp_path, "filmA_iv_sweep.csv", [first])
    w = PlotterWindow(root, [path])
    w.tree.selection_set(next(i for i, (_f, r) in w._run_items.items()
                              if r.label == "fwd"))
    w._on_tree_select()

    write(tmp_path, "filmA_iv_sweep_1.csv", [first, iv_run("rev",
                                                          minutes=1)])
    w.reload()
    root.update()
    labels = sorted(r.label for _f, r in w._run_items.values())
    check("the new run is listed once", labels == ["fwd", "rev"], labels)
    check("the status names the new file",
          "filmA_iv_sweep_1.csv" in w.status_var.get(), w.status_var.get())
    check("the selected run is still in the details",
          "Run: fwd" in w.details.get("1.0", "end"))


def test_export_and_the_settings_table(check, tmp_path, root, dialogs):
    path = write(tmp_path, "filmA_iv_sweep.csv",
                 [iv_run("fwd"), iv_run("rev", minutes=1)])
    w = PlotterWindow(root, [path])

    dialogs.save_to = str(tmp_path / "out_data.csv")
    w.export_data()
    check("readings exported", os.path.exists(tmp_path / "out_data.csv"))

    dialogs.save_to = path
    w.export_data()
    check("an open data file is never overwritten",
          any(c[0] == "error" for c in dialogs.calls)
          and load(path).runs, dialogs.calls)

    dialogs.save_to = str(tmp_path / "settings.csv")
    w.save_compare_table()
    check("settings table saved", os.path.exists(tmp_path / "settings.csv"))

    w.copy_compare_table()
    check("copied to the clipboard",
          root.clipboard_get().startswith("setting\tdiffers"))
