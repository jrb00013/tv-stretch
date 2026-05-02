# KiCad exports

## Gerbers

From KiCad **pcbnew**:

1. **File → Fabrication Outputs → Gerbers (.ger)**
2. Include: `F.Cu`, `B.Cu`, `Edge.Cuts`, `F.Mask`, `B.Mask`, `F.Silkscreen`, `B.Silkscreen`
3. **Drill Files** separately if required by fab

Optional: `kicad-cli pcb export gerbers ...` (KiCad 7+ CLI).

## STEP (PCB 3D)

**File → Export → STEP** with component models enabled once footprints are placed.

Save as `exports/pcb.step` (gitignored if large) or attach to releases.

## Netlist

Use **Tools → Update PCB from Schematic** after completing symbols and footprints.
