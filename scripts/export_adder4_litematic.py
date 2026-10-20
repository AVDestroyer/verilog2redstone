#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from verilog2redstone.cell_library import load_cell_library  # noqa: E402
from verilog2redstone.placement import (  # noqa: E402
    PlacedCell,
    Placement,
    save_placement_litematic,
)


PLACEMENT_PATH = (
    REPOSITORY_ROOT / "examples" / "build" / "adder4.placement.json"
)
OUTPUT_PATH = PLACEMENT_PATH.with_suffix(".litematic")


def main() -> int:
    data = json.loads(PLACEMENT_PATH.read_text(encoding="utf-8"))
    library = load_cell_library(REPOSITORY_ROOT / "litematica-cells")
    physical_by_id = {cell.cell_id: cell for cell in library.cells}
    placement = Placement(
        cells={
            graph_cell: PlacedCell(
                graph_cell=graph_cell,
                physical_cell=physical_by_id[cell_data["cell_id"]],
                origin=tuple(cell_data["origin"]),
            )
            for graph_cell, cell_data in data["cells"].items()
        }
    )
    save_placement_litematic(
        placement,
        OUTPUT_PATH,
        name="adder4 placement",
        description=(
            "Final simulated-annealing placement of adder4 logic cells; "
            "routing not included."
        ),
    )
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
