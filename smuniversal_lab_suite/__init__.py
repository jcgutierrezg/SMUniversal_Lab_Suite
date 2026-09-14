"""SMUniversal Lab Suite.

One namespace for everything the suite installs. Until Wave E the
packages sat at the top level as `core`, `devices`, `drivers` and
`experiments` - names at least as generic as the `main` this project
already refused to install, and free to collide with any other package
in a shared environment. The console script, `smu-lab-suite`, is the
only other thing the wheel puts on the path.
"""
