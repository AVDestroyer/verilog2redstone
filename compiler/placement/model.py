"""Data model and configuration for physical cell placement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional

from compiler.cell_library import PhysicalCell


Vec3 = tuple[int, int, int]
InitializationStrategy = Literal["topological"]


@dataclass(frozen=True)
class BoundingBox:
    """Placement volume with an implicit minimum corner at (0, 0, 0)."""

    size: Vec3

    def __post_init__(self) -> None:
        if len(self.size) != 3 or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.size
        ):
            raise ValueError("bounding box size must contain three positive integers")


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


@dataclass(frozen=True)
class CostBreakdown:
    """Independently tunable components of placement cost."""

    wire: float = 0.0
    routing_constraint: float = 0.0
    overlap: float = 0.0
    overflow: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.wire
            + self.routing_constraint
            + self.overlap
            + self.overflow
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
    initialization: InitializationStrategy = "topological"
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
        if self.initialization != "topological":
            raise ValueError("initialization must be 'topological'")
        if self.trace_interval is not None and self.trace_interval <= 0:
            raise ValueError("trace_interval must be positive when provided")


@dataclass(frozen=True)
class PlacementResult:
    """Best placement found and diagnostic information about the run."""

    placement: Placement
    initial_placement: Placement
    cost: CostBreakdown
    initial_cost: CostBreakdown
    iterations: int
    accepted_moves: int
    seed: int
    initialization: InitializationStrategy
    trace: tuple[TraceEntry, ...] = field(default_factory=tuple)
