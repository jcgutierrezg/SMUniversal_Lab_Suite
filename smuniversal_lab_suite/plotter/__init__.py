"""
The CSV plotter: open files this suite saved and look at them.

One window for every experiment. It reads the `#` header each save
writes, works out which experiment produced the file, and offers the
plots and run details that experiment's data is for - so an IV file
opens as I-V curves with their fits and a Fixed source file opens as a
trace against time, without anyone choosing.

`reader` and `detect` import no Tk and touch no instrument, so the file
format is tested directly. The window is built on top of them.
"""
