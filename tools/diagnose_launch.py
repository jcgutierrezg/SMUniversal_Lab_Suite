"""Does the way a child process is launched decide whether Tcl works?

Same file, same interpreter, same arguments - only the child's standard
handles differ. `run_tests.py` uses capture_output=True, which gives the
child pipes; run directly, it gets the console.

On Windows CI, tests/test_dialects.py passes when pytest is invoked
directly and fails when run_tests.py launches it. This isolates that one
variable.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TARGET = "tests/test_dialects.py"
ARGS = [sys.executable, "-m", "pytest", TARGET, "-q", "--no-header",
        "-p", "no:cacheprovider"]

CASES = {
    "inherit console (no redirection)": dict(),
    "capture_output=True (what run_tests.py does)": dict(capture_output=True),
    "pipes for stdout/stderr, stdin=DEVNULL": dict(
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL),
    "stdout/stderr to a file, stdin inherited": "file",
}


def main() -> int:
    width = max(len(k) for k in CASES)
    for name, kwargs in CASES.items():
        if kwargs == "file":
            with open(ROOT / "_launch_out.txt", "w") as fh:
                proc = subprocess.run(ARGS, cwd=ROOT, stdout=fh,
                                      stderr=subprocess.STDOUT, timeout=300)
            out = (ROOT / "_launch_out.txt").read_text(errors="replace")
        else:
            proc = subprocess.run(ARGS, cwd=ROOT, text=True, timeout=300,
                                  **kwargs)
            out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  exit={proc.returncode}")
        if not ok:
            for line in [l for l in out.splitlines() if "TclError" in l
                         or "couldn't read" in l][:3]:
                print(f"           {line.strip()[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
