"""
The files open in the plotter, which runs are ticked, and their colours.

Kept free of Tk so the rules that are easy to get subtly wrong - a run
saved in two overlapping snapshots, a colour that jumps when another run
is unticked - are tested directly.

Overlapping snapshots
---------------------
Every save writes the whole store, so two files from one session share
runs on purpose. A run is identified by its `record_id`; the first open
file that holds it owns it, and later copies are counted rather than
shown twice. Removing the owning file hands the run to the next file
that has it - ownership is recomputed from the open files each time, not
remembered, so it cannot go stale.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from smuniversal_lab_suite.plotter import style
from smuniversal_lab_suite.plotter.reader import StoredFile, StoredRun


@dataclass(frozen=True)
class Series:
    """A ticked run, ready to draw: the run, its file, colour and name."""

    run: StoredRun
    file: StoredFile
    color: str
    label: str


class Session:
    def __init__(self):
        self.files: list[StoredFile] = []
        self._ticked: list[str] = []          # record ids, tick order
        self._slots: dict[str, int] = {}      # record id -> palette slot

    # ---- files -----------------------------------------------------
    def add(self, stored: StoredFile) -> bool:
        """Open a file. False if that path is already open."""
        key = os.path.normcase(os.path.abspath(stored.path))
        for existing in self.files:
            if os.path.normcase(os.path.abspath(existing.path)) == key:
                return False
        self.files.append(stored)
        return True

    def remove(self, stored: StoredFile) -> None:
        self.files = [f for f in self.files if f is not stored]
        owned = {run.record_id for _, run in self.visible_runs()}
        for record_id in list(self._ticked):
            if record_id not in owned:
                self.untick(record_id)

    def clear(self) -> None:
        self.files.clear()
        self._ticked.clear()
        self._slots.clear()

    def visible_runs(self):
        """(file, run) for every run shown, first copy only."""
        seen = set()
        out = []
        for stored in self.files:
            for run in stored.runs:
                if run.record_id in seen:
                    continue
                seen.add(run.record_id)
                out.append((stored, run))
        return out

    def runs_of(self, stored: StoredFile) -> list[StoredRun]:
        """The runs this file owns - those not already shown from an
        earlier file."""
        return [run for owner, run in self.visible_runs() if owner is stored]

    def duplicates_in(self, stored: StoredFile) -> int:
        """How many of this file's runs are shown from another file."""
        return len(stored.runs) - len(self.runs_of(stored))

    # ---- ticks and colours -------------------------------------------
    def is_ticked(self, record_id: str) -> bool:
        return record_id in self._ticked

    def tick(self, record_id: str) -> None:
        if record_id in self._ticked:
            return
        self._ticked.append(record_id)
        taken = set(self._slots.values())
        free = next((i for i in range(len(style.CATEGORICAL))
                     if i not in taken), None)
        if free is not None:
            self._slots[record_id] = free

    def untick(self, record_id: str) -> None:
        if record_id in self._ticked:
            self._ticked.remove(record_id)
        self._slots.pop(record_id, None)

    def toggle(self, record_id: str) -> None:
        if self.is_ticked(record_id):
            self.untick(record_id)
        else:
            self.tick(record_id)

    def ticked_series(self) -> list[Series]:
        """Every ticked run, coloured, in the order they were measured.

        Up to eight runs keep the categorical slot they were given when
        ticked. Past eight, every run is coloured by time on the
        sequential ramp instead - there is no ninth hue.
        """
        owner = {run.record_id: (stored, run)
                 for stored, run in self.visible_runs()}
        chosen = [owner[r] for r in self._ticked if r in owner]
        chosen.sort(key=lambda pair: (pair[1].text("run_timestamp"),
                                      pair[1].record_id))
        labels = _labels([run for _, run in chosen],
                         [stored for stored, _ in chosen])

        if len(chosen) > len(style.CATEGORICAL):
            colors = style.sequential_colors(len(chosen))
        else:
            colors = []
            for _, run in chosen:
                slot = self._slots.get(run.record_id)
                if slot is None:
                    # A run ticked while eight others were: it gets the
                    # first slot free now.
                    taken = set(self._slots.values())
                    slot = next(i for i in range(len(style.CATEGORICAL))
                                if i not in taken)
                    self._slots[run.record_id] = slot
                colors.append(style.CATEGORICAL[slot])

        return [Series(run, stored, color, label)
                for (stored, run), color, label
                in zip(chosen, colors, labels)]

    @property
    def uses_sequential_colors(self) -> bool:
        return len(self.ticked_series()) > len(style.CATEGORICAL)


def _labels(runs, files) -> list[str]:
    """`sample · dataset`, made unique where two runs would share one."""
    base = []
    for run, stored in zip(runs, files):
        sample = run.text("sample_label") or stored.sample
        base.append(f"{sample} · {run.label}" if sample else run.label)
    counts: dict[str, int] = {}
    for label in base:
        counts[label] = counts.get(label, 0) + 1
    out = []
    for label, run in zip(base, runs):
        if counts[label] > 1:
            number = run.text("meas_number")
            label = f"{label} (#{number})" if number else \
                f"{label} ({run.record_id[-6:]})"
        out.append(label)
    return out
