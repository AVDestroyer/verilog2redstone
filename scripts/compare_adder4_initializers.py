#!/usr/bin/env python3
"""Run and report topological initialization on adder4."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from compiler.cell_library import load_cell_library  # noqa: E402
from compiler.graph import ModuleGraph, parse_yosys_json_file  # noqa: E402
from compiler.placement import (  # noqa: E402
    AnnealingConfig,
    BoundingBox,
    CostBreakdown,
    InitializationStrategy,
    PlacementResult,
    place,
    placement_result_to_dict,
    render_placement_svg,
)


BUILD_DIRECTORY = REPOSITORY_ROOT / "examples" / "build"
NETLIST_PATH = BUILD_DIRECTORY / "adder4.json"
REPORT_PATH = BUILD_DIRECTORY / "adder4.initializer-comparison.html"
SUMMARY_PATH = BUILD_DIRECTORY / "adder4.initializer-comparison.json"
STRATEGIES: tuple[InitializationStrategy, ...] = ("topological",)


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
    results: dict[str, PlacementResult] = {}
    elapsed_seconds: dict[str, float] = {}

    for strategy in STRATEGIES:
        started = perf_counter()
        result = place(
            graph,
            library,
            bounds,
            AnnealingConfig(
                iterations_per_cell=5_000,
                initialization=strategy,
                seed=20261011,
                trace_interval=500,
            ),
        )
        elapsed_seconds[strategy] = perf_counter() - started
        results[strategy] = result
        _write_strategy_artifacts(graph, bounds, result)

    SUMMARY_PATH.write_text(
        json.dumps(
            {
                "module": graph.name,
                "bounding_box": list(bounds.size),
                "seed": 20261011,
                "iterations_per_cell": 5_000,
                "results": {
                    strategy: {
                        "elapsed_seconds": elapsed_seconds[strategy],
                        "initial_cost": _cost_as_dict(
                            results[strategy].initial_cost
                        ),
                        "final_cost": _cost_as_dict(results[strategy].cost),
                        "accepted_moves": results[strategy].accepted_moves,
                    }
                    for strategy in STRATEGIES
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        _report_html(results, elapsed_seconds), encoding="utf-8"
    )

    for strategy in STRATEGIES:
        result = results[strategy]
        print(
            f"{strategy:11} initial={result.initial_cost.total:g} "
            f"final={result.cost.total:g} "
            f"elapsed={elapsed_seconds[strategy]:.2f}s"
        )
    print(f"Report:     {REPORT_PATH}")
    print(f"Summary:    {SUMMARY_PATH}")

    illegal = [
        strategy
        for strategy, result in results.items()
        if result.cost.routing_constraint != 0
        or result.cost.overlap != 0
        or result.cost.overflow != 0
    ]
    if illegal:
        raise RuntimeError(
            "placement ended with illegal states: "
            + ", ".join(illegal)
        )
    return 0


def _write_strategy_artifacts(
    graph: ModuleGraph,
    bounds: BoundingBox,
    result: PlacementResult,
) -> None:
    prefix = f"adder4.{result.initialization}"
    (BUILD_DIRECTORY / f"{prefix}.placement.json").write_text(
        json.dumps(
            placement_result_to_dict(graph.name, bounds, result), indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (BUILD_DIRECTORY / f"{prefix}.initial.svg").write_text(
        render_placement_svg(
            graph,
            result.initial_placement,
            bounds,
            cost=result.initial_cost,
            title=f"adder4 {result.initialization} initialization",
        ),
        encoding="utf-8",
    )
    (BUILD_DIRECTORY / f"{prefix}.final.svg").write_text(
        render_placement_svg(
            graph,
            result.placement,
            bounds,
            cost=result.cost,
            title=f"adder4 {result.initialization} final placement",
        ),
        encoding="utf-8",
    )


def _cost_as_dict(cost: CostBreakdown) -> dict[str, float]:
    return {
        "total": cost.total,
        "wire": cost.wire,
        "routing_constraint": cost.routing_constraint,
        "overlap": cost.overlap,
        "overflow": cost.overflow,
    }


def _report_html(
    results: dict[str, PlacementResult],
    elapsed_seconds: dict[str, float],
) -> str:
    rows = []
    figures = []
    for strategy in STRATEGIES:
        result = results[strategy]
        rows.append(
            "<tr>"
            f"<th>{strategy}</th>"
            f"<td>{result.initial_cost.total:g}</td>"
            f"<td>{result.initial_cost.wire:g}</td>"
            f"<td>{result.initial_cost.routing_constraint:g}</td>"
            f"<td>{result.initial_cost.overlap:g}</td>"
            f"<td>{result.initial_cost.overflow:g}</td>"
            f"<td>{result.cost.total:g}</td>"
            f"<td>{result.cost.wire:g}</td>"
            f"<td>{result.cost.routing_constraint:g}</td>"
            f"<td>{result.cost.overlap:g}</td>"
            f"<td>{result.cost.overflow:g}</td>"
            f"<td>{result.accepted_moves}</td>"
            f"<td>{elapsed_seconds[strategy]:.2f}s</td>"
            "</tr>"
        )
        figures.append(
            f"<section><h2>{strategy.title()}</h2>"
            '<div class="figures">'
            f'<figure><figcaption>Initial</figcaption><img src="adder4.{strategy}.initial.svg"></figure>'
            f'<figure><figcaption>Final</figcaption><img src="adder4.{strategy}.final.svg"></figure>'
            "</div></section>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>adder4 topological placement report</title>
<style>
body {{ margin: 2rem; font-family: system-ui, sans-serif; color: #0f172a; background: #f8fafc; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ border: 1px solid #cbd5e1; padding: .5rem; text-align: right; }}
thead th, tbody th {{ background: #e2e8f0; }}
.figures {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
figure {{ margin: 0; }}
figcaption {{ margin-bottom: .4rem; font-weight: 700; }}
img {{ width: 100%; background: white; border: 1px solid #cbd5e1; }}
</style>
</head>
<body>
<h1>adder4 topological placement report</h1>
<p>160 × 28 × 120 box, seed 20261011, and 150,000 iterations.</p>
<table>
<thead><tr><th rowspan="2">Initializer</th><th colspan="5">Initial</th><th colspan="5">Final</th><th rowspan="2">Accepted</th><th rowspan="2">Runtime</th></tr>
<tr><th>Total</th><th>Wire</th><th>Routing</th><th>Overlap</th><th>Overflow</th><th>Total</th><th>Wire</th><th>Routing</th><th>Overlap</th><th>Overflow</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
{''.join(figures)}
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
