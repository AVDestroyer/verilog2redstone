"""Sequential-aware graph IR.

Combinational subgraphs must be a DAG. State cells are divided into D and Q:
D is a sink and Q is a source. Clock and reset are control edges, so they are
not part of the topological ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class CombCycleError(ValueError):
    def __init__(self, path: list[str]):
        self.path = path
        rendered = " -> ".join(path)
        super().__init__(f"combinational data graph has a cycle: {rendered}")


@dataclass(frozen=True)
class Endpoint:
    node: str
    port: str
    bit: int = 0

    def __str__(self) -> str:
        base = self.node if not self.port else f"{self.node}.{self.port}"
        if self.bit == 0:
            return base
        return f"{base}[{self.bit}]"


@dataclass(frozen=True)
class DataEdge:
    net_id: int
    src: Endpoint
    dst: Endpoint


@dataclass(frozen=True)
class ControlEdge:
    net_id: int
    src: Endpoint
    dst: Endpoint
    role: str  # "clock" | "reset" | "enable"


@dataclass
class Port:
    name: str
    direction: str  # "input" | "output" | "inout"
    bits: list[int]  # Yosys net IDs, LSB-first (may include const 0/1)

    @property
    def width(self) -> int:
        return len(self.bits)


@dataclass
class CombCell:
    name: str
    yosys_type: str
    port_directions: dict[str, str]
    connections: dict[str, list[Any]]  # net ids or const "0"/"1"


@dataclass
class StateCell:
    name: str
    yosys_type: str
    logical_type: str
    clock_edge: str
    port_directions: dict[str, str]
    connections: dict[str, list[Any]]
    roles: dict[str, str]  # logical role -> Yosys port name


@dataclass
class Net:
    net_id: int
    name: Optional[str] = None
    drivers: list[Endpoint] = field(default_factory=list)
    sinks: list[Endpoint] = field(default_factory=list)


@dataclass
class ModuleGraph:
    name: str
    primary_inputs: list[Port] = field(default_factory=list)
    primary_outputs: list[Port] = field(default_factory=list)
    comb_cells: list[CombCell] = field(default_factory=list)
    state_cells: list[StateCell] = field(default_factory=list)
    nets: dict[int, Net] = field(default_factory=dict)
    data_edges: list[DataEdge] = field(default_factory=list)
    control_edges: list[ControlEdge] = field(default_factory=list)
    constants: dict[int, int] = field(default_factory=dict)  # synthetic net -> 0/1
    warnings: list[str] = field(default_factory=list)

    def comb_node_id(self, ep: Endpoint) -> str:
        """Node id used for combinational DAG analysis.

        State cells are split at the register boundary: Q and D are distinct
        nodes so feedback through a flop is not treated as a comb cycle.
        """
        if any(c.name == ep.node for c in self.state_cells):
            return f"{ep.node}.{ep.port}"
        return ep.node

    def comb_successors(self) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {}
        for edge in self.data_edges:
            src = self.comb_node_id(edge.src)
            dst = self.comb_node_id(edge.dst)
            adj.setdefault(src, set()).add(dst)
            adj.setdefault(dst, set())
        return adj

    def find_comb_cycle(self) -> Optional[list[str]]:
        adj = self.comb_successors()
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def dfs(n: str) -> Optional[list[str]]:
            if n in visited:
                return None
            if n in visiting:
                i = stack.index(n)
                return stack[i:] + [n]
            visiting.add(n)
            stack.append(n)
            for nxt in adj.get(n, ()):
                cycle = dfs(nxt)
                if cycle is not None:
                    return cycle
            stack.pop()
            visiting.remove(n)
            visited.add(n)
            return None

        for n in adj:
            cycle = dfs(n)
            if cycle is not None:
                return cycle
        return None

    def has_comb_cycle(self) -> bool:
        return self.find_comb_cycle() is not None

    def topo_layers(self) -> list[list[str]]:
        """Kahn layering over data-edge nodes. Raises CombCycleError if cyclic."""
        cycle = self.find_comb_cycle()
        if cycle is not None:
            raise CombCycleError(cycle)

        adj = self.comb_successors()
        indeg = {n: 0 for n in adj}
        for src, dsts in adj.items():
            for dst in dsts:
                indeg[dst] = indeg.get(dst, 0) + 1
                indeg.setdefault(src, indeg.get(src, 0))

        ready = sorted(n for n, d in indeg.items() if d == 0)
        layers: list[list[str]] = []
        while ready:
            layers.append(ready)
            nxt: list[str] = []
            for n in ready:
                for m in adj.get(n, ()):
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        nxt.append(m)
            ready = sorted(nxt)

        return layers

    def undriven_nets(self) -> list[int]:
        return sorted(
            net_id for net_id, net in self.nets.items() if net.sinks and not net.drivers
        )

    def validate(self, *, require_acyclic: bool = True) -> None:
        if require_acyclic:
            cycle = self.find_comb_cycle()
            if cycle is not None:
                raise CombCycleError(cycle)

        undriven = self.undriven_nets()
        if undriven:
            raise ValueError(
                "nets with sinks but no driver: " + ", ".join(str(n) for n in undriven)
            )

    def summary(self) -> str:
        lines = [
            f"module {self.name}",
            f"  primary_inputs:  {[p.name for p in self.primary_inputs]}",
            f"  primary_outputs: {[p.name for p in self.primary_outputs]}",
            "  comb_cells:      "
            + str([f"{c.name}:{c.yosys_type}" for c in self.comb_cells]),
            "  state_cells:     "
            + str(
                [f"{c.name}:{c.logical_type}({c.yosys_type})" for c in self.state_cells]
            ),
            f"  data_edges ({len(self.data_edges)}):",
        ]
        for e in self.data_edges:
            lines.append(f"    net {e.net_id}: {e.src} -> {e.dst}")
        lines.append(f"  control_edges ({len(self.control_edges)}):")
        for e in self.control_edges:
            lines.append(f"    [{e.role}] net {e.net_id}: {e.src} -> {e.dst}")
        if self.warnings:
            lines.append("  warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        cycle = self.find_comb_cycle()
        lines.append(f"  comb_cycle: {cycle is not None}")
        if cycle is not None:
            lines.append(f"  comb_cycle_path: {' -> '.join(cycle)}")
        else:
            lines.append(f"  topo_layers: {self.topo_layers()}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "primary_inputs": [
                {"name": p.name, "direction": p.direction, "bits": p.bits}
                for p in self.primary_inputs
            ],
            "primary_outputs": [
                {"name": p.name, "direction": p.direction, "bits": p.bits}
                for p in self.primary_outputs
            ],
            "comb_cells": [
                {
                    "name": c.name,
                    "type": c.yosys_type,
                    "port_directions": c.port_directions,
                    "connections": c.connections,
                }
                for c in self.comb_cells
            ],
            "state_cells": [
                {
                    "name": c.name,
                    "type": c.yosys_type,
                    "logical_type": c.logical_type,
                    "clock_edge": c.clock_edge,
                    "roles": c.roles,
                    "port_directions": c.port_directions,
                    "connections": c.connections,
                }
                for c in self.state_cells
            ],
            "data_edges": [
                {
                    "net": e.net_id,
                    "src": {"node": e.src.node, "port": e.src.port, "bit": e.src.bit},
                    "dst": {"node": e.dst.node, "port": e.dst.port, "bit": e.dst.bit},
                }
                for e in self.data_edges
            ],
            "control_edges": [
                {
                    "net": e.net_id,
                    "role": e.role,
                    "src": {"node": e.src.node, "port": e.src.port, "bit": e.src.bit},
                    "dst": {"node": e.dst.node, "port": e.dst.port, "bit": e.dst.bit},
                }
                for e in self.control_edges
            ],
            "warnings": list(self.warnings),
            "comb_cycle": self.has_comb_cycle(),
            "comb_cycle_path": self.find_comb_cycle(),
        }
