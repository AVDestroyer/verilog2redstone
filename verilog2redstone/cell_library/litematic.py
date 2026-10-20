from __future__ import annotations

from dataclasses import dataclass
import gzip
from pathlib import Path
import struct
from typing import Any, BinaryIO

from .model import Vec3


@dataclass(frozen=True)
class LitematicRegion:
    name: str
    position: Vec3
    signed_size: Vec3

    @property
    def dimensions(self) -> Vec3:
        return tuple(abs(value) for value in self.signed_size)  # type: ignore[return-value]


@dataclass(frozen=True)
class LitematicSummary:
    name: str
    minecraft_data_version: int
    regions: tuple[LitematicRegion, ...]


class _NbtReader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    def _read(self, size: int) -> bytes:
        return self.stream.read(size)

    def _unpack(self, fmt: str) -> Any:
        size = struct.calcsize(">" + fmt)
        return struct.unpack(">" + fmt, self._read(size))[0]

    def _string(self) -> str:
        return self._read(self._unpack("H")).decode("utf-8")

    def _array(self, fmt: str) -> list[Any]:
        length = self._unpack("i")
        return [self._unpack(fmt) for _ in range(length)]

    def payload(self, tag: int) -> Any:
        scalar_formats = {1: "b", 2: "h", 3: "i", 4: "q", 5: "f", 6: "d"}
        if tag in scalar_formats:
            return self._unpack(scalar_formats[tag])
        if tag == 7:
            length = self._unpack("i")
            return self._read(length)
        if tag == 8:
            return self._string()
        if tag == 9:
            item_tag = self._unpack("b")
            length = self._unpack("i")
            return [self.payload(item_tag) for _ in range(length)]
        if tag == 10:
            result: dict[str, Any] = {}
            while True:
                item_tag = self._unpack("b")
                if item_tag == 0:
                    return result
                name = self._string()
                result[name] = self.payload(item_tag)
        if tag == 11:
            return self._array("i")
        if tag == 12:
            return self._array("q")
        raise ValueError(f"unsupported NBT tag: {tag}")

    def root(self) -> dict[str, Any]:
        tag = self._unpack("b")
        self._string()  # Root name is normally empty and is not semantically used.
        return self.payload(tag)


def _vec3(value: dict[str, int]) -> Vec3:
    return tuple(value[axis] for axis in ("x", "y", "z"))  # type: ignore[return-value]


def read_litematic_summary(path: Path) -> LitematicSummary:
    with gzip.open(path, "rb") as stream:
        root = _NbtReader(stream).root()

    metadata = root["Metadata"]
    regions = tuple(
        LitematicRegion(
            name=name,
            position=_vec3(region["Position"]),
            signed_size=_vec3(region["Size"]),
        )
        for name, region in root["Regions"].items()
    )

    return LitematicSummary(
        name=metadata["Name"],
        minecraft_data_version=root["MinecraftDataVersion"],
        regions=regions,
    )
