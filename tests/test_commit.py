from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from gitconvoy import commit as commit_cmd
from gitconvoy import gitutil
from gitconvoy.cli import main
from gitconvoy.gitutil import capture
from gitconvoy.state import load


def _prepare_two_dirty(workspace: Path, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.chdir(workspace)
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "handler.py").write_text("print('x')\n")
    (lib / "note.py").write_text("# blast\n")
    assert main(["--json", "feature", "adopt"]) == 0
    return schd, lib


def _last_message(repo: Path) -> str:
    return capture(repo, "log", "-1", "--format=%B")


def test_json_commit_without_apply_flags_is_plan(
    workspace: Path, monkeypatch, capsys
) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["ok"] is True
    assert plan["mode"] == "plan"
    assert plan["feature"] == "blast-radius"
    assert [row["id"] for row in plan["repos"]] == ["renglo-lib", "schd"]
    assert gitutil.is_dirty(schd)
    assert gitutil.is_dirty(lib)


def test_commit_plan_prefill_header_does_not_commit(
    workspace: Path, monkeypatch, capsys
) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(
        ["--json", "feature", "commit", "--header", "blast-radius: stubs"]
    ) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "plan"
    assert plan["header"] == "blast-radius: stubs"
    assert all(row["body"] == "" for row in plan["repos"])
    assert "diff" not in plan["repos"][0]


def test_commit_plan_diff_flag(workspace: Path, monkeypatch, capsys) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "commit", "--diff"]) == 0
    plan = json.loads(capsys.readouterr().out)
    lib_row = plan["repos"][0]
    assert lib_row["id"] == "renglo-lib"
    assert "note.py" in (lib_row.get("diff") or "")
    assert "blast" in (lib_row.get("diff") or "")


def test_commit_apply_from_file(
    workspace: Path, monkeypatch, capsys, tmp_path: Path
) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    plan["header"] = "blast-radius: mock impact-analysis stubs"
    bodies = {
        "renglo-lib": "Graph controller traversal TODO.",
        "schd": "Register cron nodes.",
    }
    for row in plan["repos"]:
        row["body"] = bodies[row["id"]]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert main(["--json", "feature", "commit", "--from", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "commit"
    assert result["ok"] is True
    assert [row["id"] for row in result["repos"]] == ["renglo-lib", "schd"]
    assert not gitutil.is_dirty(schd)
    assert not gitutil.is_dirty(lib)
    assert "mock impact-analysis stubs" in _last_message(lib)
    assert "Graph controller traversal TODO." in _last_message(lib)
    assert "Register cron nodes." in _last_message(schd)
    assert "Graph controller" not in _last_message(schd)


def test_commit_apply_mismatch_commits_nothing(
    workspace: Path, monkeypatch, capsys
) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    payload = {
        "header": "blast-radius: stubs",
        "repos": [{"id": "schd", "body": "only schd"}],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(["--json", "feature", "commit", "--from", "-"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "missing dirty repos" in err["error"]
    assert gitutil.is_dirty(schd)
    assert gitutil.is_dirty(lib)


def test_commit_header_only(workspace: Path, monkeypatch, capsys) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(
        [
            "--json",
            "feature",
            "commit",
            "--header",
            "blast-radius: mock stubs",
            "--header-only",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "commit"
    assert result["header"] == "blast-radius: mock stubs"
    assert _last_message(lib).strip() == "blast-radius: mock stubs"
    assert _last_message(schd).strip() == "blast-radius: mock stubs"
    assert not gitutil.is_dirty(lib)
    assert not gitutil.is_dirty(schd)


def test_commit_header_only_requires_header(
    workspace: Path, monkeypatch, capsys
) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "commit", "--header-only"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "requires --header" in err["error"]


def test_commit_refuses_unadopted_dirty(
    workspace: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(workspace)
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    capsys.readouterr()
    (lib / "extra.py").write_text("nope\n")
    assert main(["--json", "feature", "commit"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "not on the feature sheet" in err["error"]
    assert "renglo-lib" in err["error"]
    assert gitutil.is_dirty(schd)


def test_commit_empty_header_from_plan(
    workspace: Path, monkeypatch, capsys, tmp_path: Path
) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    plan["header"] = "   "
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert main(["--json", "feature", "commit", "--from", str(path)]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "header is empty" in err["error"]


def test_commit_nothing_to_commit(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    capsys.readouterr()
    assert main(["--json", "feature", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "plan"
    assert plan["repos"] == []


def test_commit_interactive(workspace: Path, monkeypatch) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    answers = iter(
        [
            "blast-radius: mock stubs",
            "Graph controller traversal TODO.",
            "yes",
            "Register cron nodes.",
            "yes",
        ]
    )
    data = commit_cmd.commit(
        workspace,
        load(workspace),
        input_fn=lambda prompt="": next(answers),
        write_fn=lambda text: None,
        is_tty=True,
    )
    assert data["mode"] == "commit"
    assert [row["id"] for row in data["repos"]] == ["renglo-lib", "schd"]
    assert "Graph controller traversal TODO." in _last_message(lib)
    assert "Register cron nodes." in _last_message(schd)
    assert not gitutil.is_dirty(lib)
    assert not gitutil.is_dirty(schd)


def test_color_diff_plus_minus() -> None:
    patch = "\n".join(
        [
            "diff --git a/x.py b/x.py",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,2 +1,2 @@",
            "-old",
            "+new",
            " context",
        ]
    )
    colored = commit_cmd.color_diff(patch, enabled=True)
    assert "\033[31m-old\033[0m" in colored
    assert "\033[32m+new\033[0m" in colored
    assert "\033[36m@@ -1,2 +1,2 @@\033[0m" in colored
    assert colored.splitlines()[1].startswith("\033[1m---")
    assert "\033[32m+++" not in colored
    plain = commit_cmd.color_diff(patch, enabled=False)
    assert "\033[" not in plain
    assert plain == patch


def test_commit_interactive_prompt_copy(workspace: Path, monkeypatch) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    answers = iter(["blast-radius: mock stubs", "", "yes", "", "yes"])
    lines: list[str] = []
    commit_cmd.commit(
        workspace,
        load(workspace),
        input_fn=lambda prompt="": next(answers),
        write_fn=lambda text: lines.append(text),
        is_tty=True,
    )
    text = "\n".join(lines)
    assert "Describe what changed in this repo (renglo-lib)." in text
    assert "Describe what changed in this repo (schd)." in text
    assert "Enter = header only." in text
    assert "═" in text
    assert "Shared commit header" in text


def test_commit_interactive_no_skips_repo(workspace: Path, monkeypatch) -> None:
    schd, lib = _prepare_two_dirty(workspace, monkeypatch)
    answers = iter(
        [
            "blast-radius: mock stubs",
            "Graph controller traversal TODO.",
            "no",
            "Register cron nodes.",
            "yes",
        ]
    )
    data = commit_cmd.commit(
        workspace,
        load(workspace),
        input_fn=lambda prompt="": next(answers),
        write_fn=lambda text: None,
        is_tty=True,
    )
    assert [row["id"] for row in data["repos"]] == ["schd"]
    assert gitutil.is_dirty(lib)
    assert not gitutil.is_dirty(schd)
    assert "Register cron nodes." in _last_message(schd)


def test_commit_not_a_tty(workspace: Path, monkeypatch, capsys) -> None:
    _prepare_two_dirty(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["feature", "commit"]) == 1
    captured = capsys.readouterr()
    assert "not a tty" in captured.err
