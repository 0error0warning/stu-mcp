#!/usr/bin/env python3
"""Run the shared reviewed-timetable converter with Python 3.11+.

An exported skill bundles the package's converter alongside this runner. In the
source tree or installed package, use that same implementation directly. Neither
path imports third-party dependencies or reads school services.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    script = Path(__file__).resolve()
    core = script.with_name("_timetable_core.py")
    if not core.is_file():
        core = script.parent / "../../../features/timetable/export.py"
    if not core.is_file():
        raise SystemExit("Timetable converter missing; export the complete skill with stu-mcp skill-export.")
    return runpy.run_path(str(core))["main"](argv)


if __name__ == "__main__":
    raise SystemExit(main())
