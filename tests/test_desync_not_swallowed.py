"""
No broad `except` around a query may swallow a desynchronised link.

`TransportDesynchronised` is an ordinary Exception on purpose - a
BaseException would skip the cleanup handler that de-energises the
sample. The cost of that choice is that every broad handler wrapping a
query has to name it and re-raise it first, and there are eighteen such
handlers across the drivers.

Eighteen is too many to remember and the count only goes up. Worse, the
symptom of forgetting one is not a crash: it is a run that quietly
continues on a link whose every reply answers the previous command,
which is the exact failure the class exists to stop.

So the obligation is checked by a machine rather than by a reviewer.
This walks the source, so a handler added tomorrow is caught by CI on
Windows before it can reach a bench.

The rule:

    try:
        reply = self.transport.query(...)
    except TransportDesynchronised:
        raise
    except Exception:
        return (0, "")          # correct for a DROPPED reply, and stays

Swallowing an ordinary failed query is deliberate and stays deliberate.
Being unable to *ask* about errors is not evidence that a command
failed. A desynchronised link is a different claim: it says the answers
themselves can no longer be trusted.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ("core", "drivers", "experiments", "tools")

#: Handlers that catch everything, and so would catch this too.
BROAD = {"Exception", "BaseException"}

#: Files whose broad handlers are allowed to swallow it, with reasons.
#: Empty on purpose - add an entry only with a written reason, because
#: every entry here is a place a poisoned link can pass unnoticed.
EXEMPT: dict[str, str] = {}


def _is_broad(handler):
    """True when this `except` clause would catch a desync."""
    node = handler.type
    if node is None:                       # bare `except:`
        return True
    names = node.elts if isinstance(node, ast.Tuple) else [node]
    for name in names:
        if isinstance(name, ast.Name) and name.id in BROAD:
            return True
        # `except core.transports.base.Exception` and friends
        if isinstance(name, ast.Attribute) and name.attr in BROAD:
            return True
    return False


def _names_desync(handler):
    """True when this `except` clause names TransportDesynchronised."""
    node = handler.type
    if node is None:
        return False
    names = node.elts if isinstance(node, ast.Tuple) else [node]
    return any(
        (isinstance(n, ast.Name) and n.id == "TransportDesynchronised")
        or (isinstance(n, ast.Attribute) and n.attr == "TransportDesynchronised")
        for n in names)


def _reraises(handler):
    """True when the handler body re-raises rather than continuing.

    A bare `raise` or `raise <anything>` at the top level of the
    handler. Deliberately not recursive: a re-raise buried inside an
    `if` is a conditional re-raise, which is not the guarantee wanted
    here and should be written plainly.
    """
    return any(isinstance(stmt, ast.Raise) for stmt in handler.body)


def _queries(node):
    """True when this try-block contains a call to something.query()."""
    return any(isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == "query"
               for n in ast.walk(node))


def _source_files():
    for folder in SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            yield path


def offenders():
    """Every broad handler around a query that would swallow a desync."""
    found = []
    for path in _source_files():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if rel in EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not _queries(node):
                continue
            # A handler that names the class and re-raises protects
            # every broad handler after it in the same try.
            guarded = any(_names_desync(h) and _reraises(h)
                          for h in node.handlers)
            if guarded:
                continue
            for handler in node.handlers:
                if _is_broad(handler) and not _reraises(handler):
                    found.append(f"{rel}:{handler.lineno}")
    return found


def test_no_broad_handler_swallows_a_desync():
    missing = offenders()
    assert not missing, (
        "these handlers wrap a query() and would swallow a "
        "TransportDesynchronised, letting a run continue on a link whose "
        "replies answer the previous command. Add\n\n"
        "    except TransportDesynchronised:\n        raise\n\n"
        "above the broad handler:\n  " + "\n  ".join(missing))


def test_the_lint_can_actually_see_an_offender():
    """The lint's own mutation test.

    A checker that reports nothing because its AST matching is broken
    looks exactly like a clean codebase. This feeds it a known-bad
    snippet and a known-good one, so a passing run above means the rule
    held rather than that the scanner stopped working.
    """
    bad = ast.parse(
        "try:\n"
        "    r = self.transport.query('X?')\n"
        "except Exception:\n"
        "    r = None\n")
    node = next(n for n in ast.walk(bad) if isinstance(n, ast.Try))
    assert _queries(node)
    assert _is_broad(node.handlers[0])
    assert not _reraises(node.handlers[0])

    good = ast.parse(
        "try:\n"
        "    r = self.transport.query('X?')\n"
        "except TransportDesynchronised:\n"
        "    raise\n"
        "except Exception:\n"
        "    r = None\n")
    node = next(n for n in ast.walk(good) if isinstance(n, ast.Try))
    assert _names_desync(node.handlers[0]) and _reraises(node.handlers[0])


def test_a_try_without_a_query_is_not_flagged():
    """Ordinary error handling elsewhere is none of this lint's business.

    A lint that fires on unrelated code gets suppressed, and a
    suppressed lint protects nothing.
    """
    node = next(n for n in ast.walk(ast.parse(
        "try:\n"
        "    x = int(text)\n"
        "except Exception:\n"
        "    x = 0\n")) if isinstance(n, ast.Try))
    assert not _queries(node)


def test_exemptions_carry_a_reason():
    for path, reason in EXEMPT.items():
        assert reason.strip(), f"{path} is exempt with no reason given"
