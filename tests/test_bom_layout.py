"""Tests for three-BOM adopt split."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from gitconvoy.adopt import _pointed_version, point
from gitconvoy.bom_layout import (
    Placement,
    apply_released_platform,
    load_placement,
    load_platform,
    load_staging_platform,
    promote_staging_pins,
    split_master_bom,
    staging_release_pin,
    sync_deploy_target_versions,
    sync_staging_pins,
    write_bom_file,
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
        self.assertNotIn("platform", hub)
        self.assertNotIn("platform", console)

    def test_write_split_boms_stamps_platform_from_renglo_yaml(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            """
name: apollo
platform: v0.1.4
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
  data:
    python: renglo-data
    npm: '@renglo/data'
  tourbotlink:
    python: apollo-tourbotlink
    npm: '@apollo/tourbotlink'
  console:
    npm: '@renglo/console'
release:
  bom: 0.1.1
  console: 0.1.1
""",
            encoding="utf-8",
        )
        self.assertEqual(load_platform(root), "0.1.4")
        master = {
            "version": "v0.1.1",
            "created_at": "2026-10-01T01:45:00Z",
            "description": "Production. Release 2026-09-30.",
            "train": "2026-09-30",
            "platform": "0.0.1",
            "python": {"renglo-lib": "0.0.7", "renglo-data": "0.0.6", "apollo-tourbotlink": "0.1.2"},
            "npm": {"@renglo/console": "0.0.11", "@renglo/data": "0.0.6", "@apollo/tourbotlink": "0.1.2"},
        }
        write_split_boms(root, "0.1.1", master)
        hub = json.loads((root / "bom/v0.1.1.json").read_text(encoding="utf-8"))
        console = json.loads((root / "console_bom/v0.1.1.json").read_text(encoding="utf-8"))
        peer = json.loads((root / "peers_bom/tourbot/v0.1.1.json").read_text(encoding="utf-8"))
        for document in (hub, console, peer):
            self.assertEqual(document["platform"], "0.1.4")
            keys = list(document)
            self.assertLess(keys.index("train"), keys.index("platform"))
            self.assertLess(
                keys.index("platform"),
                keys.index("python" if "python" in document else "npm"),
            )

    def test_write_bom_file_drops_stale_platform_when_renglo_yaml_has_none(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text("name: apollo\n", encoding="utf-8")
        path = root / "bom.json"
        write_bom_file(
            root,
            path,
            {"version": "v0.1.1", "train": "2026-09-30", "platform": "0.0.1", "python": {}},
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("platform", data)
        self.assertEqual(data["train"], "2026-09-30")

    def test_train_renglo_ops_replaces_renglo_yaml_platform(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            "name: apollo\nplatform: 0.1.4\naccounts:\n  staging:\n    id: '1'\n",
            encoding="utf-8",
        )
        repos = [
            SimpleNamespace(id="data", path="extensions/data", to="0.0.7"),
            SimpleNamespace(id="renglo-ops", path="ops/renglo-ops", to="v0.1.5rc1"),
        ]
        self.assertEqual(apply_released_platform(root, repos), "0.1.5rc1")
        self.assertEqual(load_platform(root), "0.1.4")
        self.assertEqual(load_staging_platform(root), "0.1.5rc1")
        self.assertIn("accounts:", (root / "renglo.yaml").read_text(encoding="utf-8"))
        write_bom_file(root, root / "v0.1.2.json", {"version": "v0.1.2", "train": "2026-10-04"})
        document = json.loads((root / "v0.1.2.json").read_text(encoding="utf-8"))
        self.assertEqual(document["platform"], "0.1.5rc1")

        untouched = apply_released_platform(
            root,
            [SimpleNamespace(id="data", path="extensions/data", to="0.0.8")],
        )
        self.assertEqual(untouched, "")
        self.assertEqual(load_platform(root), "0.1.4")
        self.assertEqual(load_staging_platform(root), "0.1.5rc1")

    def test_staging_block_holds_peer_pins_until_promote(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            """
name: apollo
platform: 0.1.4
release:
  bom: 0.1.1
  console: 0.1.1
placement:
  peers:
    tourbot:
      extensions:
        - tourbotlink
      peers_bom: 0.1.1
accounts:
  production:
    enabled: true
""".lstrip(),
            encoding="utf-8",
        )
        sync_staging_pins(root, "v0.1.2", platform="0.1.5rc1")
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertIn("platform: 0.1.4\n", text)
        self.assertIn("  bom: 0.1.1\n", text)
        self.assertIn("  console: 0.1.1\n", text)
        self.assertIn("peers_bom: 0.1.1\n", text)
        self.assertIn("staging:\n", text)
        self.assertIn("    tourbot: 0.1.2\n", text)
        self.assertEqual(load_staging_platform(root), "0.1.5rc1")
        self.assertEqual(staging_release_pin(root), "0.1.2")
        self.assertEqual(_pointed_version(root, prefer_staging=True), "0.1.2")
        self.assertEqual(_pointed_version(root), "0.1.1")
        staged = point(root, "0.1.2", bom=str(root))
        self.assertTrue(staged["production_enabled"])
        self.assertIn("production pins were left in place", staged["note"])
        self.assertIn("enabled: true", (root / "renglo.yaml").read_text(encoding="utf-8"))

        sync_deploy_target_versions(root, "v0.1.3")
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertIn("  bom: 0.1.3\n", text)
        self.assertIn("peers_bom: 0.1.3\n", text)
        self.assertIn("    tourbot: 0.1.2\n", text)
        self.assertEqual(staging_release_pin(root), "0.1.2")

        self.assertTrue(promote_staging_pins(root))
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertNotIn("staging:", text)
        self.assertIn("platform: 0.1.5rc1\n", text)
        self.assertIn("  bom: 0.1.2\n", text)
        self.assertIn("  console: 0.1.2\n", text)
        self.assertIn("peers_bom: 0.1.2\n", text)
        self.assertFalse(promote_staging_pins(root))

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
        self.assertEqual(placement.hub_python, ("renglo-data",))
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
        self.assertNotIn("deploy_stage", peer)
        self.assertFalse((root / "peers_bom/tourbotlink").exists())

        sync_deploy_target_versions(root, "0.1.2")
        text = (root / "renglo.yaml").read_text(encoding="utf-8")
        self.assertIn("peers_bom: 0.1.2", text)
        self.assertIn("bom: 0.1.2", text)

    def test_load_placement_resolves_hub_catalog_handles(self) -> None:
        root = Path(self._tmp()) / "bom"
        root.mkdir()
        (root / "renglo.yaml").write_text(
            """
name: stanley
placement:
  hub:
  - data
  - breakdown
  peers: {}
packages:
  data:
    python: renglo-data
  breakdown:
    python: skbrk-breakdown
release:
  bom: 0.1.0
  console: 0.1.0
""",
            encoding="utf-8",
        )
        placement = load_placement(root)
        self.assertEqual(placement.hub_python, ("renglo-data", "skbrk-breakdown"))

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
