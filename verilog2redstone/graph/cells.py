from __future__ import annotations

from enum import Enum, auto
from typing import FrozenSet


class CellKind(Enum):
    COMB = auto()
    STATE = auto()


COMB_CELLS: FrozenSet[str] = frozenset(
    {
        "$_NOT_",
        "$_NAND_",
        "$_OR_",
    }
)

LOGICAL_REGISTER = "REGISTER"
REGISTER_YOSYS_TYPE = "$_DFF_P_"


STATE_CELLS: dict[str, dict[str, str]] = {
    REGISTER_YOSYS_TYPE: {
        "data_in": "D",
        "data_out": "Q",
        "clock": "C",
    },
}


def classify_cell(yosys_type: str) -> CellKind:
    if yosys_type in COMB_CELLS:
        return CellKind.COMB
    if yosys_type in STATE_CELLS:
        return CellKind.STATE
    raise ValueError(f"unsupported Yosys cell type: {yosys_type}")


def state_port_roles(yosys_type: str) -> dict[str, str]:
    return STATE_CELLS[yosys_type]


def state_logical_type(yosys_type: str) -> str:
    return LOGICAL_REGISTER


def state_clock_edge(yosys_type: str) -> str:
    return "positive"
