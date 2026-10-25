#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    CostBreakdown,
    PlacedCell,
    Placement,
    Track,
    place,
    placement_result_to_dict,
    render_placement_svg,
    save_placement_litematic,
)


BUILD_DIRECTORY = REPOSITORY_ROOT / "examples" / "build"
NETLIST_PATH = BUILD_DIRECTORY / "adder4.json"
PLACEMENT_JSON_PATH = BUILD_DIRECTORY / "adder4.placement.json"
LITEMATIC_PATH = BUILD_DIRECTORY / "adder4.placement.litematic"
PLACEMENT_SVG_PATH = BUILD_DIRECTORY / "adder4.placement.svg"
PLACEMENT_HTML_PATH = BUILD_DIRECTORY / "adder4.placement.html"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synthesize, place, export, and visualize adder4"
    )
    parser.add_argument(
        "--visualize-only",
        action="store_true",
        help="render the existing placement JSON without rerunning placement",
    )
    args = parser.parse_args()

    if args.visualize_only:
        return _visualize_existing_placement()

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
    placement_data = placement_result_to_dict(graph.name, result)
    PLACEMENT_JSON_PATH.write_text(
        json.dumps(placement_data, indent=2) + "\n", encoding="utf-8"
    )
    _write_visualization(
        graph,
        result.placement,
        result.bounding_box,
        result.cost,
        result.iterations,
        result.accepted_moves,
    )
    save_placement_litematic(
        result.placement,
        LITEMATIC_PATH,
        name="adder4 placement",
        description=(
            "Final simulated-annealing placement of adder4 logic cells; "
            "routing not included."
        ),
    )
    print(f"Placed {len(result.placement.cells)} cells")
    print(f"Cost: {result.cost.total:g} ({result.cost})")
    print(f"JSON: {PLACEMENT_JSON_PATH}")
    print(f"SVG: {PLACEMENT_SVG_PATH}")
    print(f"HTML: {PLACEMENT_HTML_PATH}")
    print(f"Litematic: {LITEMATIC_PATH}")
    return 0


def _visualize_existing_placement() -> int:
    data = json.loads(PLACEMENT_JSON_PATH.read_text(encoding="utf-8"))
    graph = parse_yosys_json_file(NETLIST_PATH)
    library = load_cell_library(REPOSITORY_ROOT / "litematica-cells")
    physical_by_id = {cell.cell_id: cell for cell in library.cells}
    placement = Placement(
        cells={
            graph_cell: PlacedCell(
                graph_cell=graph_cell,
                physical_cell=physical_by_id[cell_data["cell_id"]],
                origin=tuple(cell_data["origin"]),
                layer_id=cell_data.get("layer", 0),
                track_id=cell_data.get("track", 0),
                z_offset=cell_data.get("z_offset", 0),
            )
            for graph_cell, cell_data in data["cells"].items()
        },
        track_pitch=data.get("track_pitch", 0),
        track_origin_z=data.get("track_origin_z", 0),
        tracks={
            int(track_id): Track(
                track_id=int(track_id),
                origin_z=track_data["origin_z"],
                width=track_data["width"],
                used_width=track_data["used_width"],
                original_width=track_data.get(
                    "original_width", data.get("track_pitch", track_data["width"])
                ),
            )
            for track_id, track_data in data.get("tracks", {}).items()
        },
    )
    bounds_data = data["bounding_box"]
    bounds = BoundingBox(
        size=tuple(bounds_data["size"]),
        origin=tuple(bounds_data["origin"]),
    )
    cost_data = data["cost"]
    cost = CostBreakdown(
        wire=cost_data["wire"],
        cross_track=cost_data.get("cross_track", 0),
        routing_constraint=cost_data["routing_constraint"],
        overlap=cost_data["overlap"],
        overflow=cost_data["overflow"],
        bounding_box=cost_data.get("bounding_box", cost_data.get("z_span", 0)),
    )
    _write_visualization(
        graph,
        placement,
        bounds,
        cost,
        data["iterations"],
        data["accepted_moves"],
    )
    print(f"SVG: {PLACEMENT_SVG_PATH}")
    print(f"HTML: {PLACEMENT_HTML_PATH}")
    return 0


def _write_visualization(
    graph,
    placement: Placement,
    bounds: BoundingBox,
    cost: CostBreakdown,
    iterations: int,
    accepted_moves: int,
) -> None:
    PLACEMENT_SVG_PATH.write_text(
        render_placement_svg(
            graph,
            placement,
            bounds,
            cost=cost,
            title="adder4 track-aware placement",
        ),
        encoding="utf-8",
    )
    PLACEMENT_HTML_PATH.write_text(
        _placement_html(
            graph,
            placement,
            bounds,
            cost,
            iterations,
            accepted_moves,
        ),
        encoding="utf-8",
    )


def _placement_html(
    graph,
    placement: Placement,
    bounds: BoundingBox,
    cost: CostBreakdown,
    iterations: int,
    accepted_moves: int,
) -> str:
    same_track = 0
    aligned = 0
    for edge in graph.data_edges:
        source = placement.cells.get(edge.src.node)
        destination = placement.cells.get(edge.dst.node)
        if source is None or destination is None:
            continue
        if source.track_id != destination.track_id:
            continue
        same_track += 1
        source_pin = next(
            pin for pin in source.physical_cell.pins if pin.name == edge.src.port
        )
        destination_pin = next(
            pin
            for pin in destination.physical_cell.pins
            if pin.name == edge.dst.port
        )
        source_z = source.origin[2] + source_pin.position[2]
        destination_z = destination.origin[2] + destination_pin.position[2]
        aligned += source_z == destination_z

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
<p>{len(placement.cells)} cells · box {bounds.size[0]} × {bounds.size[1]} × {bounds.size[2]} · {iterations:,} iterations · track pitch {placement.track_pitch}</p>
<p>Same-track connections: {same_track} · aligned: {aligned} · misaligned: {same_track - aligned}</p>
<table>
<thead><tr><th>Track</th><th>Original width</th><th>Used width</th><th>Final width</th><th>Utilization</th></tr></thead>
<tbody>{''.join(f'<tr><td>{track.track_id}</td><td>{track.original_width}</td><td>{track.used_width}</td><td>{track.width}</td><td>{track.utilization:.1%}</td></tr>' for track in placement.tracks.values())}</tbody>
</table>
<table>
<thead><tr><th>Total</th><th>Wire</th><th>Cross-track</th><th>Box</th><th>Routing</th><th>Overlap</th><th>Overflow</th><th>Accepted moves</th></tr></thead>
<tbody><tr><td>{cost.total:g}</td><td>{cost.wire:g}</td><td>{cost.cross_track:g}</td><td>{cost.bounding_box:g}</td><td>{cost.routing_constraint:g}</td><td>{cost.overlap:g}</td><td>{cost.overflow:g}</td><td>{accepted_moves:,}</td></tr></tbody>
</table>
<img src="adder4.placement.svg" alt="Orthographic views of the adder4 placement">
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
