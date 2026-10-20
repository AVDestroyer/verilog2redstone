"""Default cost function for combinational cell placement."""

from __future__ import annotations

from compiler.graph import ModuleGraph

from .model import BoundingBox, CostBreakdown, PlacedCell, Placement, Vec3


def directed_port_distance(source: Vec3, destination: Vec3) -> int:
    """Directional Manhattan distance used by the initial routing model."""

    dx = destination[0] - source[0]
    dy = destination[1] - source[1]
    dz = destination[2] - source[2]
    return abs(dx) + abs(dy) + 10 * abs(dz) + 2


def placement_cost(
    graph: ModuleGraph,
    placement: Placement,
    bounds: BoundingBox,
    invalid_penalty: float,
    z_span_weight_per_cell: float = 1.0,
) -> CostBreakdown:
    """Evaluate wire length, insufficient clearance, and box overflow.

    Data edges involving primary I/O or constants are ignored because those
    endpoints do not yet have physical placements.
    """

    wire = 0.0
    routing_constraint_count = 0
    for edge in graph.data_edges:
        source_cell = placement.cells.get(edge.src.node)
        destination_cell = placement.cells.get(edge.dst.node)
        if source_cell is None or destination_cell is None:
            continue
        source = _pin_position(source_cell, edge.src.port)
        destination = _pin_position(destination_cell, edge.dst.port)
        wire += directed_port_distance(source, destination)
        signed_dx = destination[0] - source[0]
        dx = abs(signed_dx)
        dy = abs(destination[1] - source[1])
        dz = abs(destination[2] - source[2])
        if signed_dx < 0 or dx < dy or (dz > 0 and dx < 5) or 0 < dz <= 8:
            routing_constraint_count += 1

    placed_cells = tuple(placement.cells.values())
    overflow_count = sum(1 for cell in placed_cells if _overflows(cell, bounds))

    overlap_count = 0
    for index, first in enumerate(placed_cells):
        for second in placed_cells[index + 1 :]:
            if _violates_clearance(first, second):
                overlap_count += 1

    z_span = 0
    if placed_cells:
        z_minimum = min(cell.origin[2] for cell in placed_cells)
        z_maximum = max(
            cell.origin[2] + cell.physical_cell.schematic.dimensions[2]
            for cell in placed_cells
        )
        z_span = z_maximum - z_minimum

    return CostBreakdown(
        wire=wire,
        routing_constraint=routing_constraint_count * invalid_penalty,
        overlap=overlap_count * invalid_penalty,
        overflow=overflow_count * invalid_penalty,
        z_span=z_span * len(placed_cells) * z_span_weight_per_cell,
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

        # One integer coordinate must remain empty between the occupied ranges.
        if first_max + 1 < second_min or second_max + 1 < first_min:
            return False
    return True
