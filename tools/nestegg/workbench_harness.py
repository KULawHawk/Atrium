"""Point the Workbench's Run button at the harness environment, then prove it starts.

Run with the WORKBENCH environment's Python:  python workbench_harness.py <harness python>

The Workbench's Mission Control launches conclave_harness_adapters.pipeline_run with the interpreter in the
``harness.python`` setting; blank means the Workbench's own Python, which does not carry the harness (it lives in
its own environment so torch, the lenses and their pins stay out of the Qt one). So a fresh install with a blank
setting would fail at Run. This script:

1. writes ``harness.python`` = the harness part's interpreter into the Workbench's user settings file, using the
   Workbench's own save function, only when the setting is blank or already that value (a different value the
   person chose is never overwritten: that is a loud failure for them to look at);
2. reads it back through the Workbench's own resolver (harness_python_reader over the same layers Mission
   Control builds), so the check sees exactly what Run will see;
3. starts that interpreter with ``-m conclave_harness_adapters.pipeline_run --help``.

Prints one line ``WORKBENCH-HARNESS: OK <path>`` or ``WORKBENCH-HARNESS: FAIL <why>`` and exits 0 / 1.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main(harness_py: str) -> int:
    from conclave_workbench.pages.settings.catalog import HARNESS_PYTHON_KEY, phase_a_defaults, workbench_schema
    from conclave_workbench.pages.settings.provenance import Scope, ScopeLayer
    from conclave_workbench.pages.settings.user_layer import (
        default_user_settings_path, load_user_layer, save_user_value)
    from conclave_workbench.seal.wiring import harness_python_reader

    schema = workbench_schema(None)
    path = default_user_settings_path()

    def layers():  # the same chain Mission Control builds: shipped defaults, then the persisted user layer
        return (ScopeLayer(Scope.DEFAULT, phase_a_defaults(schema, None)), load_user_layer(path))

    current = harness_python_reader(schema, layers)()
    target = os.path.abspath(harness_py)
    if current is None:
        save_user_value(path, HARNESS_PYTHON_KEY, target)
    elif os.path.normcase(os.path.abspath(current)) != os.path.normcase(target):
        print(f"WORKBENCH-HARNESS: FAIL harness.python is already set to {current}, not the installed harness "
              f"environment {target}; left unchanged (change it in Settings > Harness, or clear it and re-run)")
        return 1
    seen = harness_python_reader(schema, layers)()
    if seen is None or os.path.normcase(os.path.abspath(seen)) != os.path.normcase(target):
        print(f"WORKBENCH-HARNESS: FAIL the Workbench resolves harness.python to {seen!r}, not {target}")
        return 1
    r = subprocess.run([seen, "-m", "conclave_harness_adapters.pipeline_run", "--help"],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
        print(f"WORKBENCH-HARNESS: FAIL {seen} -m conclave_harness_adapters.pipeline_run --help exited "
              f"{r.returncode}: {tail[0][:200]}")
        return 1
    print(f"WORKBENCH-HARNESS: OK {seen} (written to {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
