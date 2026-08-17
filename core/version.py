"""What version of this application is running.

Why this is a module and not `importlib.metadata`
-------------------------------------------------
The obvious spelling is `importlib.metadata.version("smuniversal-lab-suite")`,
and it is wrong here for two reasons that both bite at exactly the
moment the number matters most.

`importlib.metadata` reads an **installed distribution**. This project
is run from a checkout (`uv run python main.py`) and is intended to ship
as a frozen `.exe`; neither is an installed distribution, so the lookup
raises `PackageNotFoundError` in both of the environments that actually
exist. Wave 7e settles the packaging question, and this still holds
afterwards: a frozen executable has no dist-info to read.

So the number lives in the code, which is the thing that is definitely
present at runtime, and `pyproject.toml` mirrors it.

The mirror is the hazard, and `tests/test_version.py` is the answer
-------------------------------------------------------------------
Two copies of a fact drift. The whole documentation rebuild happened
because four files each held their own copy of what the code did.

The lesson from `tests/test_python_floor.py` applies unchanged: a
constraint nothing tests is not a constraint. That test exists because
`requires-python` claimed support for two Python versions nobody ran,
and the claim sat there being false until a bench machine believed it.
A version number is the same shape of claim, and it goes stale the same
silent way - a release tagged 0.2.0 whose event log says 0.1.0 sends
whoever is reading that log to the wrong commit.

So: change it here, and the test tells you to change it there.

Where it is used
----------------
Every stored file records it, and the operational event log (Wave 7d)
records it per run. That is the point of having it at all: a file
produced last March needs to say which code produced it, because "the
calculation changed in April" is otherwise unanswerable from the file.
"""

#: The single source of truth. `pyproject.toml` mirrors this, and
#: `tests/test_version.py` fails if the two disagree.
__version__ = "0.1.0"


def app_version():
    """The running application's version, as a string.

    A function rather than only a constant so that callers do not each
    import the name and pin it at import time - and so a future build
    that stamps a git description into a frozen executable has one place
    to do it.
    """
    return __version__
