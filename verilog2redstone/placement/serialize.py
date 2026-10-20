"""Serialization helpers for placement results."""

from __future__ import annotations

from .model import CostBreakdown, Placement, PlacementResult


def placement_result_to_dict(
    module_name: str,
    result: PlacementResult,
) -> dict[str, object]:
    """Convert a placement result, including its trace, to JSON-safe data."""

    display_labels = {
        graph_cell: f"C{index}"
        for index, graph_cell in enumerate(
            sorted(result.placement.cells), start=1
        )
    }
    return {
        "module": module_name,
        "bounding_box": {
            "origin": list(result.bounding_box.origin),
            "size": list(result.bounding_box.size),
        },
        "seed": result.seed,
        "iterations": result.iterations,
        "accepted_moves": result.accepted_moves,
        "initial_cost": _cost_as_dict(result.initial_cost),
        "cost": _cost_as_dict(result.cost),
        "initial_cells": _placement_cells_as_dict(
            result.initial_placement, display_labels
        ),
        "cells": _placement_cells_as_dict(result.placement, display_labels),
        "trace": [
            {
                "iteration": entry.iteration,
                "temperature": entry.temperature,
                "current_cost": _cost_as_dict(entry.current_cost),
                "best_cost": _cost_as_dict(entry.best_cost),
                "accepted": entry.accepted,
                "move": entry.move,
            }
            for entry in result.trace
        ],
    }


def _placement_cells_as_dict(
    placement: Placement,
    display_labels: dict[str, str],
) -> dict[str, object]:
    return {
        name: {
            "display_label": display_labels[name],
            "cell_id": cell.physical_cell.cell_id,
            "logical_type": cell.physical_cell.logical_type,
            "origin": list(cell.origin),
            "dimensions": list(cell.physical_cell.schematic.dimensions),
            "pins": {
                pin.name: {
                    "direction": pin.direction,
                    "position": [
                        origin + offset
                        for origin, offset in zip(cell.origin, pin.position)
                    ],
                }
                for pin in cell.physical_cell.pins
            },
        }
        for name, cell in placement.cells.items()
    }


def _cost_as_dict(cost: CostBreakdown) -> dict[str, float]:
    return {
        "total": cost.total,
        "wire": cost.wire,
        "routing_constraint": cost.routing_constraint,
        "overlap": cost.overlap,
        "overflow": cost.overflow,
        "z_span": cost.z_span,
    }
