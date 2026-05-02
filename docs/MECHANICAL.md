# Mechanical — enclosure

## Concept

**Inline puck** enclosure: PCB + HDMI **receptacle** faces one direction; **short pigtail** or second HDMI exits toward the TV. Two **shell halves** (top/bottom) with **snap clips** or **M2 standoffs** (optional).

## Files

| File | Description |
|------|-------------|
| `hardware/cad/enclosure/tv_stretch_enclosure.py` | build123d source (Python) |
| `hardware/cad/enclosure/exports/enclosure.step` | Hollow shell (outer box minus cavity) for printing / machining |

## Regenerating STEP

```bash
pip install build123d
python3 scripts/generate_enclosure_step.py
```

Default outer box (placeholder geometry) targets ~**80 × 40 × 22 mm**; edit parameters in the script to match your PCB.

## 3D printing

- **Orientation:** Largest flat face on build plate; avoid overhangs on clip features.
- **Tolerance:** Add **0.25–0.4 mm** clearance between shell and connector bodies.
- **Material:** PETG or ABS for heat near TV vents; PLA acceptable for prototypes.

## Strain relief

Use a **zip tie channel** around the HDMI pigtail exit (parametric in script) or heat-shrink anchor.

## KiCad PCB STEP

When the PCB is routed in KiCad: **File → Export → STEP** (include components). Store under `hardware/kicad/tv-stretch-node/exports/` if desired.
