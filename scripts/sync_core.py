#!/usr/bin/env python3
"""Sync the shared tapayoka_pi_core package into the Pico repo."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "tapayoka_pi_core" / "src" / "tapayoka_pi_core"
DEST = ROOT / "src" / "tapayoka_pi_core"


def main() -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"source package not found: {SOURCE}")

    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST)
    print(f"synced {SOURCE} -> {DEST}")


if __name__ == "__main__":
    main()
