#!/usr/bin/env python3
"""Synthesize, place, and visualize the combinational mux2 example."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from compiler.cell_library import load_cell_library  # noqa: E402
from compiler.graph import parse_yosys_json_file  # noqa: E402
from compiler.placement import (  # noqa: E402
    AnnealingConfig,
    BoundingBox,
    place,
    placement_result_to_dict,
    render_placement_svg,
)

BUILD_DIRECTORY = REPOSITORY_ROOT / "examples" / "build"
NETLIST_PATH = BUILD_DIRECTORY / "mux2.json"
PLACEMENT_JSON_PATH = BUILD_DIRECTORY / "mux2.placement.json"
PLACEMENT_SVG_PATH = BUILD_DIRECTORY / "mux2.placement.svg"


def main() -> int:
    subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts" / "synth.sh"),
            str(REPOSITORY_ROOT / "examples" / "mux2.v"),
            "mux2",
            str(NETLIST_PATH),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )

    graph = parse_yosys_json_file(NETLIST_PATH)
    library = load_cell_library(REPOSITORY_ROOT / "litematica-cells")
    bounds = BoundingBox(size=(52, 18, 30))
    result = place(
        graph,
        library,
        bounds,
        AnnealingConfig(
            iterations_per_cell=20_000,
            seed=20261011,
            trace_interval=100,
        ),
    )

    if (
        result.cost.routing_constraint != 0
        or result.cost.overlap != 0
        or result.cost.overflow != 0
    ):
        raise RuntimeError(
            "placer did not find a legal mux2 placement: "
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
    PLACEMENT_SVG_PATH.write_text(
        render_placement_svg(
            graph,
            result.placement,
            result.bounding_box,
            cost=result.cost,
            title="mux2 simulated-annealing placement",
        ),
        encoding="utf-8",
    )

    print(f"Placed {len(result.placement.cells)} cells")
    print(f"Cost: {result.cost.total:g} ({result.cost})")
    print(f"JSON: {PLACEMENT_JSON_PATH}")
    print(f"SVG:  {PLACEMENT_SVG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
