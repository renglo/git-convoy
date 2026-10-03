"""Tests for three-BOM adopt split."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gitconvoy.bom_layout import (
    Placement,
    load_placement,
    split_master_bom,
    sync_deploy_target_versions,
    write_split_boms,
)
from gitconvoy.catalog import PackageSlot


class BomLayoutTests(unittest.TestCase):
    def test_sync_renglo_release_console_not_packages_console(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            """
name: acme
packages:
  console:
    npm: "@renglo/console"
release:
  bom: 1.0.0
  console: 1.0.0
""",
            encoding="utf-8",
        )
        sync_deploy_target_versions(root, "1.1.0")
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertIn("release:\n  bom: 1.1.0\n  console: 1.1.0", text)
        self.assertIn('  console:\n    npm: "@renglo/console"', text)

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
        self.assertEqual(console["npm"]["@renglo/console"], "9.0.0")
        self.assertEqual(console["npm"]["@renglo/gro"], "3.0.0")

    def test_split_puts_wl_python_on_hub_and_keeps_console_host(self) -> None:
        catalog = [
            PackageSlot(id="console", npm="@renglo/console"),
            PackageSlot(id="apollo-wl", python="apollo-wl", npm="@apollo/wl"),
            PackageSlot(id="data", python="renglo-data", npm="@renglo/data"),
        ]
        placement = Placement(hub_python=("renglo-data",))
        hub, console, _peers = split_master_bom(
            {
                "version": "v0.1.1",
                "python": {
                    "renglo-lib": "0.0.7rc1",
                    "renglo-api": "0.0.9rc1",
                    "apollo-wl": "0.0.2rc1",
                    "renglo-data": "0.0.6rc1",
                },
                "npm": {
                    "@renglo/console": "0.0.11-rc.1",
                    "@apollo/wl": "0.0.2-rc.1",
                    "@renglo/data": "0.0.6-rc.1",
                },
            },
            placement=placement,
            catalog=catalog,
        )
        self.assertEqual(hub["python"]["apollo-wl"], "0.0.2rc1")
        self.assertEqual(console["npm"]["@renglo/console"], "0.0.11-rc.1")
        self.assertEqual(console["npm"]["@apollo/wl"], "0.0.2-rc.1")
        self.assertNotIn("python", console)
        self.assertNotIn("npm", hub)

    def test_console_keeps_npm_when_python_moves_to_a_renamed_peer(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            """
name: apollo
placement:
  hub:
  - renglo-data
  peers:
    tourbot:
      compute: lambda_only
      extensions:
      - tourbotlink
      peers_bom: 0.1.1
packages:
  console:
    npm: '@renglo/console'
  data:
    python: renglo-data
    npm: '@renglo/data'
  tourbotlink:
    python: apollo-tourbotlink
    npm: '@apollo/tourbotlink'
release:
  bom: 0.1.1
  console: 0.1.1
""",
            encoding="utf-8",
        )
        placement = load_placement(root)
        self.assertEqual(placement.peers["tourbot"], ("apollo-tourbotlink",))
        master = {
            "version": "v0.1.1",
            "python": {
                "renglo-lib": "0.0.7rc3",
                "renglo-api": "0.0.9rc3",
                "renglo-data": "0.0.6rc1",
                "apollo-tourbotlink": "0.1.3rc1",
            },
            "npm": {
                "@renglo/console": "0.0.11-rc.3",
                "@renglo/data": "0.0.6-rc.1",
                "@apollo/tourbotlink": "0.1.3-rc.1",
            },
        }
        write_split_boms(root, "0.1.1", master)
        hub = json.loads((root / "bom/v0.1.1.json").read_text(encoding="utf-8"))
        console = json.loads((root / "console_bom/v0.1.1.json").read_text(encoding="utf-8"))
        peer = json.loads((root / "peers_bom/tourbot/v0.1.1.json").read_text(encoding="utf-8"))
        self.assertNotIn("apollo-tourbotlink", hub["python"])
        self.assertEqual(console["npm"]["@apollo/tourbotlink"], "0.1.3-rc.1")
        self.assertEqual(console["npm"]["@renglo/data"], "0.0.6-rc.1")
        self.assertEqual(peer["python"]["apollo-tourbotlink"], "0.1.3rc1")
        self.assertEqual(peer["python"]["renglo-lib"], "0.0.7rc3")
        self.assertFalse((root / "peers_bom/tourbotlink").exists())

        sync_deploy_target_versions(root, "0.1.2")
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertIn("peers_bom: 0.1.2", text)
        self.assertIn("bom: 0.1.2", text)

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
