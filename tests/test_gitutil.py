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
