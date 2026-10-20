"""Data model and configuration for physical cell placement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from compiler.cell_library import PhysicalCell

Vec3 = tuple[int, int, int]


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned placement volume."""

    size: Vec3
    origin: Vec3 = (0, 0, 0)

    def __post_init__(self) -> None:
        if len(self.size) != 3 or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.size
        ):
            raise ValueError("bounding box size must contain three positive integers")
        if len(self.origin) != 3 or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in self.origin
        ):
            raise ValueError("bounding box origin must contain three integers")


@dataclass(frozen=True)
class PlacedCell:
    """A graph cell assigned to a physical cell and design-space origin."""

    graph_cell: str
    physical_cell: PhysicalCell
    origin: Vec3


@dataclass(frozen=True)
class Placement:
    """Physical assignments indexed by graph cell name."""

    cells: Mapping[str, PlacedCell]


def placement_bounding_box(placement: Placement) -> BoundingBox:
    """Return the smallest axis-aligned box containing every placed cell."""

    if not placement.cells:
        raise ValueError("cannot calculate a bounding box for an empty placement")
    minimum = tuple(
        min(cell.origin[axis] for cell in placement.cells.values()) for axis in range(3)
    )
    maximum = tuple(
        max(
            cell.origin[axis] + cell.physical_cell.schematic.dimensions[axis]
            for cell in placement.cells.values()
        )
        for axis in range(3)
    )
    return BoundingBox(
        size=tuple(maximum[axis] - minimum[axis] for axis in range(3)),
        origin=minimum,
    )


@dataclass(frozen=True)
class CostBreakdown:
    """Independently tunable components of placement cost."""

    wire: float = 0.0
    routing_constraint: float = 0.0
    overlap: float = 0.0
    overflow: float = 0.0
    z_span: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.wire
            + self.routing_constraint
            + self.overlap
            + self.overflow
            + self.z_span
        )


@dataclass(frozen=True)
class TraceEntry:
    """A sampled point in an annealing run."""

    iteration: int
    temperature: float
    current_cost: CostBreakdown
    best_cost: CostBreakdown
    accepted: bool
    move: str


@dataclass(frozen=True)
class AnnealingConfig:
    """Simulated annealing schedule and move configuration."""

    iterations_per_cell: int = 5_000
    initial_temperature: float = 100.0
    final_temperature: float = 0.1
    displace_weight: float = 0.8
    swap_weight: float = 0.2
    max_displacement_fraction: float = 0.25
    invalid_penalty: float = 100_000.0
    z_span_weight_per_cell: float = 2.0
    seed: Optional[int] = None
    trace_interval: Optional[int] = None

    def __post_init__(self) -> None:
        if self.iterations_per_cell <= 0:
            raise ValueError("iterations_per_cell must be positive")
        if self.initial_temperature <= 0 or self.final_temperature <= 0:
            raise ValueError("annealing temperatures must be positive")
        if self.initial_temperature < self.final_temperature:
            raise ValueError(
                "initial_temperature must be greater than or equal to "
                "final_temperature"
            )
        if self.displace_weight < 0 or self.swap_weight < 0:
            raise ValueError("move weights cannot be negative")
        if self.displace_weight + self.swap_weight == 0:
            raise ValueError("at least one move weight must be positive")
        if self.max_displacement_fraction <= 0:
            raise ValueError("max_displacement_fraction must be positive")
        if self.invalid_penalty < 0:
            raise ValueError("invalid_penalty cannot be negative")
        if self.z_span_weight_per_cell < 0:
            raise ValueError("z_span_weight_per_cell cannot be negative")
        if self.trace_interval is not None and self.trace_interval <= 0:
            raise ValueError("trace_interval must be positive when provided")


@dataclass(frozen=True)
class PlacementResult:
    """Best placement found and diagnostic information about the run."""

    placement: Placement
    bounding_box: BoundingBox
    initial_placement: Placement
    cost: CostBreakdown
    initial_cost: CostBreakdown
    iterations: int
    accepted_moves: int
    seed: int
    trace: tuple[TraceEntry, ...] = field(default_factory=tuple)
