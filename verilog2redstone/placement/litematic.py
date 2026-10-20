"""Export placed physical cells to a combined Litematica schematic."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .model import Placement, Vec3, placement_bounding_box


def save_placement_litematic(
    placement: Placement,
    path: str | Path,
    *,
    name: str = "verilog2redstone placement",
    author: str = "verilog2redstone",
    description: str = "Placed logic cells; routing not included.",
    region_name: str = "PLACEMENT",
) -> Path:
    """Save all blocks and block entities from a placement with Litemapy.

    The output preserves the cell library's axis convention: canonical +x and
    +z map to Litematica -X and -Z. This lets block-state orientations be
    copied verbatim from the source cells.
    """

    try:
        from litemapy import Entity, Region, Schematic, TileEntity
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Litematica export requires litemapy; install requirements.txt"
        ) from exc

    if not placement.cells:
        raise ValueError("cannot export an empty placement")
    bounds = placement_bounding_box(placement)

    loaded: dict[Path, Any] = {}
    sources: dict[str, tuple[Any, Any]] = {}
    versions: set[tuple[int, int, int]] = set()
    for graph_cell, placed_cell in placement.cells.items():
        physical_cell = placed_cell.physical_cell
        schematic_path = physical_cell.schematic.path
        if schematic_path not in loaded:
            loaded[schematic_path] = Schematic.load(str(schematic_path))
        source_schematic = loaded[schematic_path]
        try:
            source_region = source_schematic.regions[
                physical_cell.schematic.region
            ]
        except KeyError as exc:
            raise ValueError(
                f"region {physical_cell.schematic.region!r} is missing from "
                f"{schematic_path}"
            ) from exc
        sources[graph_cell] = (source_schematic, source_region)
        versions.add(
            (
                int(source_schematic.lm_version),
                int(source_schematic.lm_subversion),
                int(source_schematic.mc_version),
            )
        )

    if len(versions) != 1:
        raise ValueError(
            f"physical cells use incompatible schematic versions: {versions!r}"
        )
    litematic_version, litematic_subversion, minecraft_version = versions.pop()

    # A selection corner at the canonical origin and negative X/Z sizes maps
    # canonical coordinates directly without rotating or mirroring cell data.
    output_region = Region(
        0,
        0,
        0,
        -bounds.size[0],
        bounds.size[1],
        -bounds.size[2],
    )

    for graph_cell, placed_cell in placement.cells.items():
        physical_cell = placed_cell.physical_cell
        _, source_region = sources[graph_cell]
        source_region_position = (
            source_region.x,
            source_region.y,
            source_region.z,
        )

        for local_position in _positions(physical_cell.schematic.dimensions):
            source_schematic_position = physical_cell.cell_to_schematic(
                local_position
            )
            source_region_position_local = tuple(
                source_schematic_position[index]
                - source_region_position[index]
                for index in range(3)
            )
            block = source_region[source_region_position_local]
            if block.id == "minecraft:air":
                continue

            canonical_position = tuple(
                placed_cell.origin[index]
                - bounds.origin[index]
                + local_position[index]
                for index in range(3)
            )
            destination = _canonical_to_litematic(canonical_position)
            existing = output_region[destination]
            if existing.id != "minecraft:air":
                raise ValueError(
                    f"placed cells overlap at canonical position "
                    f"{canonical_position!r}"
                )
            output_region[destination] = block

        source_origin = physical_cell.cell_to_schematic((0, 0, 0))
        destination_origin = _canonical_to_litematic(
            tuple(
                placed_cell.origin[index] - bounds.origin[index]
                for index in range(3)
            )
        )
        translation = tuple(
            destination_origin[index] - source_origin[index]
            for index in range(3)
        )
        for tile_entity in source_region.tile_entities:
            copied = TileEntity(deepcopy(tile_entity.data))
            copied.position = _translate(tile_entity.position, translation)
            output_region.tile_entities.append(copied)
        for entity in source_region.entities:
            copied = Entity(deepcopy(entity.data))
            copied.position = _translate(entity.position, translation)
            output_region.entities.append(copied)

    schematic = Schematic(
        name=name,
        author=author,
        description=description,
        regions={region_name: output_region},
        lm_version=litematic_version,
        lm_subversion=litematic_subversion,
        mc_version=minecraft_version,
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schematic.save(str(output_path))
    return output_path


def _positions(dimensions: Vec3):
    for x in range(dimensions[0]):
        for y in range(dimensions[1]):
            for z in range(dimensions[2]):
                yield x, y, z


def _canonical_to_litematic(position: Vec3) -> Vec3:
    return -position[0], position[1], -position[2]


def _translate(position, translation):
    return tuple(
        position[index] + translation[index] for index in range(3)
    )
