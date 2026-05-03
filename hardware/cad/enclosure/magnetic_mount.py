"""
Magnetic mount for tv-stretch-node (build123d).

30mm x 5mm neodymium magnet pocket.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Part, export_step


def magnetic_mount() -> Part:
    base = Box(70, 15, 50)
    pocket = Box(32, 10, 6)
    pocket = pocket.translate((0, 5, 0))
    shell = base - pocket
    
    return shell


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(magnetic_mount(), os.path.join(out_dir, "magnetic_mount.step"))


def export(path: str) -> None:
    export_step(magnetic_mount(), path)


if __name__ == "__main__":
    export("exports/magnetic_mount.step")