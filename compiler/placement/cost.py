"""Default cost function for combinational cell placement."""

from __future__ import annotations

from compiler.graph import ModuleGraph

from .model import BoundingBox, CostBreakdown, PlacedCell, Placement, Vec3


def directed_port_distance(source: Vec3, destination: Vec3) -> int:
    """Directional Manhattan distance used by the initial routing model."""

    dx = destination[0] - source[0]
    if dx < 0:
        raise ValueError("backward x edges are illegal")
    dy = destination[1] - source[1]
    dz = destination[2] - source[2]
    return dx + abs(dy) + 10 * abs(dz) + 2


def placement_has_backward_x_edge(
    graph: ModuleGraph, placement: Placement
) -> bool:
    """Return whether a placed cell-to-cell edge travels in negative X."""

    for edge in graph.data_edges:
        source_cell = placement.cells.get(edge.src.node)
        destination_cell = placement.cells.get(edge.dst.node)
        if source_cell is None or destination_cell is None:
            continue
        source = _pin_position(source_cell, edge.src.port)
        destination = _pin_position(destination_cell, edge.dst.port)
        if destination[0] < source[0]:
            return True
    return False


def placement_cost(
    graph: ModuleGraph,
    placement: Placement,
    bounds: BoundingBox,
    invalid_penalty: float,
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
        dx = destination[0] - source[0]
        dy = abs(destination[1] - source[1])
        dz = abs(destination[2] - source[2])
        if (
            dx < dy
            or (dz > 0 and dx < 5)
            or 0 < dz <= 8
        ):
            routing_constraint_count += 1

    placed_cells = tuple(placement.cells.values())
    overflow_count = sum(1 for cell in placed_cells if _overflows(cell, bounds))

    overlap_count = 0
    for index, first in enumerate(placed_cells):
        for second in placed_cells[index + 1 :]:
            if _violates_clearance(first, second):
                overlap_count += 1

    return CostBreakdown(
        wire=wire,
        routing_constraint=routing_constraint_count * invalid_penalty,
        overlap=overlap_count * invalid_penalty,
        overflow=overflow_count * invalid_penalty,
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
        origin < 0 or origin + dimension > limit
        for origin, dimension, limit in zip(
            cell.origin, cell.physical_cell.schematic.dimensions, bounds.size
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
