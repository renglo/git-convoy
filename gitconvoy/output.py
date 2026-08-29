from __future__ import annotations

import json
import sys
from typing import Any


def emit(data: Any, as_json: bool, text: str | None = None) -> None:
    if as_json:
        json.dump(data, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    if text is None:
        json.dump(data, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def fail(message: str, as_json: bool) -> int:
    if as_json:
        json.dump({"ok": False, "error": message}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"git-convoy: {message}\n")
    return 1
