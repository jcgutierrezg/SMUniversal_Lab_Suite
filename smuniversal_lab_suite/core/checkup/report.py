"""The Markdown report a checkup writes.
"""
import time

from smuniversal_lab_suite.core.provenance import as_markdown_lines


def write_pacing(driver):
    """What pause the link held after each write, and whose it was.

    Recorded because it changes the traffic and nothing else in a report
    would show it. A GSM-20H10 checkup from before 2026-09-16 and one
    from after send the same commands in the same order and read
    identically - but one sent them as a burst the instrument drops
    commands from, and the other did not. Without this line the two
    cannot be told apart, which is fault 41: a measurement recorded
    without the configuration it was taken under.

    Taken from the transport, not the class: the value in force is what
    shaped the traffic. The driver's declaration is kept beside it so a
    disagreement - a link left paced by some other caller - shows up as
    one instead of passing for the declared value.

    Returns a dict with `in_force_s` (None when the transport keeps no
    such setting), `declared_s`, and `text` for the Markdown.
    """
    declared = float(getattr(type(driver), "WRITE_DELAY_S", 0.0) or 0.0)
    transport = getattr(driver, "transport", None)
    in_force = getattr(transport, "write_delay_s", None)
    if in_force is None:
        text = "not recorded - this transport keeps no write pacing"
    else:
        in_force = float(in_force)
        if in_force != declared:
            text = (f"{in_force * 1000:g} ms after each write - NOT what "
                    f"the driver declares ({declared * 1000:g} ms)")
        elif in_force:
            text = (f"{in_force * 1000:g} ms after each write, as the "
                    f"driver declares")
        else:
            text = "none - writes sent as fast as the bus takes them"
    return {"in_force_s": in_force, "declared_s": declared, "text": text}


def build_report(driver, results, address="", sensing_note=None,
                 open_circuit=True, provenance=None, stopped_early=False):
    """Render the results as Markdown."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for result in results:
        counts[result.severity] += 1

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    verdict = "FAIL" if counts["fail"] else (
        "PASS WITH WARNINGS" if counts["warn"] else "PASS")

    lines = [
        f"# Instrument checkup - {type(driver).DISPLAY_NAME}",
        "",
        f"- **Result:** {verdict}",
        f"- **When:** {stamp}",
        f"- **Address:** {address or 'not recorded'}",
        f"- **Driver:** `{type(driver).__name__}`",
        f"- **Write pacing:** {write_pacing(driver)['text']}",
        *as_markdown_lines(provenance or {}),
        f"- **Checks:** {counts['pass']} passed, {counts['warn']} warned, "
        f"{counts['fail']} failed, {counts['skip']} skipped",
        "",
        "> This checkup assumes **nothing is connected to the output**. "
        "The measurement checks expect open-circuit behaviour, so a "
        "connected sample will produce warnings that are not faults."
        if open_circuit else
        "> This checkup was told **something is connected** to the "
        "output. The open-circuit measurement checks were skipped, "
        "because the expected reading is unknown. Everything else ran "
        "normally.",
        "",
    ]
    if sensing_note:
        lines += [f"> {sensing_note}", ""]
    # Deliberately the built-in sum, not math.fsum: this counts
    # results, and fsum would return a float where an integer count is
    # meant. The 3.12 float-summation change that moved the maths
    # modules does not touch integer summation.
    if stopped_early:
        lines += [
            "> **This checkup did not finish.** The link to the instrument "
            "went out of step, so the run stopped there rather than record "
            "readings that would answer the previous command. Everything "
            "listed below was taken before that point and is sound; "
            "everything the instrument was never asked is simply absent. "
            "Reconnect the instrument and run it again.", ""]

    if counts["fail"]:
        lines += ["## Failures", ""]
        for result in results:
            if result.severity == "fail":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")
    if counts["warn"]:
        lines += ["## Warnings", ""]
        for result in results:
            if result.severity == "warn":
                lines.append(f"- **{result.name}** - {result.detail}")
        lines.append("")

    titles = {1: "Tier 1 - identity and declarations",
              2: "Tier 2 - configuration syntax (output off)",
              3: "Tier 3 - live measurement"}
    for tier in (1, 2, 3):
        rows = [r for r in results if r.tier == tier]
        if not rows:
            continue
        lines += [f"## {titles[tier]}", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for result in rows:
            detail = (result.detail or "").replace("|", "\\|")
            lines.append(f"| {result.name} | {result.severity} | {detail} |")
        lines.append("")

    return "\n".join(lines)
