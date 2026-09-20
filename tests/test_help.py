from __future__ import annotations

import json

from gitconvoy.cli import main
from gitconvoy.help_text import HELP_SECTIONS, format_help_text


def test_help_text_lists_all_cycles(capsys) -> None:
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "Cycle 1 — Feature" in out
    assert "Cycle 4 — Production release" in out
    assert "git convoy feature start NAME" in out
    assert "git convoy train tag-rc" in out
    assert "git convoy hotfix publish" in out


def test_help_json(capsys) -> None:
    assert main(["--json", "help"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert len(data["sections"]) == len(HELP_SECTIONS)
    names = [section["name"] for section in data["sections"]]
    assert "Aux — Platform tooling" in names


def test_format_help_text_ends_with_newline() -> None:
    text = format_help_text()
    assert text.endswith("\n")
    assert text.startswith("git convoy — command sequences")
