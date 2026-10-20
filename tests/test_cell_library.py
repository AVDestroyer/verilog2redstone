"""Behavioral contracts for the physical cell library."""

from __future__ import annotations

from pathlib import Path
import unittest

from compiler.cell_library import load_cell_library
from compiler.graph.cells import COMB_CELLS


LIBRARY_ROOT = Path(__file__).resolve().parents[1] / "litematica-cells"


class TestCellLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = load_cell_library(LIBRARY_ROOT)

    def test_cells_and_routing_policy(self) -> None:
        self.assertEqual(
            {cell.logical_type for cell in self.library.logic_cells}, COMB_CELLS
        )
        self.assertEqual(
            {cell.routing.turn for cell in self.library.routing_cells},
            {"straight", "left", "right"},
        )
        self.assertEqual(self.library.max_unbuffered_rail_distance, 8)
        self.assertEqual(
            self.library.routing_objectives[0], "minimize_direction_changes"
        )

    def test_reported_pin_coordinates(self) -> None:
        expected = {
            "$_NOT_": ([(0, 1, 0)], [(3, 2, 0)]),
            "$_OR_": ([(0, 1, 2), (0, 4, 1)], [(3, 4, 2)]),
            "$_NAND_": ([(0, 2, 1), (5, 5, 1)], [(8, 5, 1)]),
            "straight": ([(0, 1, 1)], [(3, 1, 2)]),
            "left": ([(0, 1, 3)], [(3, 1, 0)]),
            "right": ([(0, 1, 1)], [(3, 1, 4)]),
        }
        for cell in self.library.cells:
            key = cell.logical_type or cell.routing.turn  # type: ignore[union-attr]
            inputs, outputs = expected[key]
            self.assertEqual([pin.position for pin in cell.inputs], inputs)
            self.assertEqual([pin.position for pin in cell.outputs], outputs)

    def test_output_signal_strengths(self) -> None:
        expected = {
            "$_NOT_": 8,
            "$_OR_": 6,
            "$_NAND_": 5,
            "straight": 8,
            "left": 6,
            "right": 6,
        }
        for cell in self.library.cells:
            key = cell.logical_type or cell.routing.turn  # type: ignore[union-attr]
            self.assertEqual(cell.output_signal_strength, expected[key])

    def test_cell_coordinates_map_to_minecraft_axes(self) -> None:
        expected_steps = {
            (1, 0, 0): (-1, 0, 0),
            (0, 1, 0): (0, 1, 0),
            (0, 0, 1): (0, 0, -1),
        }
        for cell in self.library.cells:
            origin = cell.cell_to_schematic((0, 0, 0))
            for local_step, expected_step in expected_steps.items():
                adjacent = cell.cell_to_schematic(local_step)
                actual_step = tuple(
                    adjacent[index] - origin[index] for index in range(3)
                )
                self.assertEqual(actual_step, expected_step)


if __name__ == "__main__":
    unittest.main()
