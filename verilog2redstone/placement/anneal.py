from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import replace
from typing import Protocol

from verilog2redstone.cell_library import CellLibrary, PhysicalCell
from verilog2redstone.graph import CombCell, ModuleGraph

from .cost import placement_cost
from .model import (
    AnnealingConfig,
    BoundingBox,
    CostBreakdown,
    PlacedCell,
    Placement,
    PlacementResult,
    Track,
    TraceEntry,
    placement_bounding_box,
)


class CostFunction(Protocol):
    def __call__(
        self,
        graph: ModuleGraph,
        placement: Placement,
        bounds: BoundingBox,
        invalid_penalty: float,
        bounding_box_weight_per_cell: float,
        cross_track_penalty: float,
    ) -> CostBreakdown: ...


def place(
    graph: ModuleGraph,
    library: CellLibrary,
    bounds: BoundingBox,
    config: AnnealingConfig | None = None,
    *,
    cost_function: CostFunction | None = None,
) -> PlacementResult:
    """Assign and place every combinational graph cell using annealing."""

    if graph.state_cells:
        raise ValueError("placement of state cells is not implemented")

    config = config or AnnealingConfig()
    evaluator = cost_function or placement_cost
    seed = (
        config.seed
        if config.seed is not None
        else random.SystemRandom().randrange(0, 2**63)
    )
    move_rng = random.Random(seed)
    acceptance_rng = random.Random(seed ^ 0xD1B54A32D192ED03)

    assignments = _assign_physical_cells(graph, library)
    _validate_cells_fit(assignments, bounds)
    current = _initial_placement(graph, assignments, config.track_padding)
    initial_placement = current
    current_cost = evaluator(
        graph,
        current,
        bounds,
        config.invalid_penalty,
        config.bounding_box_weight_per_cell,
        config.cross_track_penalty,
    )
    initial_cost = current_cost
    best = current
    best_cost = current_cost

    cell_count = len(current.cells)
    iterations = config.iterations_per_cell * cell_count
    accepted_moves = 0
    trace: list[TraceEntry] = []
    if config.trace_interval is not None:
        trace.append(
            TraceEntry(
                iteration=0,
                temperature=config.initial_temperature,
                current_cost=current_cost,
                best_cost=best_cost,
                accepted=True,
                move="initial",
            )
        )

    for iteration in range(1, iterations + 1):
        temperature = _temperature(config, iteration, iterations)
        candidate, move = _candidate_move(
            current, bounds, temperature, config, move_rng
        )
        candidate_cost = evaluator(
            graph,
            candidate,
            bounds,
            config.invalid_penalty,
            config.bounding_box_weight_per_cell,
            config.cross_track_penalty,
        )
        cost_change = candidate_cost.total - current_cost.total
        changed = candidate is not current
        accepted = changed and (
            cost_change <= 0
            or acceptance_rng.random() < math.exp(-cost_change / temperature)
        )

        if accepted:
            current = candidate
            current_cost = candidate_cost
            accepted_moves += 1
            if current_cost.total < best_cost.total:
                best = current
                best_cost = current_cost

        if config.trace_interval is not None and (
            iteration % config.trace_interval == 0 or iteration == iterations
        ):
            trace.append(
                TraceEntry(
                    iteration=iteration,
                    temperature=temperature,
                    current_cost=current_cost,
                    best_cost=best_cost,
                    accepted=accepted,
                    move=move,
                )
            )

    best = _compact_tracks(best)
    best = _move_to_origin(best)
    best_cost = evaluator(
        graph,
        best,
        bounds,
        config.invalid_penalty,
        config.bounding_box_weight_per_cell,
        config.cross_track_penalty,
    )
    return PlacementResult(
        placement=best,
        bounding_box=placement_bounding_box(best),
        initial_placement=initial_placement,
        cost=best_cost,
        initial_cost=initial_cost,
        iterations=iterations,
        accepted_moves=accepted_moves,
        seed=seed,
        trace=tuple(trace),
    )


def _move_to_origin(placement: Placement) -> Placement:
    minimum = tuple(
        min(cell.origin[axis] for cell in placement.cells.values()) for axis in range(3)
    )
    return Placement(
        cells={
            name: replace(
                cell,
                origin=tuple(cell.origin[axis] - minimum[axis] for axis in range(3)),
            )
            for name, cell in placement.cells.items()
        },
        track_pitch=placement.track_pitch,
        track_origin_z=placement.track_origin_z - minimum[2],
        tracks={
            track_id: replace(track, origin_z=track.origin_z - minimum[2])
            for track_id, track in placement.tracks.items()
        },
    )


def _compact_tracks(placement: Placement) -> Placement:
    """Remove unused z space while retaining one separator between tracks."""

    cells_by_track: dict[int, list[PlacedCell]] = {}
    for cell in placement.cells.values():
        cells_by_track.setdefault(cell.track_id, []).append(cell)

    cells = dict(placement.cells)
    tracks: dict[int, Track] = {}
    next_origin = placement.track_origin_z
    for track_id in sorted(cells_by_track):
        track_cells = cells_by_track[track_id]
        used_minimum = min(cell.origin[2] for cell in track_cells)
        used_maximum = max(
            cell.origin[2] + cell.physical_cell.schematic.dimensions[2]
            for cell in track_cells
        )
        used_width = used_maximum - used_minimum
        compact_width = used_width + 1
        displacement = next_origin - used_minimum
        track = Track(
            track_id=track_id,
            origin_z=next_origin,
            width=compact_width,
            used_width=used_width,
            original_width=placement.track_width(track_id),
        )
        tracks[track_id] = track
        for cell in track_cells:
            origin = list(cell.origin)
            origin[2] += displacement
            depth = cell.physical_cell.schematic.dimensions[2]
            centered = (compact_width - 1 - depth) // 2
            cells[cell.graph_cell] = replace(
                cell,
                origin=tuple(origin),  # type: ignore[arg-type]
                z_offset=origin[2] - next_origin - centered,
            )
        next_origin += compact_width

    return Placement(
        cells=cells,
        track_pitch=placement.track_pitch,
        track_origin_z=placement.track_origin_z,
        tracks=tracks,
    )


def _assign_physical_cells(
    graph: ModuleGraph, library: CellLibrary
) -> dict[str, PhysicalCell]:
    physical_by_type = {
        cell.logical_type: cell
        for cell in library.logic_cells
        if cell.logical_type is not None
    }
    assignments: dict[str, PhysicalCell] = {}
    for graph_cell in graph.comb_cells:
        try:
            physical = physical_by_type[graph_cell.yosys_type]
        except KeyError as exc:
            raise ValueError(
                f"no physical cell for logical type {graph_cell.yosys_type!r}"
            ) from exc
        _validate_ports(graph_cell, physical)
        assignments[graph_cell.name] = physical
    return assignments


def _validate_ports(graph_cell: CombCell, physical_cell: PhysicalCell) -> None:
    graph_ports = set(graph_cell.port_directions.items())
    physical_ports = {(pin.name, pin.direction) for pin in physical_cell.pins}
    if graph_ports != physical_ports:
        raise ValueError(
            f"port mismatch for {graph_cell.name!r}: graph has "
            f"{sorted(graph_ports)!r}, physical cell {physical_cell.cell_id!r} "
            f"has {sorted(physical_ports)!r}"
        )


def _validate_cells_fit(
    assignments: dict[str, PhysicalCell],
    bounds: BoundingBox,
) -> None:
    for physical_cell in assignments.values():
        dimensions = physical_cell.schematic.dimensions
        if any(dimension > limit for dimension, limit in zip(dimensions, bounds.size)):
            raise ValueError(
                f"physical cell {physical_cell.cell_id!r} with dimensions "
                f"{dimensions!r} does not fit in bounding box {bounds.size!r}"
            )


def _initial_placement(
    graph: ModuleGraph,
    assignments: dict[str, PhysicalCell],
    track_padding: int,
) -> Placement:
    order, predecessors = _stable_cell_topological_order(graph, assignments)
    layers: dict[str, int] = {}
    layer_cells: dict[int, list[str]] = {}
    for graph_cell in order:
        layer_id = max(
            (layers[predecessor] + 1 for predecessor in predecessors[graph_cell]),
            default=0,
        )
        layers[graph_cell] = layer_id
        layer_cells.setdefault(layer_id, []).append(graph_cell)

    maximum_depth = max(
        cell.schematic.dimensions[2] for cell in assignments.values()
    )
    track_pitch = maximum_depth + track_padding
    layer_x: dict[int, int] = {}
    next_x = 0
    for layer_id in sorted(layer_cells):
        layer_x[layer_id] = next_x
        layer_width = max(
            assignments[name].schematic.dimensions[0]
            for name in layer_cells[layer_id]
        )
        next_x += layer_width + 5

    cells: dict[str, PlacedCell] = {}
    for layer_id, names in layer_cells.items():
        for track_id, graph_cell in enumerate(names):
            physical_cell = assignments[graph_cell]
            depth = physical_cell.schematic.dimensions[2]
            centered_z = track_id * track_pitch + (track_pitch - 1 - depth) // 2
            cells[graph_cell] = PlacedCell(
                graph_cell=graph_cell,
                physical_cell=physical_cell,
                origin=(layer_x[layer_id], 0, centered_z),
                layer_id=layer_id,
                track_id=track_id,
                z_offset=0,
            )

    return Placement(cells=cells, track_pitch=track_pitch)


def _stable_cell_topological_order(
    graph: ModuleGraph,
    assignments: dict[str, PhysicalCell],
) -> tuple[list[str], dict[str, set[str]]]:
    cell_names = set(assignments)
    predecessors = {name: set() for name in assignments}
    successors = {name: [] for name in assignments}
    successor_sets = {name: set() for name in assignments}

    for edge in graph.data_edges:
        source = edge.src.node
        destination = edge.dst.node
        if source not in cell_names or destination not in cell_names:
            continue
        predecessors[destination].add(source)
        if destination not in successor_sets[source]:
            successor_sets[source].add(destination)
            successors[source].append(destination)

    indegree = {
        name: len(cell_predecessors) for name, cell_predecessors in predecessors.items()
    }
    ready = deque(name for name in assignments if indegree[name] == 0)
    order: list[str] = []
    while ready:
        name = ready.popleft()
        order.append(name)
        for successor in successors[name]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)

    if len(order) != len(assignments):
        raise ValueError("combinational cell graph contains a cycle")
    return order, predecessors


def _temperature(config: AnnealingConfig, iteration: int, iterations: int) -> float:
    if iterations <= 1:
        return config.final_temperature
    progress = (iteration - 1) / (iterations - 1)
    return (
        config.initial_temperature
        * (config.final_temperature / config.initial_temperature) ** progress
    )


def _candidate_move(
    placement: Placement,
    bounds: BoundingBox,
    temperature: float,
    config: AnnealingConfig,
    rng: random.Random,
) -> tuple[Placement, str]:
    if not placement.cells:
        return placement, "none"

    cells_by_layer: dict[int, list[str]] = {}
    for name, cell in placement.cells.items():
        cells_by_layer.setdefault(cell.layer_id, []).append(name)

    moves: list[tuple[str, float]] = []
    if config.z_offset_weight > 0:
        moves.append(("z_offset", config.z_offset_weight))
    if config.track_swap_weight > 0 and any(
        len(names) >= 2 for names in cells_by_layer.values()
    ):
        moves.append(("track_swap", config.track_swap_weight))
    if config.y_position_weight > 0:
        moves.append(("y_position", config.y_position_weight))
    if config.x_gap_weight > 0 and len(cells_by_layer) >= 2:
        moves.append(("x_gap", config.x_gap_weight))
    if not moves:
        return placement, "none"

    selection = rng.random() * sum(weight for _, weight in moves)
    move = moves[-1][0]
    for name, weight in moves:
        selection -= weight
        if selection < 0:
            move = name
            break

    if move == "z_offset":
        return _move_z_offset(placement, rng), move
    if move == "track_swap":
        return _swap_tracks_within_layer(placement, cells_by_layer, rng), move
    if move == "y_position":
        return _move_y_position(
            placement, bounds, temperature, config, rng
        ), move
    return _move_x_gap(placement, bounds, temperature, config, rng), move


def _move_z_offset(
    placement: Placement,
    rng: random.Random,
) -> Placement:
    cell_name = rng.choice(tuple(placement.cells))
    cell = placement.cells[cell_name]
    displacement = rng.choice((-1, 1))
    origin = list(cell.origin)
    origin[2] += displacement
    candidate = replace(
        cell,
        origin=tuple(origin),  # type: ignore[arg-type]
        z_offset=cell.z_offset + displacement,
    )
    if not _cell_fits_track(candidate, placement):
        return placement

    cells = dict(placement.cells)
    cells[cell_name] = candidate
    return _with_cells(placement, cells)


def _swap_tracks_within_layer(
    placement: Placement,
    cells_by_layer: dict[int, list[str]],
    rng: random.Random,
) -> Placement:
    layer_id = rng.choice(
        tuple(
            layer
            for layer, names in cells_by_layer.items()
            if len(names) >= 2
        )
    )
    first_name, second_name = rng.sample(cells_by_layer[layer_id], 2)
    first = placement.cells[first_name]
    second = placement.cells[second_name]
    first_origin = list(first.origin)
    second_origin = list(second.origin)
    first_origin[2] = _track_z_for_cell(
        first, second.track_id, first.z_offset, placement
    )
    second_origin[2] = _track_z_for_cell(
        second, first.track_id, second.z_offset, placement
    )

    cells = dict(placement.cells)
    cells[first_name] = replace(
        first,
        origin=tuple(first_origin),  # type: ignore[arg-type]
        track_id=second.track_id,
    )
    cells[second_name] = replace(
        second,
        origin=tuple(second_origin),  # type: ignore[arg-type]
        track_id=first.track_id,
    )
    candidate = _with_cells(placement, cells)
    if not _tracks_do_not_overlap_x(candidate):
        return placement
    return candidate


def _move_y_position(
    placement: Placement,
    bounds: BoundingBox,
    temperature: float,
    config: AnnealingConfig,
    rng: random.Random,
) -> Placement:
    cell_name = rng.choice(tuple(placement.cells))
    cell = placement.cells[cell_name]
    displacement = rng.randint(
        1, _maximum_displacement(bounds.size[1], temperature, config)
    ) * rng.choice((-1, 1))
    origin = list(cell.origin)
    origin[1] += displacement

    cells = dict(placement.cells)
    cells[cell_name] = replace(cell, origin=tuple(origin))  # type: ignore[arg-type]
    return _with_cells(placement, cells)


def _move_x_gap(
    placement: Placement,
    bounds: BoundingBox,
    temperature: float,
    config: AnnealingConfig,
    rng: random.Random,
) -> Placement:
    layers = sorted({cell.layer_id for cell in placement.cells.values()})
    boundary = rng.choice(layers[1:])
    displacement = rng.randint(
        1, _maximum_displacement(bounds.size[0], temperature, config)
    ) * rng.choice((-1, 1))

    cells = dict(placement.cells)
    for name, cell in placement.cells.items():
        if cell.layer_id < boundary:
            continue
        origin = list(cell.origin)
        origin[0] += displacement
        cells[name] = replace(cell, origin=tuple(origin))  # type: ignore[arg-type]

    candidate = _with_cells(placement, cells)
    if not _layers_are_forward(candidate) or not _tracks_do_not_overlap_x(candidate):
        return placement
    return candidate


def _maximum_displacement(
    axis_size: int,
    temperature: float,
    config: AnnealingConfig,
) -> int:

    if config.initial_temperature == config.final_temperature:
        temperature_fraction = 0.0
    else:
        temperature_fraction = (temperature - config.final_temperature) / (
            config.initial_temperature - config.final_temperature
        )
    temperature_fraction = min(1.0, max(0.0, temperature_fraction))
    return max(
        1,
        math.ceil(
            axis_size * config.max_displacement_fraction * temperature_fraction
        ),
    )


def _track_z_for_cell(
    cell: PlacedCell,
    track_id: int,
    z_offset: int,
    placement: Placement,
) -> int:
    depth = cell.physical_cell.schematic.dimensions[2]
    track_width = placement.track_width(track_id)
    centered = (track_width - 1 - depth) // 2
    return (
        placement.track_origin(track_id)
        + centered
        + z_offset
    )


def _cell_fits_track(cell: PlacedCell, placement: Placement) -> bool:
    track_start = placement.track_origin(cell.track_id)
    track_end = track_start + placement.track_width(cell.track_id) - 2
    depth = cell.physical_cell.schematic.dimensions[2]
    return track_start <= cell.origin[2] and cell.origin[2] + depth - 1 <= track_end


def _layers_are_forward(placement: Placement) -> bool:
    positions: dict[int, set[int]] = {}
    for cell in placement.cells.values():
        positions.setdefault(cell.layer_id, set()).add(cell.origin[0])
    if any(len(layer_positions) != 1 for layer_positions in positions.values()):
        return False
    ordered = [next(iter(positions[layer])) for layer in sorted(positions)]
    return all(first < second for first, second in zip(ordered, ordered[1:]))


def _tracks_do_not_overlap_x(placement: Placement) -> bool:
    cells_by_track: dict[int, list[PlacedCell]] = {}
    for cell in placement.cells.values():
        cells_by_track.setdefault(cell.track_id, []).append(cell)
    for track_cells in cells_by_track.values():
        ordered = sorted(track_cells, key=lambda cell: cell.origin[0])
        for first, second in zip(ordered, ordered[1:]):
            first_end = (
                first.origin[0]
                + first.physical_cell.schematic.dimensions[0]
                - 1
            )
            if first_end + 1 >= second.origin[0]:
                return False
    return True


def _with_cells(
    placement: Placement,
    cells: dict[str, PlacedCell],
) -> Placement:
    return Placement(
        cells=cells,
        track_pitch=placement.track_pitch,
        track_origin_z=placement.track_origin_z,
        tracks=placement.tracks,
    )
