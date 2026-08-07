"""Root conftest.

Its only job is to exist. pytest inserts the directory holding the
rootdir conftest at the front of sys.path, which is what lets the test
files say `from core.limits import ...` without each one repeating the
`sys.path.insert(...)` bootstrap they used to carry.
"""
