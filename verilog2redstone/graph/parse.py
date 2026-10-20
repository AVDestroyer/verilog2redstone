from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from .cells import (
    CellKind,
    classify_cell,
    state_clock_edge,
    state_logical_type,
    state_port_roles,
)
from .ir import (
    CombCell,
    ControlEdge,
    DataEdge,
    Endpoint,
    ModuleGraph,
    Net,
    Port,
    StateCell,
)


PathLike = Union[str, Path]


def parse_yosys_json_file(
    path: PathLike,
    module_name: Optional[str] = None,
    *,
    require_acyclic: bool = True,
) -> ModuleGraph:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse_yosys_json(
        data, module_name=module_name, require_acyclic=require_acyclic
    )


def parse_yosys_json(
    data: dict[str, Any],
    module_name: Optional[str] = None,
    *,
    require_acyclic: bool = True,
) -> ModuleGraph:
    modules = data["modules"]

    if module_name is None:
        module_name = next(iter(modules))
        for name, mod in modules.items():
            attrs = mod.get("attributes") or {}
            top = attrs.get("top")
            if top in (1, "1") or (isinstance(top, str) and top.strip("0") != ""):
                module_name = name
                break

    graph = _build_module(module_name, modules[module_name])
    if require_acyclic:
        graph.validate(require_acyclic=True)
    return graph


def _bit_is_const(bit: Any) -> Optional[int]:
    if bit in (0, "0"):
        return 0
    if bit in (1, "1"):
        return 1
    return None


def _as_net_id(bit: Any) -> Optional[int]:
    """Return a signal net id, or None for constants / x / z."""
    if isinstance(bit, int) and bit >= 2:
        return bit
    if isinstance(bit, str) and bit.isdigit():
        value = int(bit)
        return value if value >= 2 else None
    return None


def _build_module(name: str, mod: dict[str, Any]) -> ModuleGraph:
    g = ModuleGraph(name=name)

    netnames = mod.get("netnames") or {}
    for nname, info in netnames.items():
        bits = info.get("bits") or []
        for bit_i, bit in enumerate(bits):
            if not isinstance(bit, int) or bit < 2:
                continue
            label = nname if len(bits) == 1 else f"{nname}[{bit_i}]"
            net = g.nets.setdefault(bit, Net(net_id=bit, name=label))
            if net.name is None:
                net.name = label

    for pname, pinfo in (mod.get("ports") or {}).items():
        direction = pinfo.get("direction", "input")
        bits = list(pinfo.get("bits") or [])
        port = Port(name=pname, direction=direction, bits=bits)
        if direction == "input":
            g.primary_inputs.append(port)
        elif direction == "output":
            g.primary_outputs.append(port)
        else:
            g.warnings.append(f"inout port not fully modeled: {pname}")
            g.primary_inputs.append(port)
            g.primary_outputs.append(port)

    for cname, cinfo in (mod.get("cells") or {}).items():
        ytype = cinfo["type"]
        kind = classify_cell(ytype)
        dirs = dict(cinfo.get("port_directions") or {})
        conns = dict(cinfo.get("connections") or {})
        if kind is CellKind.COMB:
            g.comb_cells.append(
                CombCell(
                    name=cname,
                    yosys_type=ytype,
                    port_directions=dirs,
                    connections=conns,
                )
            )
        else:
            g.state_cells.append(
                StateCell(
                    name=cname,
                    yosys_type=ytype,
                    logical_type=state_logical_type(ytype),
                    clock_edge=state_clock_edge(ytype),
                    port_directions=dirs,
                    connections=conns,
                    roles=state_port_roles(ytype),
                )
            )

    _register_endpoints(g)
    _emit_edges(g)
    return g


def _ensure_net(g: ModuleGraph, net_id: int) -> Net:
    if net_id not in g.nets:
        g.nets[net_id] = Net(net_id=net_id)
    return g.nets[net_id]


def _register_endpoints(g: ModuleGraph) -> None:
    for port in g.primary_inputs:
        for bit_i, bit in enumerate(port.bits):
            const = _bit_is_const(bit)
            if const is not None:
                g.warnings.append(f"primary input {port.name} tied to const {const}")
                continue
            net_id = _as_net_id(bit)
            if net_id is None:
                g.warnings.append(f"unhandled bit on input {port.name}: {bit!r}")
                continue
            ep = Endpoint(node=port.name, port="", bit=bit_i)
            _ensure_net(g, net_id).drivers.append(ep)

    for port in g.primary_outputs:
        for bit_i, bit in enumerate(port.bits):
            const = _bit_is_const(bit)
            if const is not None:
                g.warnings.append(f"primary output {port.name} tied to const {const}")
                continue
            net_id = _as_net_id(bit)
            if net_id is None:
                g.warnings.append(f"unhandled bit on output {port.name}: {bit!r}")
                continue
            ep = Endpoint(node=port.name, port="", bit=bit_i)
            _ensure_net(g, net_id).sinks.append(ep)

    for cell in g.comb_cells:
        for pname, direction in cell.port_directions.items():
            bits = cell.connections.get(pname) or []
            for bit_i, bit in enumerate(bits):
                const = _bit_is_const(bit)
                if const is not None:
                    if direction == "input":
                        synth = _const_net(g, const)
                        ep = Endpoint(node=cell.name, port=pname, bit=bit_i)
                        _ensure_net(g, synth).sinks.append(ep)
                    continue
                net_id = _as_net_id(bit)
                if net_id is None:
                    g.warnings.append(
                        f"unhandled bit on {cell.name}.{pname}: {bit!r}"
                    )
                    continue
                ep = Endpoint(node=cell.name, port=pname, bit=bit_i)
                net = _ensure_net(g, net_id)
                if direction == "output":
                    net.drivers.append(ep)
                else:
                    net.sinks.append(ep)

    for cell in g.state_cells:
        roles = cell.roles
        data_in = roles.get("data_in")
        data_out = roles.get("data_out")
        control_ports = {
            roles[k]: k for k in ("clock", "reset", "enable") if k in roles
        }

        for pname, direction in cell.port_directions.items():
            bits = cell.connections.get(pname) or []
            for bit_i, bit in enumerate(bits):
                const = _bit_is_const(bit)
                if const is not None:
                    if direction == "input":
                        synth = _const_net(g, const)
                        ep = Endpoint(node=cell.name, port=pname, bit=bit_i)
                        _ensure_net(g, synth).sinks.append(ep)
                    continue
                net_id = _as_net_id(bit)
                if net_id is None:
                    g.warnings.append(
                        f"unhandled bit on {cell.name}.{pname}: {bit!r}"
                    )
                    continue
                ep = Endpoint(node=cell.name, port=pname, bit=bit_i)
                net = _ensure_net(g, net_id)

                if pname == data_out:
                    net.drivers.append(ep)
                elif pname == data_in:
                    net.sinks.append(ep)
                elif pname in control_ports:
                    net.sinks.append(ep)
                elif direction == "output":
                    net.drivers.append(ep)
                else:
                    net.sinks.append(ep)
                    g.warnings.append(
                        f"state cell port treated as data sink: {cell.name}.{pname}"
                    )


def _const_net(g: ModuleGraph, value: int) -> int:
    for existing, v in g.constants.items():
        if v == value:
            return existing
    synth_id = -(value + 1)
    g.constants[synth_id] = value
    node = f"CONST_{value}"
    net = _ensure_net(g, synth_id)
    net.name = f"const_{value}"
    if not net.drivers:
        net.drivers.append(Endpoint(node=node, port="Y", bit=0))
    return synth_id


def _emit_edges(g: ModuleGraph) -> None:
    state_by_name = {c.name: c for c in g.state_cells}
    control_port_role: dict[tuple[str, str], str] = {}
    for cell in g.state_cells:
        for role, pname in cell.roles.items():
            if role in ("clock", "reset", "enable"):
                control_port_role[(cell.name, pname)] = role

    for net_id, net in g.nets.items():
        if not net.drivers:
            if net.sinks:
                g.warnings.append(f"net {net_id} has sinks but no driver")
            continue
        if len(net.drivers) > 1:
            g.warnings.append(
                f"net {net_id} has multiple drivers: "
                + ", ".join(str(d) for d in net.drivers)
            )

        for driver in net.drivers:
            for sink in net.sinks:
                role = control_port_role.get((sink.node, sink.port))
                if role is not None:
                    g.control_edges.append(
                        ControlEdge(
                            net_id=net_id, src=driver, dst=sink, role=role
                        )
                    )
                    continue

                # State boundaries must not introduce internal Q-to-D edges.
                if (
                    driver.node == sink.node
                    and driver.node in state_by_name
                ):
                    g.warnings.append(
                        f"skipped intra-state data edge on {driver.node} "
                        f"({driver.port}->{sink.port})"
                    )
                    continue

                g.data_edges.append(
                    DataEdge(net_id=net_id, src=driver, dst=sink)
                )
