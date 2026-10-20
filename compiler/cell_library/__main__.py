"""Validate and summarize the physical cell library."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .parse import load_cell_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "library",
        type=Path,
        nargs="?",
        default=Path("litematica-cells"),
        help="Cell-library directory (default: litematica-cells)",
    )
    args = parser.parse_args(argv)

    try:
        library = load_cell_library(args.library)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"cell library schema v{library.schema_version}")
    for cell in library.cells:
        inputs = ", ".join(f"{pin.name}@{pin.position}" for pin in cell.inputs)
        outputs = ", ".join(f"{pin.name}@{pin.position}" for pin in cell.outputs)
        label = cell.logical_type or cell.cell_id
        routing = ""
        if cell.routing is not None:
            routing = (
                f" turn={cell.routing.turn} "
                f"heading={cell.routing.input_heading}->{cell.routing.output_heading}"
            )
        print(
            f"  {label}: {cell.schematic.dimensions} "
            f"inputs=[{inputs}] "
            f"outputs=[{outputs}] output_strength={cell.output_signal_strength} "
            f"region_size={cell.schematic.region_signed_size}"
            f"{routing}"
        )
    print(
        f"  rail reach: {library.max_unbuffered_rail_distance} blocks; "
        f"routing objectives: {', '.join(library.routing_objectives)}"
    )
    if library.deferred_assets:
        print(f"  deferred assets: {len(library.deferred_assets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
