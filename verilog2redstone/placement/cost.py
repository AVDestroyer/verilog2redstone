from __future__ import annotations

from verilog2redstone.graph import ModuleGraph

from .model import BoundingBox, CostBreakdown, PlacedCell, Placement, Vec3


def placement_cost(
    graph: ModuleGraph,
    placement: Placement,
    bounds: BoundingBox,
    invalid_penalty: float,
    bounding_box_weight_per_cell: float = 0.5,
    cross_track_penalty: float = 100.0,
) -> CostBreakdown:
    """Evaluate wire length, routing legality, overlap, overflow, and size.

    Data edges involving primary I/O or constants are ignored because those
    endpoints do not yet have physical placements.
    """

    wire = 0.0
    cross_track_count = 0
    routing_constraint_count = 0
    for edge in graph.data_edges:
        source_cell = placement.cells.get(edge.src.node)
        destination_cell = placement.cells.get(edge.dst.node)
        if source_cell is None or destination_cell is None:
            continue
        source = _pin_position(source_cell, edge.src.port)
        destination = _pin_position(destination_cell, edge.dst.port)
        same_track = source_cell.track_id == destination_cell.track_id
        signed_dx = destination[0] - source[0]
        dx = abs(signed_dx)
        dy = abs(destination[1] - source[1])
        dz = abs(destination[2] - source[2])
        wire += dx + dy + 2
        if not same_track:
            cross_track_count += 1
        if signed_dx < 0 or dx < dy + 1 or (same_track and dz != 0):
            routing_constraint_count += 1

    placed_cells = tuple(placement.cells.values())
    overflow_count = sum(1 for cell in placed_cells if _overflows(cell, bounds))

    overlap_count = 0
    for index, first in enumerate(placed_cells):
        for second in placed_cells[index + 1 :]:
            if _violates_clearance(first, second):
                overlap_count += 1

    bounding_box_cost = 0.0
    if placed_cells:
        spans = tuple(
            max(
                cell.origin[axis] + cell.physical_cell.schematic.dimensions[axis]
                for cell in placed_cells
            )
            - min(cell.origin[axis] for cell in placed_cells)
            for axis in range(3)
        )
        bounding_box_cost = (
            sum(spans) * len(placed_cells) * bounding_box_weight_per_cell
        )

    return CostBreakdown(
        wire=wire,
        cross_track=cross_track_count * cross_track_penalty,
        routing_constraint=routing_constraint_count * invalid_penalty,
        overlap=overlap_count * invalid_penalty,
        overflow=overflow_count * invalid_penalty,
        bounding_box=bounding_box_cost,
    )


def _pin_position(cell: PlacedCell, pin_name: str) -> Vec3:
    try:
        pin = next(pin for pin in cell.physical_cell.pins if pin.name == pin_name)
    except StopIteration as exc:
        raise ValueError(
            f"physical cell {cell.physical_cell.cell_id!r} has no pin "
            f"matching {cell.graph_cell}.{pin_name}"
        ) from exc
    return tuple(
        origin_coordinate + pin_coordinate
        for origin_coordinate, pin_coordinate in zip(cell.origin, pin.position)
    )  # type: ignore[return-value]


def _overflows(cell: PlacedCell, bounds: BoundingBox) -> bool:
    return any(
        cell_origin < box_origin or cell_origin + dimension > box_origin + limit
        for cell_origin, dimension, box_origin, limit in zip(
            cell.origin,
            cell.physical_cell.schematic.dimensions,
            bounds.origin,
            bounds.size,
        )
    )


def _violates_clearance(first: PlacedCell, second: PlacedCell) -> bool:
    """Return true unless at least one block separates the cells on an axis."""

    for axis in range(3):
        first_min = first.origin[axis]
        first_max = first_min + first.physical_cell.schematic.dimensions[axis] - 1
        second_min = second.origin[axis]
        second_max = second_min + second.physical_cell.schematic.dimensions[axis] - 1

        if first_max + 1 < second_min or second_max + 1 < first_min:
            return False
    return True
