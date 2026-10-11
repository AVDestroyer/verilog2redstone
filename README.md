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
