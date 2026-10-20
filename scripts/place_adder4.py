#!/usr/bin/env python3
"""Synthesize and place the combinational adder4 example."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from verilog2redstone.cell_library import load_cell_library  # noqa: E402
from verilog2redstone.graph import parse_yosys_json_file  # noqa: E402
from verilog2redstone.placement import (  # noqa: E402
    AnnealingConfig,
    BoundingBox,
    place,
    placement_result_to_dict,
)


BUILD_DIRECTORY = REPOSITORY_ROOT / "examples" / "build"
NETLIST_PATH = BUILD_DIRECTORY / "adder4.json"
PLACEMENT_JSON_PATH = BUILD_DIRECTORY / "adder4.placement.json"


def main() -> int:
    subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts" / "synth.sh"),
            str(REPOSITORY_ROOT / "examples" / "adder4.v"),
            "adder4",
            str(NETLIST_PATH),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )

    graph = parse_yosys_json_file(NETLIST_PATH)
    library = load_cell_library(REPOSITORY_ROOT / "litematica-cells")
    bounds = BoundingBox(size=(160, 28, 120))
    result = place(
        graph,
        library,
        bounds,
        AnnealingConfig(
            iterations_per_cell=5_000,
            seed=20261011,
            trace_interval=500,
        ),
    )

    if (
        result.cost.routing_constraint != 0
        or result.cost.overlap != 0
        or result.cost.overflow != 0
    ):
        raise RuntimeError(
            "placer did not find a legal adder4 placement: "
            f"routing_constraint={result.cost.routing_constraint:g}, "
            f"overlap={result.cost.overlap:g}, "
            f"overflow={result.cost.overflow:g}"
        )

    BUILD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    PLACEMENT_JSON_PATH.write_text(
        json.dumps(
            placement_result_to_dict(graph.name, result), indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Placed {len(result.placement.cells)} cells")
    print(f"Cost: {result.cost.total:g} ({result.cost})")
    print(f"JSON: {PLACEMENT_JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
