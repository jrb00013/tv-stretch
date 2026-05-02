#!/usr/bin/env python3
"""Generate STEP files under hardware/cad/enclosure/exports/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENC = ROOT / "hardware" / "cad" / "enclosure"
OUT_DIR = ENC / "exports"


def main() -> int:
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "tv_stretch_enclosure", ENC / "tv_stretch_enclosure.py"
        )
        if spec is None or spec.loader is None:
            print("Could not load tv_stretch_enclosure.py", file=sys.stderr)
            return 1
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except ImportError as e:
        print(
            "build123d not installed. Try: pip install build123d\n"
            "On Debian/Ubuntu you may need: libocct-* dev packages.",
            file=sys.stderr,
        )
        print(e, file=sys.stderr)
        return 1

    if hasattr(mod, "export_all"):
        mod.export_all(str(OUT_DIR))
        print(f"Wrote STEP under {OUT_DIR}")
    else:
        out = OUT_DIR / "enclosure.step"
        out.parent.mkdir(parents=True, exist_ok=True)
        mod.export(str(out))
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
