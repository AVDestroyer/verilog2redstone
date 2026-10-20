from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional


Vec3 = tuple[int, int, int]
PinDirection = Literal["input", "output"]
BufferTurn = Literal["straight", "left", "right"]


@dataclass(frozen=True)
class Pin:
    name: str
    direction: PinDirection
    position: Vec3
    signal_strength_required: Optional[int] = None


@dataclass(frozen=True)
class Schematic:
    path: Path
    region: str
    dimensions: Vec3
    region_position: Vec3
    region_signed_size: Vec3

    @property
    def region_minimum(self) -> Vec3:
        """Minimum schematic corner used as the BlockStates array origin."""
        return tuple(
            position
            if signed_size > 0
            else position - (abs(signed_size) - 1)
            for position, signed_size in zip(
                self.region_position, self.region_signed_size
            )
        )  # type: ignore[return-value]

    def array_to_schematic(self, position: Vec3) -> Vec3:
        """Map a region-array coordinate to the file's schematic coordinate."""
        return tuple(
            minimum + index
            for minimum, index in zip(self.region_minimum, position)
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class Orientation:
    origin: Vec3
    minecraft_axis_directions: Vec3
    allowed_y_rotations: tuple[int, ...]
    allow_mirror: bool


@dataclass(frozen=True)
class RoutingBehavior:
    turn: BufferTurn
    input_heading: str
    output_heading: str


@dataclass(frozen=True)
class PhysicalCell:
    cell_id: str
    logical_type: Optional[str]
    kind: str
    output_signal_strength: int
    schematic: Schematic
    orientation: Orientation
    pins: tuple[Pin, ...]
    routing: Optional[RoutingBehavior] = None

    @property
    def inputs(self) -> tuple[Pin, ...]:
        return tuple(pin for pin in self.pins if pin.direction == "input")

    @property
    def outputs(self) -> tuple[Pin, ...]:
        return tuple(pin for pin in self.pins if pin.direction == "output")

    def cell_to_region_array(self, position: Vec3) -> Vec3:
        """Map a canonical cell-local coordinate to a Litematica array index."""
        return tuple(
            coordinate if cell_direction > 0 else dimension - 1 - coordinate
            for coordinate, dimension, cell_direction in zip(
                position,
                self.schematic.dimensions,
                self.orientation.minecraft_axis_directions,
            )
        )  # type: ignore[return-value]

    def cell_to_schematic(self, position: Vec3) -> Vec3:
        """Map a canonical cell-local coordinate to schematic/world axes."""
        return self.schematic.array_to_schematic(
            self.cell_to_region_array(position)
        )


@dataclass(frozen=True)
class CellLibrary:
    root: Path
    schema_version: int
    cells: tuple[PhysicalCell, ...]
    deferred_assets: tuple[Path, ...]
    max_unbuffered_rail_distance: int
    routing_objectives: tuple[str, ...]

    @property
    def logic_cells(self) -> tuple[PhysicalCell, ...]:
        return tuple(cell for cell in self.cells if cell.kind == "combinational")

    @property
    def routing_cells(self) -> tuple[PhysicalCell, ...]:
        return tuple(cell for cell in self.cells if cell.kind == "routing")

    def by_logical_type(self, logical_type: str) -> PhysicalCell:
        return next(
            cell for cell in self.logic_cells if cell.logical_type == logical_type
        )

    def buffer_for_turn(self, turn: BufferTurn) -> PhysicalCell:
        return next(
            cell
            for cell in self.routing_cells
            if cell.routing is not None and cell.routing.turn == turn
        )
