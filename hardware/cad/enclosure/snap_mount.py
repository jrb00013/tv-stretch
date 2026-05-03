"""
Snap mount for tv-stretch-node (build123d).

No screws needed, press-fit.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Part, export_step


def snap_mount() -> Part:
    base = Box(80, 42, 20)
    
    for x in [-28, 28]:
        lip = Box(4, 6, 3)
        lip = lip.translate((x, 0, 10))
        base = base + lip
    
    return base


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(snap_mount(), os.path.join(out_dir, "snap_mount.step"))


def export(path: str) -> None:
    export_step(snap_mount(), path)


if __name__ == "__main__":
    export("exports/snap_mount.step")