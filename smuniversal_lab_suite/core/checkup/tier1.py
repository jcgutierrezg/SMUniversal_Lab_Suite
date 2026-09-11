"""Tier 1 - who is on the other end, and what it says it can do.

A mixin on `Checkup`; the state it uses is set up by
`CheckupBase`.
"""

from smuniversal_lab_suite.core.transports.base import TransportDesynchronised


class Tier1Checks:
    """Tier 1 - who is on the other end, and what it says it can do."""


    # ---- tier 1 ----
    def tier1_identity(self):
        driver = self.driver
        self._log("\nTier 1 - identity and declarations")

        self.attempt(1, "identify()", driver.identify,
                     expect=lambda v: True if v and str(v).strip()
                     else "empty identity reply")

        # The registry is what picks the driver at connect. If the
        # identity no longer resolves to the class in use, auto-detection
        # is broken even though everything else may work.
        from smuniversal_lab_suite.drivers.registry import driver_for_idn
        try:
            idn = driver.identify()
            resolved = driver_for_idn(idn)
            if resolved is type(driver):
                self.record(1, "identity resolves to this driver", "pass",
                            type(driver).__name__)
            elif resolved is None:
                self.record(1, "identity resolves to this driver", "fail",
                            f"MODEL_IDS {type(driver).MODEL_IDS} does not "
                            f"match {idn!r} - auto-detect would fail")
            else:
                self.record(1, "identity resolves to this driver", "fail",
                            f"resolves to {resolved.__name__}, not "
                            f"{type(driver).__name__} - auto-detect would "
                            f"pick the wrong driver for this instrument")
        except TransportDesynchronised:
            raise
        except Exception as exc:
            self.record(1, "identity resolves to this driver", "fail", str(exc))

        for label, value in (
                ("firmware", getattr(driver, "firmware", None)),
                ("sweep kind", getattr(driver, "sweep_kind", None))):
            if callable(value):
                self.attempt(1, label, value)

        self.attempt(1, "reset()", driver.reset)
        self.check_queue(1, "reset()")

        note = getattr(driver, "sweep_note", None)
        if callable(note):
            self.attempt(1, "sweep_note()", note)

        limits = driver.LIMITS
        self.record(1, "declared limits", "pass",
                    f"{limits.max_voltage} V, {limits.max_current} A, "
                    f"{len(limits.current_ranges)} current range(s)")

        # The levels this run sourced, and why they are what they are.
        # Recorded in tier 1 rather than left implicit, because a
        # commissioning report is read against other instruments' and a
        # probe that differs between them has to say so on its own line
        # - otherwise the first person to compare two reports finds a
        # different current in tier 3 and has nowhere to look.
        #
        # The row is kept and rewritten at the end of the run. One of
        # the four levels can still move in tier 3, where the active
        # range turns out not to be able to express it, and this row is
        # the one people read: on 2026-09-04 it said the U2722A was
        # probed at the nominal 1 uA while tier 3 had substituted
        # 73.2 uA and said so forty lines further down.
        self._probe_result = self.record(1, "probe levels", "pass",
                                         self._probe_summary())

        # What is known about a source level below one count of whatever
        # range is active. Three answers, and none of them is a pass:
        # this is a property of the instrument that a checkup can report
        # and cannot establish.
        for quantity in ("current", "voltage"):
            self._record_sub_count_state(quantity)

    def _record_sub_count_state(self, quantity):
        """Say, per axis, what is known about sub-count source levels.

        A `warn` for `unmeasured`, deliberately, and on six of the eight
        drivers in the registry. It is not noise: below one count of the
        active range a commanded level is offset residue, and on the one
        instrument where that has been measured the residue's sign was
        not the sign anybody asked for - it walked the output to the
        range rail during a commissioning run. Whether the same is true
        of the Keithleys, the B2901A and the GSM-20H10 is unknown, and
        an unknown that changes which way current flows through somebody
        's sample does not render as a skip.

        Each warn is closed by one bench measurement on one instrument,
        not by a change here.
        """
        cls = type(self.driver)
        state = cls.sub_count_state(quantity)
        name = f"sub-count {quantity} levels"
        if state == cls.SUB_COUNT_REFUSED:
            self.record(1, name, "pass",
                        "measured on this model, and this driver refuses a "
                        "level below its declared floor before the output "
                        "is energised")
        elif state == cls.SUB_COUNT_NOT_APPLICABLE:
            self.record(1, name, "skip",
                        f"this model has no source {quantity} range for a "
                        f"level to fall below, so the question does not "
                        f"arise in this form. What a sub-count source "
                        f"{quantity} would mean here is itself unmeasured")
        else:
            self.record(
                1, name, "warn",
                f"UNMEASURED on this model. Every fixed-range converter "
                f"has a bottom count; below it a commanded level is offset "
                f"residue whose sign is not commanded, which on the one "
                f"instrument where this was measured drove the output to "
                f"the range rail. Nothing in this suite puts a floor under "
                f"a source {quantity} here, and nothing has measured where "
                f"the floor is. Closed by one bench measurement: command "
                f"plus and minus a small fraction of a count on a wide "
                f"range and see whether the output follows the sign")
