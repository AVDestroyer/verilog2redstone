from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTH_SH = REPO_ROOT / "scripts" / "synth.sh"
EXAMPLES = REPO_ROOT / "examples"
BUILD = EXAMPLES / "build"


def synth(verilog_name: str, top: str | None = None) -> Path:
    verilog = EXAMPLES / verilog_name
    if not verilog.is_file():
        raise FileNotFoundError(verilog)
    module = top or verilog.stem
    out = BUILD / f"{verilog.stem}.json"
    cmd = [str(SYNTH_SH), str(verilog), module, str(out)]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, capture_output=True, text=True)
    return out
