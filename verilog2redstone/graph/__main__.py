"""CLI: parse a Yosys JSON netlist into the sequential-aware graph IR."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ir import CombCycleError
from .parse import parse_yosys_json_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse Yosys JSON into a sequential-aware ModuleGraph."
    )
    parser.add_argument("json_path", type=Path, help="Path to Yosys .json netlist")
    parser.add_argument(
        "-m",
        "--module",
        default=None,
        help="Module name (default: Yosys top / first module)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the graph as JSON",
    )
    parser.add_argument(
        "--allow-comb-cycles",
        action="store_true",
        help="Do not reject combinational loops (debug only; not a supported design)",
    )
    args = parser.parse_args(argv)

    try:
        graph = parse_yosys_json_file(
            args.json_path,
            module_name=args.module,
            require_acyclic=not args.allow_comb_cycles,
        )
    except CombCycleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Combinational loops are not supported. "
            "Fix the RTL, or pass --allow-comb-cycles only to inspect the graph.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(graph.summary())

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(graph.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nWrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
