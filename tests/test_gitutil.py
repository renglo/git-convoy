from __future__ import annotations

from pathlib import Path

from gitconvoy import gitutil


def test_github_slug_ssh_alias(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_origin(_repo: Path) -> str:
        return "git@github-arbitium:Arbitium/arbitium-wl.git"

    monkeypatch.setattr(gitutil, "origin_url", fake_origin)
    assert gitutil.github_slug(repo) == "Arbitium/arbitium-wl"


def test_github_slug_standard_forms(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cases = [
        ("git@github.com:renglo/schd.git", "renglo/schd"),
        ("https://github.com/renglo/schd.git", "renglo/schd"),
        ("https://github.com/renglo/schd", "renglo/schd"),
        ("ssh://git@github.com/renglo/schd.git", "renglo/schd"),
    ]
    for url, expected in cases:
        monkeypatch.setattr(gitutil, "origin_url", lambda _r, u=url: u)
        assert gitutil.github_slug(repo) == expected, url


def test_push_branch_and_tag_one_git_push(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    calls: list[tuple] = []

    def record_push(path: Path, *args: str) -> None:
        calls.append((path, args))

    monkeypatch.setattr(gitutil, "push", record_push)
    gitutil.push_branch_and_tag(repo, "release/2026-09-30", "v0.1.2-rc.1", set_upstream=True)
    gitutil.push_branch_and_tag(repo, "main", "v0.1.2")
    assert calls == [
        (repo, ("-u", "origin", "release/2026-09-30", "v0.1.2-rc.1")),
        (repo, ("origin", "main", "v0.1.2")),
    ]
