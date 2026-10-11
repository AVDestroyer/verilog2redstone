"""End-to-end tests for synthesis and the sequential-aware graph IR."""

from __future__ import annotations

import subprocess
import unittest

from compiler.graph import CombCycleError, parse_yosys_json_file
from compiler.graph.cells import COMB_CELLS, REGISTER_YOSYS_TYPE
from tests.helpers import synth


class TestExampleGraphs(unittest.TestCase):
    def test_adder_maps_to_v1_gates_and_preserves_buses(self) -> None:
        graph = parse_yosys_json_file(synth("adder4.v", "adder4"))
        ports = {
            port.name: port
            for port in graph.primary_inputs + graph.primary_outputs
        }
        self.assertEqual(
            {name: ports[name].width for name in ("a", "b", "sum", "cout")},
            {"a": 4, "b": 4, "sum": 4, "cout": 1},
        )
        self.assertTrue(
            {cell.yosys_type for cell in graph.comb_cells}.issubset(COMB_CELLS)
        )
        self.assertEqual(
            {edge.dst.bit for edge in graph.data_edges if edge.dst.node == "sum"},
            {0, 1, 2, 3},
        )

    def test_register_feedback_is_split_at_state_boundary(self) -> None:
        graph = parse_yosys_json_file(
            synth("minimal_toggle.v", "minimal_toggle")
        )
        self.assertEqual(len(graph.state_cells), 1)
        self.assertEqual(graph.state_cells[0].yosys_type, REGISTER_YOSYS_TYPE)
        self.assertEqual({edge.role for edge in graph.control_edges}, {"clock"})
        self.assertTrue(any(edge.src.port == "Q" for edge in graph.data_edges))
        self.assertTrue(any(edge.dst.port == "D" for edge in graph.data_edges))
        self.assertFalse(graph.has_comb_cycle())

    def test_combinational_loop_is_rejected(self) -> None:
        path = synth("comb_loop.v", "comb_loop")
        with self.assertRaises(CombCycleError):
            parse_yosys_json_file(path)

    def test_level_latch_is_not_supported(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            synth("level_latch.v", "level_latch")


if __name__ == "__main__":
    unittest.main()
