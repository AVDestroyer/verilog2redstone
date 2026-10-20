"""Simulated annealing placer for fixed-orientation physical cells."""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import replace
from typing import Protocol

from compiler.cell_library import CellLibrary, PhysicalCell
from compiler.graph import CombCell, ModuleGraph

from .cost import placement_cost
from .model import (
    AnnealingConfig,
    BoundingBox,
    CostBreakdown,
    PlacedCell,
    Placement,
    PlacementResult,
    TraceEntry,
    placement_bounding_box,
)


class CostFunction(Protocol):
    """Callable cost model accepted by :func:`place`."""

    def __call__(
        self,
        graph: ModuleGraph,
        placement: Placement,
        bounds: BoundingBox,
        invalid_penalty: float,
        z_span_weight_per_cell: float,
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
    current = _initial_placement(graph, assignments)
    initial_placement = current
    current_cost = evaluator(
        graph,
        current,
        bounds,
        config.invalid_penalty,
        config.z_span_weight_per_cell,
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
            config.z_span_weight_per_cell,
        )
        cost_change = candidate_cost.total - current_cost.total
        accepted = cost_change <= 0 or acceptance_rng.random() < math.exp(
            -cost_change / temperature
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

    best = _move_to_origin(best)
    best_cost = evaluator(
        graph,
        best,
        bounds,
        config.invalid_penalty,
        config.z_span_weight_per_cell,
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
        }
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
) -> Placement:
    order, predecessors = _stable_cell_topological_order(graph, assignments)
    cells: dict[str, PlacedCell] = {}
    current_row: set[str] = set()
    row_number = 0
    row_x = 0
    row_z = 0
    row_width = 0

    for graph_cell in order:
        cell_predecessors = predecessors[graph_cell]
        starts_new_row = bool(cells) and (
            (row_number == 0 and bool(cell_predecessors))
            or bool(cell_predecessors & current_row)
        )
        if starts_new_row:
            row_x += row_width + 5
            row_z = 0
            row_width = 0
            current_row = set()
            row_number += 1

        physical_cell = assignments[graph_cell]
        dimensions = physical_cell.schematic.dimensions
        cells[graph_cell] = PlacedCell(
            graph_cell=graph_cell,
            physical_cell=physical_cell,
            origin=(row_x, 0, row_z),
        )
        current_row.add(graph_cell)
        row_width = max(row_width, dimensions[0])
        row_z += dimensions[2] + 5

    return Placement(cells=cells)


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
    cell_names = tuple(placement.cells)
    if not cell_names:
        return placement, "none"

    can_swap = len(cell_names) >= 2 and config.swap_weight > 0
    can_displace = config.displace_weight > 0
    if not can_swap and not can_displace:
        return placement, "none"
    if can_swap and can_displace:
        total_weight = config.displace_weight + config.swap_weight
        swap = rng.random() * total_weight >= config.displace_weight
    else:
        swap = can_swap

    if swap:
        return _swap_cells(placement, cell_names, rng), "swap"
    return (
        _displace_cell(placement, cell_names, bounds, temperature, config, rng),
        "displace",
    )


def _swap_cells(
    placement: Placement,
    cell_names: tuple[str, ...],
    rng: random.Random,
) -> Placement:
    first_name, second_name = rng.sample(cell_names, 2)
    first = placement.cells[first_name]
    second = placement.cells[second_name]
    cells = dict(placement.cells)
    cells[first_name] = replace(first, origin=second.origin)
    cells[second_name] = replace(second, origin=first.origin)
    return Placement(cells=cells)


def _displace_cell(
    placement: Placement,
    cell_names: tuple[str, ...],
    bounds: BoundingBox,
    temperature: float,
    config: AnnealingConfig,
    rng: random.Random,
) -> Placement:
    cell_name = rng.choice(cell_names)
    cell = placement.cells[cell_name]
    axis = rng.randrange(3)

    if config.initial_temperature == config.final_temperature:
        temperature_fraction = 0.0
    else:
        temperature_fraction = (temperature - config.final_temperature) / (
            config.initial_temperature - config.final_temperature
        )
    temperature_fraction = min(1.0, max(0.0, temperature_fraction))
    maximum = max(
        1,
        math.ceil(
            bounds.size[axis] * config.max_displacement_fraction * temperature_fraction
        ),
    )
    displacement = rng.randint(1, maximum) * rng.choice((-1, 1))
    origin = list(cell.origin)
    origin[axis] += displacement

    cells = dict(placement.cells)
    cells[cell_name] = replace(cell, origin=tuple(origin))  # type: ignore[arg-type]
    return Placement(cells=cells)
