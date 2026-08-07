"""Find out what makes a second Tk root fail on Windows.

Not a test. A bisection tool, run in CI, to be deleted once it has
answered its question.

The facts it is chasing:

  * `python -c "Tk(); destroy; Tk(); destroy"` succeeds on the same
    Windows runner where the suite fails, so create/destroy/create is
    not the trigger on its own.
  * The failure is always the same: a Tcl file that exists on disk
    cannot be read, and the reported errno is 0. That is the signature
    of Tcl's encoding subsystem having been finalised, not of a missing
    file or a filesystem problem.
  * It reproduces on two unrelated machines with two unrelated Python
    distributions, so it is not the interpreter build and not a synced
    folder.

So something the suite imports or does finalises Tcl. Each scenario
below runs in its own subprocess and adds one ingredient. The first one
that fails names the culprit.
"""
import subprocess
import sys

PROLOGUE = "import tkinter as tk\n"

SECOND_ROOT = (
    "r2 = tk.Tk(); r2.withdraw(); r2.destroy()\n"
    "print('SECOND ROOT OK')\n"
)

SCENARIOS = {
    "plain create/destroy x10":
        "for _ in range(10):\n"
        "    r = tk.Tk(); r.withdraw(); r.destroy()\n"
        + SECOND_ROOT,

    "ttk widgets used":
        "from tkinter import ttk\n"
        "r = tk.Tk(); r.withdraw()\n"
        "ttk.Notebook(r); ttk.Progressbar(r); ttk.Combobox(r)\n"
        "r.destroy()\n"
        + SECOND_ROOT,

    "matplotlib imported only":
        "import matplotlib\n"
        "r = tk.Tk(); r.withdraw(); r.destroy()\n"
        + SECOND_ROOT,

    "matplotlib TkAgg canvas built and closed":
        "import matplotlib\n"
        "matplotlib.use('TkAgg')\n"
        "from matplotlib.figure import Figure\n"
        "from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg\n"
        "r = tk.Tk(); r.withdraw()\n"
        "c = FigureCanvasTkAgg(Figure(), master=r)\n"
        "c.get_tk_widget().pack()\n"
        "r.destroy()\n"
        + SECOND_ROOT,

    "pyplot figure created and closed":
        "import matplotlib\n"
        "matplotlib.use('TkAgg')\n"
        "import matplotlib.pyplot as plt\n"
        "f = plt.figure(); plt.close(f)\n"
        "r = tk.Tk(); r.withdraw(); r.destroy()\n"
        + SECOND_ROOT,

    "PIL ImageTk used":
        "from PIL import Image, ImageTk\n"
        "r = tk.Tk(); r.withdraw()\n"
        "ImageTk.PhotoImage(Image.new('RGB', (8, 8)))\n"
        "r.destroy()\n"
        + SECOND_ROOT,

    "worker thread touches the root":
        "import threading\n"
        "r = tk.Tk(); r.withdraw()\n"
        "done = threading.Event()\n"
        "t = threading.Thread(target=lambda: (r.after(0, lambda: None),\n"
        "                                     done.set()))\n"
        "t.start(); t.join(); done.wait(2)\n"
        "r.destroy()\n"
        + SECOND_ROOT,

    "LabApp built and closed":
        "from core.base_app import LabApp\n"
        "from experiments.vanderpauw.experiment import VanDerPauwExperiment\n"
        "r = tk.Tk(); r.withdraw()\n"
        "app = LabApp(r, VanDerPauwExperiment)\n"
        "r.update_idletasks()\n"
        "r.destroy()\n"
        + SECOND_ROOT,
}


def main() -> int:
    width = max(len(name) for name in SCENARIOS)
    first_failure = None
    for name, body in SCENARIOS.items():
        proc = subprocess.run([sys.executable, "-c", PROLOGUE + body],
                              capture_output=True, text=True, timeout=180)
        ok = proc.returncode == 0 and "SECOND ROOT OK" in proc.stdout
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}")
        if not ok:
            tail = (proc.stderr or proc.stdout).strip().splitlines()
            for line in tail[-6:]:
                print(f"           {line}")
            if first_failure is None:
                first_failure = name

    print()
    if first_failure:
        print(f"FIRST FAILING SCENARIO: {first_failure}")
    else:
        print("Every scenario passed - the trigger is not in this list.")
    return 0        # never fail the job; this step exists to report


if __name__ == "__main__":
    raise SystemExit(main())
