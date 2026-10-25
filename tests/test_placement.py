from __future__ import annotations

from pathlib import Path
import unittest

from verilog2redstone.cell_library import load_cell_library
from verilog2redstone.graph import parse_yosys_json_file
from verilog2redstone.placement import (
    AnnealingConfig,
    BoundingBox,
    place,
    placement_bounding_box,
    placement_result_to_dict,
)
from tests.helpers import synth


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPlacementEndToEnd(unittest.TestCase):
    def test_places_and_serializes_small_combinational_design(self) -> None:
        graph = parse_yosys_json_file(synth("and2.v", "and2"))
        library = load_cell_library(REPO_ROOT / "litematica-cells")
        search_bounds = BoundingBox(size=(30, 12, 12))
        config = AnnealingConfig(iterations_per_cell=100, seed=7)

        result = place(graph, library, search_bounds, config)

        graph_cells = {cell.name: cell for cell in graph.comb_cells}
        self.assertEqual(set(result.placement.cells), set(graph_cells))
        for name, placed_cell in result.placement.cells.items():
            graph_cell = graph_cells[name]
            self.assertEqual(
                placed_cell.physical_cell.logical_type,
                graph_cell.yosys_type,
            )
            self.assertEqual(
                {pin.name: pin.direction for pin in placed_cell.physical_cell.pins},
                graph_cell.port_directions,
            )

        self.assertEqual(result.cost.routing_constraint, 0)
        self.assertEqual(result.cost.overlap, 0)
        self.assertEqual(result.cost.overflow, 0)

        calculated_bounds = placement_bounding_box(result.placement)
        self.assertEqual(result.bounding_box, calculated_bounds)
        self.assertEqual(result.bounding_box.origin, (0, 0, 0))
        self.assertEqual(
            tuple(
                max(
                    cell.origin[axis]
                    + cell.physical_cell.schematic.dimensions[axis]
                    for cell in result.placement.cells.values()
                )
                for axis in range(3)
            ),
            result.bounding_box.size,
        )

        serialized = placement_result_to_dict(graph.name, result)
        self.assertEqual(
            serialized["bounding_box"],
            {"origin": [0, 0, 0], "size": list(result.bounding_box.size)},
        )
        self.assertEqual(set(serialized["cells"]), set(graph_cells))


if __name__ == "__main__":
    unittest.main()
