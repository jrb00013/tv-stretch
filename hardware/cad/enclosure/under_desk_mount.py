"""
Under-desk mount for tv-stretch-node (build123d).

Install: `pip install build123d`
"""

from build123d import Box, export_step

def under_desk_mount() -> "Part":
    from build123d import Part
    base = Box(80, 60, 15)
    return base

export_step(under_desk_mount(), "exports/under_desk_mount.step")