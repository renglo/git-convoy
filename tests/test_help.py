from __future__ import annotations

import json

from gitconvoy.cli import main
from gitconvoy.help_text import (
    HELP_GROUPS,
    HELP_SECTIONS,
    format_help_text,
    resolve_help_topic,
)


def test_help_text_lists_all_cycles(capsys) -> None:
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "Cycle 1 — Feature" in out
    assert "Cycle 4 — Production release" in out
    assert "git convoy feature start NAME" in out
    assert "git convoy train tag-rc" in out
    assert "git convoy hotfix publish" in out
    assert "Topics:" in out


def test_help_text_groups_the_three_golden_paths(capsys) -> None:
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    for group in HELP_GROUPS:
        assert group["title"] in out
        assert group["note"] in out
    product = out.index("PRODUCT — features into a running environment")
    ops = out.index("OPS — operator tooling into the registries")
    hotfix = out.index("HOTFIX — patch production now")
    assert product < ops < hotfix
    assert out.index("Cycle 1 — Feature") < out.index("Product — optional") < ops
    assert ops < out.index("git convoy ops cut NAME") < hotfix
    assert ops < out.index("git convoy ops tag-rc") < hotfix
    assert ops < out.index("git convoy ops release REPO") < hotfix
    assert "ops/git-convoy/README.md" in out


def test_help_json(capsys) -> None:
    assert main(["--json", "help"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["topic"] == "all"
    assert len(data["sections"]) == len(HELP_SECTIONS)
    names = [section["name"] for section in data["sections"]]
    assert "Ops cycle 1 — land tooling on develop" in names
    assert "Ops cycle 2 — release the whole convoy" in names
    first_cmd = data["sections"][0]["commands"][0]
    assert "cmd" in first_cmd
    assert "summary" in first_cmd
    keys = [group["key"] for group in data["groups"]]
    assert keys == [group["key"] for group in HELP_GROUPS]
    assert [section["group"] for section in data["sections"]] == sorted(
        (section["group"] for section in data["sections"]), key=keys.index
    )


def test_format_help_text_ends_with_newline() -> None:
    text = format_help_text()
    assert text.endswith("\n")
    assert text.startswith("git convoy — quick reference")


def test_help_feature_topic(capsys) -> None:
    assert main(["help", "feature"]) == 0
    out = capsys.readouterr().out
    assert "git convoy help feature" in out
    assert "git convoy feature start NAME" in out
    assert "git convoy sync" in out
    assert "git convoy hotfix publish" in out
    assert "git convoy feature refresh" in out
    assert "git convoy bom" not in out


def test_help_train_includes_bom(capsys) -> None:
    assert main(["help", "train"]) == 0
    out = capsys.readouterr().out
    assert "git convoy train cut NAME" in out
    assert "git convoy train tag-rc" in out
    assert "git convoy bom --bom" in out
    assert "git convoy bom --production" in out
    assert out.index("train cut") < out.index("tag-rc") < out.index("bom --production")


def test_help_summaries_flag(capsys) -> None:
    assert main(["help", "hotfix", "--summaries"]) == 0
    out = capsys.readouterr().out
    assert "git convoy hotfix start NAME" in out
    assert "Branch hotfix/NAME from main" in out
    assert "git convoy feature refresh" in out


def test_help_summaries_short_flag(capsys) -> None:
    assert main(["help", "staging", "-s"]) == 0
    out = capsys.readouterr().out
    assert "git convoy train tag-rc" in out
    assert "push rc tags" in out.lower()


def test_help_unknown_topic(capsys) -> None:
    assert main(["help", "nope"]) == 1
    err = capsys.readouterr().err
    assert "unknown help topic" in err


def test_resolve_help_topic_aliases() -> None:
    assert resolve_help_topic("cycle1") == "feature"
    assert resolve_help_topic("release") == "train"
    assert resolve_help_topic("platform") == "ops"
