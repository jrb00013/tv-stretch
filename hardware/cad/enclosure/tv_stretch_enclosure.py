"""
Hollow enclosure for tv-stretch-node (build123d).

Writes `enclosure.step` (hollow shell). Optional split halves require manual CAD
or FreeCAD; see docs/MECHANICAL.md.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Part, export_step

OUTER_L = 86.0
OUTER_W = 46.0
OUTER_H = 24.0
WALL = 2.0
FLOOR = 2.0
LID = 1.8


def enclosure_shell() -> Part:
    outer = Box(OUTER_L, OUTER_W, OUTER_H)
    inner_l = OUTER_L - 2 * WALL
    inner_w = OUTER_W - 2 * WALL
    inner_h = OUTER_H - FLOOR - LID
    cavity = Box(inner_l, inner_w, inner_h)
    cavity = cavity.translate((WALL, WALL, FLOOR))
    return outer - cavity


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(enclosure_shell(), os.path.join(out_dir, "enclosure.step"))


def export(path: str) -> None:
    export_step(enclosure_shell(), path)


if __name__ == "__main__":
    export("exports/enclosure.step")
