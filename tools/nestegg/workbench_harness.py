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

Second use, after a whole install passes:  python workbench_harness.py --reader-envs <reader_envs.json> <harness python>

Turns on ``harness.reader_envs`` (Decision 8 A: each reader is checked and run from its own environment, so the
installed app is no longer limited to what the harness environment itself carries). Same rules as above: written
only when blank or already that file (a value the person chose is never overwritten), read back through the
Workbench's own resolver, then proved by running the preset probe exactly as Mission Control will
(``-m conclave_harness_adapters.preset_probe --reader-envs <file>``). Prints ``WORKBENCH-READER-ENVS: OK|FAIL ...``.
If the probe fails, a value this run wrote is put back to empty (off). Undo at any time: clear "Reader
environments record" in Settings > Harness (empty is off).
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


def reader_envs(record: str, harness_py: str) -> int:
    import json

    from conclave_workbench.pages.settings.catalog import HARNESS_READER_ENVS_KEY, phase_a_defaults, workbench_schema
    from conclave_workbench.pages.settings.provenance import Scope, ScopeLayer
    from conclave_workbench.pages.settings.user_layer import (
        default_user_settings_path, load_user_layer, save_user_value)
    from conclave_workbench.seal.wiring import harness_reader_envs_reader

    schema = workbench_schema(None)
    path = default_user_settings_path()

    def layers():
        return (ScopeLayer(Scope.DEFAULT, phase_a_defaults(schema, None)), load_user_layer(path))

    target = os.path.abspath(record)
    if not os.path.isfile(target):
        print(f"WORKBENCH-READER-ENVS: FAIL {target} does not exist; harness.reader_envs left as it was")
        return 1
    current = harness_reader_envs_reader(schema, layers)()
    wrote = current is None
    if wrote:
        save_user_value(path, HARNESS_READER_ENVS_KEY, target)
    elif os.path.normcase(os.path.abspath(current)) != os.path.normcase(target):
        print(f"WORKBENCH-READER-ENVS: FAIL harness.reader_envs is already set to {current}, not {target}; "
              f"left unchanged (change it in Settings > Harness, or clear it and re-run)")
        return 1
    seen = harness_reader_envs_reader(schema, layers)()
    if seen is None or os.path.normcase(os.path.abspath(seen)) != os.path.normcase(target):
        print(f"WORKBENCH-READER-ENVS: FAIL the Workbench resolves harness.reader_envs to {seen!r}, not {target}")
        return 1
    r = subprocess.run([os.path.abspath(harness_py), "-m", "conclave_harness_adapters.preset_probe", "--reader-envs", seen],
                       capture_output=True, text=True, timeout=600)
    try:
        ok = r.returncode == 0 and isinstance(json.loads(r.stdout.strip().splitlines()[-1]), dict)
    except (ValueError, IndexError):
        ok = False
    if not ok:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
        if wrote:  # this run turned it on: put it back off, so a failure never leaves it on
            save_user_value(path, HARNESS_READER_ENVS_KEY, "")
        print(f"WORKBENCH-READER-ENVS: FAIL the preset probe with --reader-envs {seen} exited {r.returncode}: "
              f"{tail[0][:200]}; " + ("harness.reader_envs put back off" if wrote else
              "harness.reader_envs is STILL ON (an earlier install set it to this same file; this run did not "
              "change it). Readers may not start: clear \"Reader environments record\" in Settings > Harness to turn it off"))
        return 1
    print(f"WORKBENCH-READER-ENVS: OK {seen} (written to {path}; the preset probe reads it)")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reader-envs"]:
        sys.exit(reader_envs(sys.argv[2], sys.argv[3]))
    sys.exit(main(sys.argv[1]))
