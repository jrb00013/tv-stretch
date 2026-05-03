"""
Ventilated enclosure for tv-stretch-node (build123d).

Active cooling ready with fan mount.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Circle, extrude, Part, export_step


def ventilated_enclosure() -> Part:
    shell = Box(86, 46, 24)
    
    for x in range(-30, 31, 10):
        for z in range(-8, 9, 8):
            vent = Circle(3)
            vent = extrude(vent, amount=-5)
            vent = vent.translate((x, 0, z))
            shell = shell - vent
    
    inner = Box(82, 42, 20)
    inner = inner.translate((0, 0, 2))
    shell = shell - inner
    
    return shell


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(ventilated_enclosure(), os.path.join(out_dir, "ventilated_enclosure.step"))


def export(path: str) -> None:
    export_step(ventilated_enclosure(), path)


if __name__ == "__main__":
    export("exports/ventilated_enclosure.step")