"""
Wall mount bracket for tv-stretch-node (build123d).

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Circle, Extrude, Part, Plane, export_step


def wall_mount() -> Part:
    base = Box(80, 10, 60)
    hook = Box(15, 8, 20)
    hook = hook.translate((-32, 5, -20))
    part = base + hook
    
    for x in [-25, 25]:
        hole = Circle(4)
        hole = Extrude(hole, amount=-10)
        hole = hole.translate((x, 0, 0))
        part = part - hole
    
    return part


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(wall_mount(), os.path.join(out_dir, "wall_bracket.step"))


def export(path: str) -> None:
    export_step(wall_mount(), path)


if __name__ == "__main__":
    export("exports/wall_bracket.step")