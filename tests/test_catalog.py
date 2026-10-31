from __future__ import annotations

from gitconvoy.catalog import (
    parse_package_catalog,
    parse_registry_scopes,
    slot_for_repo,
    slot_served_by_registry,
    unregistered_wl_slots,
)


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


def test_scalar_console_line_is_not_an_npm_slot() -> None:
    """A mashed `console: 0.1.1 '@renglo/console'` is not a package map.

    git convoy never writes ``packages:``. If that scalar form lands in
    renglo.yaml, adopt must not treat it as ``npm: @renglo/console`` or
    the console host pin is dropped on the next take.
    """
    catalog = parse_package_catalog(
        """
packages:
  renglo-api:
    python: renglo-api
  console: 0.1.1 '@renglo/console'
  apollo-wl:
    python: apollo-wl
    npm: '@apollo/wl'
"""
    )
    assert catalog is not None
    by_id = {slot.id: slot for slot in catalog}
    assert "console" not in by_id
    assert by_id["apollo-wl"].python == "apollo-wl"
    assert by_id["apollo-wl"].npm == "@apollo/wl"


def test_console_mapping_and_wl_python_are_catalogued() -> None:
    catalog = parse_package_catalog(
        """
packages:
  console:
    npm: '@renglo/console'
  apollo-wl:
    python: apollo-wl
    npm: '@apollo/wl'
"""
    )
    assert catalog is not None
    by_id = {slot.id: slot for slot in catalog}
    assert by_id["console"].npm == "@renglo/console"
    assert by_id["apollo-wl"].python == "apollo-wl"


def test_slot_for_repo_matches_id_then_npm() -> None:
    catalog = parse_package_catalog(
        "packages:\n  skbrk-wl:\n    npm: \"@skbrk/wl\"\n"
    )
    assert catalog is not None
    assert slot_for_repo(catalog, "skbrk-wl").id == "skbrk-wl"
    assert slot_for_repo(catalog, "other", npm_name="@skbrk/wl").id == "skbrk-wl"


def test_registry_scopes_decide_whether_a_wl_pack_exists() -> None:
    text = """
registries:
- domain: renglo
  scopes:
  - '@renglo'
packages:
  liga-wl:
    python: liga-wl
    npm: '@liga/wl'
  data:
    python: renglo-data
    npm: '@renglo/data'
"""
    scopes = parse_registry_scopes(text)
    assert scopes == {"@renglo"}
    catalog = parse_package_catalog(text)
    assert catalog is not None
    liga = next(slot for slot in catalog if slot.id == "liga-wl")
    data = next(slot for slot in catalog if slot.id == "data")
    assert slot_served_by_registry(data, scopes)
    assert not slot_served_by_registry(liga, scopes)
    assert [slot.id for slot in unregistered_wl_slots(catalog, scopes)] == ["liga-wl"]
    assert unregistered_wl_slots(catalog, {"@liga", "@renglo"}) == []
    assert parse_registry_scopes("registries: []\n") == set()
