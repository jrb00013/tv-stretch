"""
Cable clip for tv-stretch-node (build123d).

Manages HDMI and USB-C cables.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Part, export_step


def cable_clip() -> Part:
    clip = Box(15, 30, 25)
    groove = Box(20, 4, 12)
    groove = groove.translate((0, 0, 15))
    shell = clip - groove
    
    tab = Box(8, 3, 8)
    tab = tab.translate((0, -14, 0))
    shell = shell + tab
    
    return shell


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(cable_clip(), os.path.join(out_dir, "cable_clip.step"))


def export(path: str) -> None:
    export_step(cable_clip(), path)


if __name__ == "__main__":
    export("exports/cable_clip.step")