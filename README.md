# verilog2redstone

Compile a subset of Verilog into Minecraft redstone circuits, with real support for synchronous / sequential RTL.

Inspired by [itsfrank/MinecraftHDL](https://github.com/itsfrank/MinecraftHDL), but not a fork. MinecraftHDL’s pipeline works for combinational logic, but does not implement sequential logic. This project aims to fix that. This project also uses 0-tick combinational logic using an update suppression "bug" in Minecraft 1.18, allowing for less delays when placement/routing.

## Status

Done so far:

1. **Yosys frontend script** — Compiles RTL into a netlist that only contains cells from our library.
2. **Sequential-aware graph IR** — parses primary I/O, combinational cells, positive-edge logical `REGISTER` cells, **data edges**, and clock **control edges**.
3. **Cell Library**
4. **Examples + tests**

## Requirements

- [Yosys](https://yosyshq.net/yosys/) (tested with 0.33)
- Python 3.10+ (stdlib only for the graph frontend)
- [Litemapy](https://pypi.org/project/litemapy/) (placement export only)

## Quick start

```bash
# Verilog → Yosys JSON (writes examples/build/<name>.json)
./scripts/synth.sh examples/minimal_toggle.v minimal_toggle

# Yosys JSON → sequential-aware graph summary
python3 -m compiler.graph examples/build/minimal_toggle.json

# Fail on combinational loops (default)
python3 -m compiler.graph examples/build/comb_loop.json

# Optional: dump the graph as JSON
python3 -m compiler.graph examples/build/minimal_toggle.json \
  --json-out examples/build/minimal_toggle.graph.json

# Run tests (synth + parse assertions; requires yosys)
python3 -m unittest discover -s tests -v
```

### Synth script

```bash
./scripts/synth.sh <verilog_file> [top_module] [output_json]
```

Defaults to `examples/build/<verilog_basename>.json`. The Yosys template is [`scripts/to_json.ys`](scripts/to_json.ys).

## Graph model

The frontend builds a sequential-aware graph:

| Concept             | Role                                                       |
| ------------------- | ---------------------------------------------------------- |
| Combinational cells | `NAND`, `NOT`, and `OR`                                    |
| State cells         | Positive-edge logical `REGISTER` (`$_DFF_P_`)              |
| Data edges          | Value flow for placement layering (`Q → NOT → D`, outputs) |
| Control edges       | Clock attachment to registers (not used for topo sort)     |

State cells are split at the register boundary for DAG analysis: `Q` is a source into combinational logic, `D` is a sink from it.

**Combinational loops are disallowed.** Parsing rejects them by default (`CombCycleError`).

## Supported Yosys cells

For our first version, we only support the following gates/cells

- NAND
- NOT
- OR
- Positive D-flip-flop

More gates are coming in the future.

## Placement API

The initial fixed-orientation placer supports purely combinational graphs. It
assigns graph cells to physical library cells and uses simulated annealing to
search within a caller-supplied bounding box. Initialization follows the
combinational graph's topological order. Moves that put a destination input
behind its source output in X are rejected as illegal:

```python
from compiler.cell_library import load_cell_library
from compiler.graph import parse_yosys_json_file
from compiler.placement import AnnealingConfig, BoundingBox, place

graph = parse_yosys_json_file("examples/build/adder4.json")
library = load_cell_library("litematica-cells")
result = place(
    graph,
    library,
    BoundingBox(size=(80, 20, 40)),
    AnnealingConfig(seed=123, trace_interval=100),
)

print(result.cost)
for cell in result.placement.cells.values():
    print(cell.graph_cell, cell.physical_cell.cell_id, cell.origin)
```

Primary I/O and constant endpoints are ignored until they have physical
placements. The optional trace records sampled current and best costs for
inspection or plotting.

To run a reproducible placement smoke test and generate an SVG with top, side,
and front views:

```bash
python3 scripts/place_mux2.py
```

The script writes `mux2.placement.svg` and `mux2.placement.json` under
`examples/build/`.

The larger combinational `adder4` example uses 30 physical cells and can be
run in the same way:

```bash
python3 scripts/place_adder4.py
```

To generate a detailed report for the topological placement:

```bash
python3 scripts/compare_adder4_initializers.py
```

To combine the latest final topological placement into one Litematica
schematic containing all gate blocks and block entities:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/export_adder4_litematic.py
```

The exporter writes `adder4.topological.placement.litematic` under
`examples/build/`. Routing is not included yet.
