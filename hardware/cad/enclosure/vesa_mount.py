"""
VESA 75/100 mount adapter for tv-stretch-node (build123d).

Fits VESA 75 (75mm) and VESA 100 (100mm) patterns.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Circle, Extrude, Part, export_step


def vesa_mount() -> Part:
    plate = Box(100, 80, 4)
    
    for x in [-37.5, 37.5]:
        for z in [-30, 30]:
            hole = Circle(5)
            hole = Extrude(hole, amount=-12)
            hole = hole.translate((x, 0, z))
            plate = plate - hole
    
    body = Box(35, 12, 55)
    body = body.translate((0, 6, 0))
    plate = plate - body
    
    return plate


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(vesa_mount(), os.path.join(out_dir, "vesa75_mount.step"))


def export(path: str) -> None:
    export_step(vesa_mount(), path)


if __name__ == "__main__":
    export("exports/vesa75_mount.step")