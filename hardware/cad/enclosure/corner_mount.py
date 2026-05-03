"""
Corner mount for tv-stretch-node (build123d).
"""
from build123d import Box, export_step

def corner_mount():
    return Box(60, 60, 20)

export_step(corner_mount(), "exports/corner_mount.step")