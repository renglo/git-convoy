"""Tests for three-BOM adopt split."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gitconvoy.bom_layout import (
    Placement,
    split_master_bom,
    sync_deploy_target_versions,
    write_split_boms,
)
from gitconvoy.catalog import PackageSlot


class BomLayoutTests(unittest.TestCase):
    def test_sync_deploy_target_versions(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "deploy_targets.yml").write_text(
            "bom: 1.0.0\n\nhub:\n  python:\n    - renglo-gro\n\npeers:\n  lab:\n    python:\n      - acme-lab\n    peers_bom: 1.0.0\n",
            encoding="utf-8",
        )
        sync_deploy_target_versions(root, "1.1.0")
        text = (root / "deploy_targets.yml").read_text(encoding="utf-8")
        self.assertIn("bom: 1.1.0", text)
        self.assertIn("console_bom: 1.1.0", text)
        self.assertIn("peers_bom: 1.1.0", text)

    def test_write_split_boms(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "deploy_targets.yml").write_text(
            """
packages:
  console:
    npm: "@renglo/console"
hub:
  python:
    - renglo-gro
""",
            encoding="utf-8",
        )
        catalog = [
            PackageSlot(id="console", npm="@renglo/console"),
            PackageSlot(id="gro", python="renglo-gro", npm="@renglo/gro"),
        ]
        placement = Placement(hub_python=("renglo-gro",))
        master = {
            "version": "v2.0.0",
            "python": {"renglo-lib": "1.0.0", "renglo-api": "1.0.0", "renglo-gro": "3.0.0"},
            "npm": {"@renglo/console": "9.0.0", "@renglo/gro": "3.0.0"},
        }
        write_split_boms(root, "2.0.0", master, catalog=catalog, placement=placement)
        hub = json.loads((root / "bom/v2.0.0.json").read_text(encoding="utf-8"))
        console = json.loads((root / "console_bom/v2.0.0.json").read_text(encoding="utf-8"))
        self.assertNotIn("npm", hub)
        self.assertNotIn("python", console)
        self.assertEqual(hub["python"]["renglo-gro"], "3.0.0")
        self.assertEqual(console["npm"]["@renglo/gro"], "3.0.0")

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
