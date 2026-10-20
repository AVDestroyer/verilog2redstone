# verilog2redstone

Compile a subset of Verilog into Minecraft redstone circuits, with support for
synchronous / sequential RTL. Currently we only support
**Minecraft 1.16.5**.

Inspired by [itsfrank/MinecraftHDL](https://github.com/itsfrank/MinecraftHDL).
MinecraftHDL’s pipeline works for combinational logic, but does not implement
sequential logic. This project aims to fix that. This project also uses 0-tick
combinational logic using an update suppression "bug" in Minecraft 1.16.5,
allowing for less delays when placement/routing.

## Status

Done so far:

1. Frontend (using Yosys): Compiles RTL into a netlist that only contains cells
   from our library.
2. Graph IR: parses inputs and outputs, combinational logic, registers, and
   creates data/control edges.
3. Cell Library: a few 0-tick cells in Minecraft. More coming later.
4. Basic Placement algorithm using simulated annealing.

## Requirements

- [Yosys](https://yosyshq.net/yosys/) (tested with 0.33)
- Python 3.10+ (stdlib only for the graph frontend)
- [Litemapy](https://pypi.org/project/litemapy/) (to explore Litematica designs)

Install Yosys on Ubuntu or Debian:

```bash
sudo apt update
sudo apt install yosys
```

Install Yosys on macOS with Homebrew:

```bash
brew install yosys
```

On Windows, use WSL and follow the Ubuntu instructions. See the
[official Yosys installation guide](https://yosyshq.readthedocs.io/projects/yosys/en/stable/getting_started/installation.html)
for source builds and other platforms.

Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick start

```bash
# Verilog → Yosys JSON (writes examples/build/<name>.json)
./scripts/synth.sh examples/minimal_toggle.v minimal_toggle

# Yosys JSON → graph summary
python3 -m verilog2redstone.graph examples/build/minimal_toggle.json

# Dump the graph as JSON
python3 -m verilog2redstone.graph examples/build/minimal_toggle.json \
  --json-out examples/build/minimal_toggle.graph.json

# Run the placement example
python3 scripts/place_adder4.py

# Run tests (requires yosys)
python3 -m unittest discover -s tests -v
```

## Graph model

The frontend builds a sequential-aware graph, with the following elements:

- Combinational cells
- Registers
- Data edges between source and destination ports
- Control edges: clocks

Each data edge represents signal flow from an output port to an input port.
Examples include a primary input driving a gate, one gate driving another,
a register's `Q` output driving combinational logic, or combinational logic
driving a register's `D` input.

State cells are split at the register boundary for DAG analysis: `Q` is a
source into combinational logic, `D` is a sink from it.

**Combinational loops are disallowed.** Parsing rejects them by default
(`CombCycleError`).

## Supported Yosys cells

Currently, we only support the following gates/cells:

- NAND
- NOT
- OR
- Positive D-flip-flop

More gates are coming in the future.

## Placement API

We currently support only placing combinational circuits. The placer
assigns graph cells to physical library cells and uses simulated annealing to
try to optimize the design according to a few cost objectives.

```python
from verilog2redstone.cell_library import load_cell_library
from verilog2redstone.graph import parse_yosys_json_file
from verilog2redstone.placement import (
    AnnealingConfig,
    BoundingBox,
    place,
    save_placement_litematic,
)

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

save_placement_litematic(
    result.placement,
    "examples/build/adder4.placement.litematic",
)
```

`save_placement_litematic` writes the placed cells to a Litematica schematic.
Routing is not included yet.
