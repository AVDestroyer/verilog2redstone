from __future__ import annotations

from pathlib import Path
import unittest

from verilog2redstone.cell_library import load_cell_library
from verilog2redstone.graph import parse_yosys_json_file
from verilog2redstone.placement import (
    AnnealingConfig,
    BoundingBox,
    PlacedCell,
    place,
    placement_bounding_box,
    placement_result_to_dict,
)
from tests.helpers import synth


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPlacementEndToEnd(unittest.TestCase):
    def test_places_tracks_and_serializes_combinational_design(self) -> None:
        graph = parse_yosys_json_file(synth("mux2.v", "mux2"))
        library = load_cell_library(REPO_ROOT / "litematica-cells")
        search_bounds = BoundingBox(size=(52, 18, 30))
        config = AnnealingConfig(
            iterations_per_cell=250,
            seed=20261011,
        )

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
            self.assertTrue(
                all(pin.position[0] == 0 for pin in placed_cell.physical_cell.inputs)
            )

        self.assertEqual(result.cost.routing_constraint, 0)
        self.assertEqual(result.cost.overlap, 0)
        self.assertEqual(result.cost.overflow, 0)
        self.assertGreater(result.cost.cross_track, 0)
        self.assertGreater(result.cost.bounding_box, 0)
        self.assertLessEqual(
            result.cost.total,
            result.initial_cost.total,
        )

        self.assertGreater(result.placement.track_pitch, 0)
        self.assertTrue(result.placement.tracks)
        tracks_by_layer: dict[int, set[int]] = {}
        for cell in result.placement.cells.values():
            layer_tracks = tracks_by_layer.setdefault(cell.layer_id, set())
            self.assertNotIn(cell.track_id, layer_tracks)
            layer_tracks.add(cell.track_id)
            track_start = result.placement.track_origin(cell.track_id)
            track_end = (
                track_start + result.placement.track_width(cell.track_id) - 2
            )
            depth = cell.physical_cell.schematic.dimensions[2]
            self.assertGreaterEqual(cell.origin[2], track_start)
            self.assertLessEqual(cell.origin[2] + depth - 1, track_end)

        for edge in graph.data_edges:
            source = result.placement.cells.get(edge.src.node)
            destination = result.placement.cells.get(edge.dst.node)
            if source is not None and destination is not None:
                self.assertLess(source.layer_id, destination.layer_id)
                if source.track_id == destination.track_id:
                    source_pin = next(
                        pin
                        for pin in source.physical_cell.pins
                        if pin.name == edge.src.port
                    )
                    destination_pin = next(
                        pin
                        for pin in destination.physical_cell.pins
                        if pin.name == edge.dst.port
                    )
                    self.assertEqual(
                        source.origin[2] + source_pin.position[2],
                        destination.origin[2] + destination_pin.position[2],
                    )

        for track_id, track in result.placement.tracks.items():
            track_cells = [
                cell
                for cell in result.placement.cells.values()
                if cell.track_id == track_id
            ]
            used_minimum = min(cell.origin[2] for cell in track_cells)
            used_maximum = max(
                cell.origin[2] + cell.physical_cell.schematic.dimensions[2]
                for cell in track_cells
            )
            self.assertEqual(track.origin_z, used_minimum)
            self.assertEqual(track.used_width, used_maximum - used_minimum)
            self.assertEqual(track.width, track.used_width + 1)
            self.assertLessEqual(track.width, track.original_width)

        cells_by_track: dict[int, list[PlacedCell]] = {}
        for cell in result.placement.cells.values():
            cells_by_track.setdefault(cell.track_id, []).append(cell)
        for cells in cells_by_track.values():
            ordered = sorted(cells, key=lambda cell: cell.origin[0])
            for first, second in zip(ordered, ordered[1:]):
                first_end = (
                    first.origin[0]
                    + first.physical_cell.schematic.dimensions[0]
                    - 1
                )
                self.assertLess(first_end + 1, second.origin[0])

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
        self.assertEqual(serialized["track_pitch"], result.placement.track_pitch)
        self.assertEqual(
            set(serialized["tracks"]),
            {str(track_id) for track_id in result.placement.tracks},
        )
        self.assertIn("bounding_box", serialized["cost"])
        self.assertIn("cross_track", serialized["cost"])
        for name, cell in result.placement.cells.items():
            serialized_cell = serialized["cells"][name]
            self.assertEqual(serialized_cell["layer"], cell.layer_id)
            self.assertEqual(serialized_cell["track"], cell.track_id)
            self.assertEqual(serialized_cell["z_offset"], cell.z_offset)


if __name__ == "__main__":
    unittest.main()
