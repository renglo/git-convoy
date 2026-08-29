from __future__ import annotations

import json
from pathlib import Path

from gitconvoy import adopt as adopt_cmd


def test_draft_and_pin(tmp_path: Path) -> None:
    bom_repo = tmp_path / "ops" / "stanley-bom"
    (bom_repo / "bom").mkdir(parents=True)
    (bom_repo / "bom" / "v1.4.0.json").write_text(
        json.dumps(
            {
                "version": "v1.4.0",
                "python": {"renglo-lib": "1.2.3", "renglo-schd": "1.1.0"},
                "npm": {"@renglo/console": "0.8.0"},
            },
            indent=2,
        )
        + "\n"
    )
    (bom_repo / "deploy_targets.yml").write_text(
        "bom: 1.4.0\n\ntenants:\n  stanley:\n    stages:\n"
        "      staging:\n        enabled: true\n"
        "      production:\n        enabled: true\n"
    )
    ws = tmp_path
    from gitconvoy.state import State

    state = State()
    adopt_cmd.draft(ws, state, "1.4.0", "1.5.0", bom=str(bom_repo), train="2026-W34")
    dest = bom_repo / "bom" / "v1.5.0.json"
    data = json.loads(dest.read_text())
    assert data["version"] == "v1.5.0"
    assert data["train"] == "2026-W34"
    adopt_cmd.pin(ws, "1.5.0", "renglo-lib", "1.2.4", bom=str(bom_repo))
    data = json.loads(dest.read_text())
    assert data["python"]["renglo-lib"] == "1.2.4"
    adopt_cmd.point(ws, "1.5.0", bom=str(bom_repo), production=False)
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.5.0" in text
    assert "enabled: false" in text
