"""
Stackable case for multiple tv-stretch-nodes (build123d).

Daisy-chain mounting for 2+ zones.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Part, export_step


def stackable_case() -> Part:
    outer = Box(86, 46, 24)
    inner = Box(82, 42, 20)
    inner = inner.translate((0, 0, 2))
    shell = outer - inner
    
    for x in [-30, 30]:
        slot = Box(5, 38, 2)
        slot = slot.translate((x, 0, 0))
        shell = shell + slot
    
    return shell


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(stackable_case(), os.path.join(out_dir, "stackable_case.step"))


def export(path: str) -> None:
    export_step(stackable_case(), path)


if __name__ == "__main__":
    export("exports/stackable_case.step")