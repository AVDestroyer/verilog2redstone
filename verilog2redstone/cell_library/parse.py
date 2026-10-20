from __future__ import annotations

import json
from pathlib import Path

from .litematic import read_litematic_summary
from .model import (
    CellLibrary,
    Orientation,
    PhysicalCell,
    Pin,
    RoutingBehavior,
    Schematic,
    Vec3,
)


def _vec3(value: list[int]) -> Vec3:
    return tuple(value)  # type: ignore[return-value]


def _load_cell(
    metadata_path: Path,
    origin: Vec3,
    axis_directions: Vec3,
) -> PhysicalCell:
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    kind = data["kind"]
    logical_type = data.get("logical_type")
    routing: RoutingBehavior | None = None
    if kind == "routing":
        routing_data = data["routing"]
        routing = RoutingBehavior(
            turn=routing_data["turn"],
            input_heading=routing_data["input_heading"],
            output_heading=routing_data["output_heading"],
        )

    schematic_data = data["schematic"]
    schematic_path = metadata_path.parent / schematic_data["file"]
    dimensions = _vec3(schematic_data["dimensions"])
    region_name = schematic_data["region"]

    summary = read_litematic_summary(schematic_path)
    litematic_region = next(r for r in summary.regions if r.name == region_name)
    if litematic_region.dimensions != dimensions:
        raise ValueError(
            f"dimension mismatch for {schematic_path}: metadata has {dimensions}, "
            f"schematic has {litematic_region.dimensions}"
        )

    orientation_data = data["orientation"]
    pins = tuple(
        Pin(
            name=pin["name"],
            direction=pin["direction"],
            position=_vec3(pin["position"]),
            signal_strength_required=(
                pin["signal_strength_required"]
                if pin["direction"] == "input"
                else None
            ),
        )
        for pin in data["pins"]
    )
    for pin in pins:
        if any(
            coord < 0 or coord >= limit
            for coord, limit in zip(pin.position, dimensions)
        ):
            raise ValueError(
                f"pin {pin.name} {pin.position} is outside dimensions {dimensions}"
            )

    return PhysicalCell(
        cell_id=data["id"],
        logical_type=logical_type,
        kind=kind,
        output_signal_strength=data["output_signal_strength"],
        schematic=Schematic(
            path=schematic_path,
            region=region_name,
            dimensions=dimensions,
            region_position=litematic_region.position,
            region_signed_size=litematic_region.signed_size,
        ),
        orientation=Orientation(
            origin=origin,
            minecraft_axis_directions=axis_directions,
            allowed_y_rotations=tuple(orientation_data["allowed_y_rotations"]),
            allow_mirror=orientation_data["allow_mirror"],
        ),
        pins=pins,
        routing=routing,
    )


def load_cell_library(root: str | Path) -> CellLibrary:
    root = Path(root)
    data = json.loads((root / "library.json").read_text(encoding="utf-8"))
    coordinate_data = data["coordinate_system"]
    origin = _vec3(coordinate_data["origin_position"])
    axis_directions = _vec3(coordinate_data["minecraft_axis_directions"])
    routing_data = data["routing"]

    return CellLibrary(
        root=root,
        schema_version=data["schema_version"],
        cells=tuple(
            _load_cell(root / path, origin, axis_directions)
            for path in data["cells"]
        ),
        deferred_assets=tuple(root / path for path in data["deferred_assets"]),
        max_unbuffered_rail_distance=routing_data["max_unbuffered_rail_distance"],
        routing_objectives=tuple(routing_data["objectives"]),
    )
