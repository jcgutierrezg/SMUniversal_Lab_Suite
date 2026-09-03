"""A dummy SMU that can be stopped at a named point in a run.

Why this exists
---------------
A cancellation-boundary matrix has to press Stop at an exact instant -
before the output goes on, between two points, halfway through a
reversal set. Doing that by sleeping and hoping is a test that passes on
a fast machine and fails on a loaded CI runner, and on Windows the 15.6
ms clock quantisation makes "wait 20 ms then cancel" a coin toss. A
matrix that goes red intermittently teaches everybody to press re-run,
which costs more than the matrix was worth.

So the instrument blocks instead of the test sleeping. `arm()` names a
stage; the driver runs normally until it reaches that stage, then sets
`reached` and waits on `release`. The test waits for `reached` - which
is a fact, not a duration - does whatever it wants to do at that exact
moment, and sets `release`.

The analogy: a single-step debugger on the instrument side rather than a
stopwatch on the test side.

Stages
------
Named after what the *worker* is doing, not after which driver method is
being called, because that is the vocabulary review §8 uses when it
lists where a cancellation check belongs.

``before_output_on``
    Inside `output_on()`, before the output is live. §8's named race:
    Stop pressed during configuration, worker energises anyway.

``first_measure``
    Inside the first `measure()`. The settle happens here - the delay
    was handed to the instrument with `set_source_delay()` - so this is
    "during settle" as far as the worker can tell.

``mid_reversal``
    Inside `set_current_level()` on the second polarity flip of a
    reversal set. Cancelling here must not leave a partial average.

``between_points``
    Inside `set_current_level()` at the start of the second point.

``second_polarity``
    Inside `set_current_level()` on the flip to the negative current
    block. Used by both Van der Pauw and Hall, for related but distinct
    reasons.

    Van der Pauw averages the two blocks, so a cancellation that left
    the positive one behind would give an R(ave) that is not an average
    of anything - wrong by a factor that depends on the offset, and
    entirely plausible on screen.

    Hall does not average them, which makes it worse rather than better:
    a half-finished run would put a row in the table carrying a V+ and
    no V-, and the eight-term average downstream would draw on a
    combination that was never measured at one field direction.

``last_measure``
    Inside the final `measure()` of the run. Cancellation lands between
    the last reading and the commit, exercising §8's "immediately before
    final commit" checkpoint.

Deadlocks
---------
Every wait is bounded. A stage that is never reached fails the test with
a timeout rather than hanging the suite - which matters because
`run_tests.py` gives GUI files their own process and a hung one takes
the whole group with it.
"""
import threading

from drivers.dummy_smu import DummySMU

#: How long a test will wait for a stage before declaring it unreachable.
REACH_TIMEOUT = 10.0

#: How long the instrument will block before giving up and continuing.
#: Bounded so a test that forgets to release cannot hang the process.
BLOCK_TIMEOUT = 10.0


class StageNotReached(AssertionError):
    """The run never got to the stage the test armed."""


class StageBlockingSMU(DummySMU):
    """A `DummySMU` that pauses at one named stage and waits.

    Everything else behaves exactly as `DummySMU` does, so a run that
    is never cancelled produces the same numbers as a normal demo run.
    That matters: the matrix asserts that a *completed* run still
    commits, and it would prove nothing against an instrument whose
    physics had been stubbed out.
    """

    def __init__(self, transport, **kwargs):
        super().__init__(transport, **kwargs)
        self._stage = None
        self.reached = threading.Event()
        self.release = threading.Event()

        # Call counters, used both to identify a stage and to assert
        # afterwards that nothing was issued post-cancellation.
        self.output_on_calls = 0
        self.output_off_calls = 0
        self.measure_calls = 0
        self.level_calls = 0
        self.levels = []
        #: Every command issued after `stop_here()` returned, in order.
        #: Should be the shutdown and nothing else.
        self.after_release = []
        self._released_at = None

    # ---- arming ----
    def arm(self, stage):
        """Block the next time the run reaches `stage`."""
        self._stage = stage
        self.reached.clear()
        self.release.clear()
        return self

    def wait_until_blocked(self, timeout=REACH_TIMEOUT):
        """Block the *test* until the run is parked at the armed stage."""
        if not self.reached.wait(timeout):
            raise StageNotReached(
                f"the run never reached stage {self._stage!r} within "
                f"{timeout}s (output_on={self.output_on_calls}, "
                f"measure={self.measure_calls}, level={self.level_calls})")
        return self

    def let_go(self):
        """Let the parked run continue."""
        self._released_at = (self.measure_calls, self.level_calls)
        self.release.set()

    # ---- the block itself ----
    _blocked_call = False

    def _pause_if(self, stage):
        if stage != self._stage:
            return
        self._stage = None          # fire once, not on every later call
        self.reached.set()
        # Bounded: a test that forgets to release loses, but does not
        # take the process with it.
        self.release.wait(BLOCK_TIMEOUT)
        # The call we are *inside* does not count as "issued after the
        # cancellation". A driver call is not interruptible half way
        # through - `output_on()` that has already been entered will
        # finish - and the guarantee under test is about the checkpoint
        # after it, not about rewriting history. Counting the blocked
        # call itself would make every row fail for a reason the code
        # could not have avoided.
        self._blocked_call = True

    def _note(self, what):
        if self._blocked_call:
            self._blocked_call = False
            return
        if self.release.is_set() and self._released_at is not None:
            self.after_release.append(what)

    # ---- instrumented driver methods ----
    def output_on(self):
        self._pause_if("before_output_on")
        self._note("output_on")
        self.output_on_calls += 1
        return super().output_on()

    def output_off(self):
        self.output_off_calls += 1
        return super().output_off()

    def set_current_level(self, amps):
        self.level_calls += 1
        self.levels.append(amps)
        # The reversal pattern for a single current is +I, -I, +I, -I...
        # so the second call at a nonzero level is the first polarity
        # flip. Level 1 is the zero set during configuration.
        if self.level_calls == 3:
            self._pause_if("mid_reversal")
        # Van der Pauw's shape, added in Wave 5a-i. It sets no level
        # during configuration and sources exactly twice - once per
        # polarity block - so its flip is call 2, where 4PP's is call 3.
        # The indices differ because the sequences differ; a stage only
        # fires when a test arms it, so the two never collide.
        if self.level_calls == 2:
            self._pause_if("second_polarity")
        if self.level_calls == 2 + self._reversals_guess():
            self._pause_if("between_points")
        self._note(f"set_current_level({amps:.3g})")
        return super().set_current_level(amps)

    def measure(self, timeout_s=3.0):
        self.measure_calls += 1
        if self.measure_calls == 1:
            self._pause_if("first_measure")
        if self._last_measure is not None \
                and self.measure_calls == self._last_measure:
            self._pause_if("last_measure")
        self._note("measure")
        return super().measure(timeout_s=timeout_s)

    # ---- knowing which measure is the last ----
    _last_measure = None
    _reversals = None

    def expect_readings(self, points, reversals):
        """Tell the fake how long the run is, so `last_measure` works.

        The driver cannot infer this: it sees a stream of levels and
        reads with no idea how many are coming. The test knows, because
        the test wrote the form.
        """
        self._reversals = reversals
        self._last_measure = points * reversals
        return self

    def _reversals_guess(self):
        return self._reversals or 1
