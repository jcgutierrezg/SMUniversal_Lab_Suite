"""
The plotter's session: overlapping snapshots, ticks and colours.
"""
from plotter_files import iv_run, stored

from smuniversal_lab_suite.plotter import style
from smuniversal_lab_suite.plotter.session import Session


def _session_with(runs, path="filmA_iv_sweep.csv"):
    session = Session()
    session.add(stored(runs, path=path))
    return session


def test_a_colour_follows_its_run_when_another_is_unticked(check):
    runs = [iv_run(f"r{i}", minutes=i) for i in range(3)]
    session = _session_with(runs)
    ids = [r.record_id for r in runs]
    for record_id in ids:
        session.tick(record_id)
    before = {s.run.record_id: s.color for s in session.ticked_series()}

    session.untick(ids[0])
    after = {s.run.record_id: s.color for s in session.ticked_series()}
    check("survivors keep their colours",
          all(after[r] == before[r] for r in ids[1:]), (before, after))

    session.tick(ids[0])
    again = {s.run.record_id: s.color for s in session.ticked_series()}
    check("a re-ticked run takes the free slot",
          again[ids[0]] == before[ids[0]], again)


def test_past_eight_runs_colour_by_time_and_back(check):
    count = len(style.CATEGORICAL) + 2
    runs = [iv_run(f"r{i}", minutes=i) for i in range(count)]
    session = _session_with(runs)
    for run in runs:
        session.tick(run.record_id)
    series = session.ticked_series()
    check("sequential", session.uses_sequential_colors)
    check("earliest lightest, latest darkest",
          series[0].color == style.SEQUENTIAL[0]
          and series[-1].color == style.SEQUENTIAL[-1],
          [s.color for s in series])
    check("no categorical hue reused",
          not any(s.color in style.CATEGORICAL[1:] for s in series[:-1]))

    first_colors = {}
    for run in runs[:2]:
        session.untick(run.record_id)
    series = session.ticked_series()
    first_colors = {s.run.record_id: s.color for s in series}
    check("back to categorical at eight",
          set(first_colors.values()) <= set(style.CATEGORICAL)
          and len(set(first_colors.values())) == len(series), first_colors)


def test_a_run_saved_in_two_snapshots_is_shown_once(check):
    shared = iv_run("shared")
    later = iv_run("later", minutes=5)
    first = stored([shared], path="filmA_iv_sweep.csv")
    second = stored([shared, later], path="filmA_iv_sweep_1.csv")
    session = Session()
    session.add(first)
    session.add(second)

    check("shown once", len(session.visible_runs()) == 2,
          [r.label for _, r in session.visible_runs()])
    check("counted as a duplicate", session.duplicates_in(second) == 1)

    session.tick(shared.record_id)
    session.remove(first)
    check("the next file takes it over",
          [r.label for r in session.runs_of(second)] == ["shared", "later"])
    check("and it stays ticked", session.is_ticked(shared.record_id))


def test_closing_the_only_copy_unticks_it(check):
    run = iv_run("only")
    session = _session_with([run])
    session.tick(run.record_id)
    session.remove(session.files[0])
    check("gone", session.ticked_series() == [])
    check("and not ticked", not session.is_ticked(run.record_id))


def test_the_same_path_is_not_opened_twice(check):
    run = iv_run()
    session = Session()
    check("first", session.add(stored([run], path="a/filmA_iv_sweep.csv")))
    check("second refused",
          not session.add(stored([run], path="a/filmA_iv_sweep.csv")))


def test_labels_are_unique_when_datasets_repeat(check):
    runs = [iv_run("run", minutes=i) for i in range(2)]
    session = _session_with(runs)
    for run in runs:
        session.tick(run.record_id)
    labels = [s.label for s in session.ticked_series()]
    check("distinct", len(set(labels)) == 2, labels)
    check("still named after the dataset",
          all("filmA · run" in label for label in labels), labels)
