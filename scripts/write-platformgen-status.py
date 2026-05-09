#!/usr/bin/env python3
"""Append a restart-safe work-status note for PlatformGen."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from platformgen.runtime import state_dir as runtime_state_dir
except Exception:
    runtime_state_dir = None


def main() -> int:
    note = " ".join(sys.argv[1:]).strip()
    if not note:
        print("usage: write-platformgen-status.py <note>", file=sys.stderr)
        return 2

    state_root = (
        runtime_state_dir()
        if runtime_state_dir is not None
        else Path(os.environ.get("PLATFORMGEN_HOME") or os.environ.get("AUGER_HOME") or (Path.home() / ".platformgen"))
    )
    history_dir = state_root / "logs" / "chat_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    status_file = history_dir / "work_status.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "kind": "external-status",
        "content": note,
    }
    with open(status_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(status_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
