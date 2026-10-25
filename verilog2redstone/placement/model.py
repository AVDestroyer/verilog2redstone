from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from verilog2redstone.cell_library import PhysicalCell

Vec3 = tuple[int, int, int]


@dataclass(frozen=True)
class BoundingBox:
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
    graph_cell: str
    physical_cell: PhysicalCell
    origin: Vec3
    layer_id: int = 0
    track_id: int = 0
    z_offset: int = 0


@dataclass(frozen=True)
class Track:
    track_id: int
    origin_z: int
    width: int
    used_width: int
    original_width: int

    @property
    def utilization(self) -> float:
        return self.used_width / self.original_width


@dataclass(frozen=True)
class Placement:
    cells: Mapping[str, PlacedCell]
    track_pitch: int = 0
    track_origin_z: int = 0
    tracks: Mapping[int, Track] = field(default_factory=dict)

    def track_origin(self, track_id: int) -> int:
        track = self.tracks.get(track_id)
        if track is not None:
            return track.origin_z
        return self.track_origin_z + track_id * self.track_pitch

    def track_width(self, track_id: int) -> int:
        track = self.tracks.get(track_id)
        if track is not None:
            return track.width
        return self.track_pitch


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
    wire: float = 0.0
    cross_track: float = 0.0
    routing_constraint: float = 0.0
    overlap: float = 0.0
    overflow: float = 0.0
    bounding_box: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.wire
            + self.cross_track
            + self.routing_constraint
            + self.overlap
            + self.overflow
            + self.bounding_box
        )


@dataclass(frozen=True)
class TraceEntry:
    iteration: int
    temperature: float
    current_cost: CostBreakdown
    best_cost: CostBreakdown
    accepted: bool
    move: str


@dataclass(frozen=True)
class AnnealingConfig:
    iterations_per_cell: int = 5_000
    initial_temperature: float = 100.0
    final_temperature: float = 0.1
    z_offset_weight: float = 0.3
    track_swap_weight: float = 0.2
    y_position_weight: float = 0.2
    x_gap_weight: float = 0.3
    max_displacement_fraction: float = 0.25
    invalid_penalty: float = 100_000.0
    cross_track_penalty: float = 100.0
    bounding_box_weight_per_cell: float = 0.5
    track_padding: int = 5
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
        move_weights = (
            self.z_offset_weight,
            self.track_swap_weight,
            self.y_position_weight,
            self.x_gap_weight,
        )
        if any(weight < 0 for weight in move_weights):
            raise ValueError("move weights cannot be negative")
        if sum(move_weights) == 0:
            raise ValueError("at least one move weight must be positive")
        if self.max_displacement_fraction <= 0:
            raise ValueError("max_displacement_fraction must be positive")
        if self.invalid_penalty < 0:
            raise ValueError("invalid_penalty cannot be negative")
        if self.cross_track_penalty < 0:
            raise ValueError("cross_track_penalty cannot be negative")
        if self.bounding_box_weight_per_cell < 0:
            raise ValueError("bounding_box_weight_per_cell cannot be negative")
        if self.track_padding < 1:
            raise ValueError("track_padding must be at least one block")
        if self.trace_interval is not None and self.trace_interval <= 0:
            raise ValueError("trace_interval must be positive when provided")


@dataclass(frozen=True)
class PlacementResult:
    placement: Placement
    bounding_box: BoundingBox
    initial_placement: Placement
    cost: CostBreakdown
    initial_cost: CostBreakdown
    iterations: int
    accepted_moves: int
    seed: int
    trace: tuple[TraceEntry, ...] = field(default_factory=tuple)
