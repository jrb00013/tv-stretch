"""
DIN rail mount for tv-stretch-node (build123d).

Fits 35mm DIN rail. Snap-lock design.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Circle, Extrude, Part, export_step


def din_rail_mount() -> Part:
    body = Box(70, 10, 45)
    
    lip = Box(5, 12, 35)
    lip = lip.translate((-35, 0, 0))
    part = body + lip
    
    clip = Box(8, 4, 30)
    clip = clip.translate((32, 2, 0))
    part = part + clip
    
    for x in [-20, 0, 20]:
        hole = Circle(3)
        hole = Extrude(hole, amount=-12)
        hole = hole.translate((x, 0, 18))
        part = part - hole
    
    return part


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(din_rail_mount(), os.path.join(out_dir, "din_rail_mount.step"))


def export(path: str) -> None:
    export_step(din_rail_mount(), path)


if __name__ == "__main__":
    export("exports/din_rail_mount.step")