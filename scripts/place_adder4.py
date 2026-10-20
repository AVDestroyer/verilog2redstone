#!/usr/bin/env python3
"""Synthesize, place, and visualize the combinational adder4 example."""

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
    PlacementResult,
    place,
    placement_result_to_dict,
    render_placement_svg,
)


BUILD_DIRECTORY = REPOSITORY_ROOT / "examples" / "build"
NETLIST_PATH = BUILD_DIRECTORY / "adder4.json"
PLACEMENT_JSON_PATH = BUILD_DIRECTORY / "adder4.placement.json"
PLACEMENT_SVG_PATH = BUILD_DIRECTORY / "adder4.placement.svg"
PLACEMENT_HTML_PATH = BUILD_DIRECTORY / "adder4.placement.html"


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
    PLACEMENT_SVG_PATH.write_text(
        render_placement_svg(
            graph,
            result.placement,
            result.bounding_box,
            cost=result.cost,
            title="adder4 simulated-annealing placement",
        ),
        encoding="utf-8",
    )
    PLACEMENT_HTML_PATH.write_text(
        _placement_html(result), encoding="utf-8"
    )

    print(f"Placed {len(result.placement.cells)} cells")
    print(f"Cost: {result.cost.total:g} ({result.cost})")
    print(f"JSON: {PLACEMENT_JSON_PATH}")
    print(f"SVG:  {PLACEMENT_SVG_PATH}")
    print(f"HTML: {PLACEMENT_HTML_PATH}")
    return 0


def _placement_html(result: PlacementResult) -> str:
    cost = result.cost
    bounds = result.bounding_box
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>adder4 placement</title>
<style>
body {{ margin: 2rem; font-family: system-ui, sans-serif; color: #0f172a; background: #f8fafc; }}
table {{ border-collapse: collapse; background: white; margin-bottom: 1rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .5rem .75rem; text-align: right; }}
th {{ background: #e2e8f0; }}
img {{ width: 100%; background: white; border: 1px solid #cbd5e1; }}
</style>
</head>
<body>
<h1>adder4 placement</h1>
<p>{len(result.placement.cells)} cells · box {bounds.size[0]} × {bounds.size[1]} × {bounds.size[2]} · {result.iterations:,} iterations</p>
<table>
<thead><tr><th>Total</th><th>Wire</th><th>Z span</th><th>Routing</th><th>Overlap</th><th>Overflow</th><th>Accepted moves</th></tr></thead>
<tbody><tr><td>{cost.total:g}</td><td>{cost.wire:g}</td><td>{cost.z_span:g}</td><td>{cost.routing_constraint:g}</td><td>{cost.overlap:g}</td><td>{cost.overflow:g}</td><td>{result.accepted_moves:,}</td></tr></tbody>
</table>
<img src="adder4.placement.svg" alt="Orthographic views of the adder4 placement">
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
