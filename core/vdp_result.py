"""
Reading a sheet resistance back out of a saved Van der Pauw file.

Why a file rather than shared memory: the two experiments are separate
windows, launched separately, and in the lab the Van der Pauw run may
have happened an hour or a week before the Hall run, possibly at a
different bench. A file survives all of that; a variable doesn't.

It also leaves a trail. A Hall result whose Rs came from a named file can
be traced back to the run that produced it, which a retyped number
cannot.

Van der Pauw writes a `<sample>_vanderpauw.csv` whose header is a block
of `# key: value` lines followed by the raw readings. Only the header
matters here, and because it is the same convention every file in this
suite uses, this parser reads the CSV and the older standalone .txt
results with the same code - it simply scans for `#` lines and ignores
everything else.
"""
import datetime
import os

# The key the value is stored under. Changing this breaks old files, so
# read_result() also accepts the older spellings if that ever happens.
RS_KEY = "Rs_ohm_per_sq"


def format_result(sample, rh, rv, rs, rho, thickness_um, stage_lines=None):
    """Build the text of a result file. Pure string work, so it can be
    tested without touching the filesystem."""
    lines = [
        "# Van der Pauw result",
        f"# timestamp: {datetime.datetime.now().isoformat()}",
        f"# sample: {sample}",
        f"# thickness_um: {thickness_um:.6g}",
        f"# Rh_ohm: {rh:.9g}",
        f"# Rv_ohm: {rv:.9g}",
        f"# {RS_KEY}: {rs:.9g}",
        f"# rho_ohm_cm: {rho:.9g}",
    ]
    if stage_lines:
        lines += list(stage_lines)
    return "\n".join(lines) + "\n"


def parse_result(text):
    """Pull the `# key: value` pairs out of a result file into a dict.

    Tolerant on purpose: unknown keys are kept, malformed lines skipped.
    A file that has gained an extra field should still load.
    """
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("#"):
            continue
        body = line.lstrip("#").strip()
        key, sep, value = body.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def read_result(path):
    """Load a result file and return (sheet_resistance, fields).

    Raises ValueError with a message meant for a dialog if the file has
    no readable sheet resistance - better than silently handing back a
    number that isn't there.
    """
    with open(path, "r", encoding="utf-8") as f:
        fields = parse_result(f.read())

    for key in (RS_KEY, "Rs", "Rs_ohm_sq"):
        if key in fields:
            try:
                return float(fields[key]), fields
            except ValueError:
                raise ValueError(
                    f"'{os.path.basename(path)}' has a sheet resistance "
                    f"entry that isn't a number: {fields[key]!r}")

    raise ValueError(
        f"'{os.path.basename(path)}' doesn't contain a sheet resistance.\n\n"
        "Pick a CSV saved by the Van der Pauw experiment - its name ends "
        "in _vanderpauw.csv. The sheet resistance is only written once "
        "Calculate has been pressed there, so a file saved before "
        "calculating won't have one.")
