"""
HDMI panel mount adapter for tv-stretch-node (build123d).

Fits standard HDMI panel cutout. Secures board to TV back.

Install: `python3 -m venv .venv-cad && .venv-cad/bin/pip install build123d`
"""

from __future__ import annotations

import os

from build123d import Box, Circle, extrude, Part, export_step


def hdmi_adapter() -> Part:
    frame = Box(45, 6, 35)
    
    for x in [-15, 15]:
        for z in [-12, 12]:
            hole = Circle(2.5)
            hole = extrude(hole, amount=-10)
            hole = hole.translate((x, 0, z))
            frame = frame - hole
    
    slot = Box(14, 10, 3)
    frame = frame - slot
    
    return frame


def export_all(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    export_step(hdmi_adapter(), os.path.join(out_dir, "hdmi_adapter.step"))


def export(path: str) -> None:
    export_step(hdmi_adapter(), path)


if __name__ == "__main__":
    export("exports/hdmi_adapter.step")