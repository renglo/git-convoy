from __future__ import annotations

from gitconvoy.catalog import parse_package_catalog, slot_for_repo


def test_parse_package_catalog() -> None:
    catalog = parse_package_catalog(
        """
bom: 1.4.0
packages:
  renglo-lib:
    python: renglo-lib
  skbrk-wl:
    npm: "@skbrk/wl"
  pes:
    python: renglo-pes
    repo: renglo/pes
tenants:
  stanley:
    id: x
"""
    )
    assert catalog is not None
    by_id = {slot.id: slot for slot in catalog}
    assert by_id["renglo-lib"].python == "renglo-lib"
    assert by_id["skbrk-wl"].npm == "@skbrk/wl"
    assert by_id["pes"].repo == "renglo/pes"


def test_absent_packages_is_none() -> None:
    assert parse_package_catalog("bom: 1.4.0\n") is None


def test_slot_for_repo_matches_id_then_npm() -> None:
    catalog = parse_package_catalog(
        "packages:\n  skbrk-wl:\n    npm: \"@skbrk/wl\"\n"
    )
    assert catalog is not None
    assert slot_for_repo(catalog, "skbrk-wl").id == "skbrk-wl"
    assert slot_for_repo(catalog, "other", npm_name="@skbrk/wl").id == "skbrk-wl"
