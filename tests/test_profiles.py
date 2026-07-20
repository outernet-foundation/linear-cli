from __future__ import annotations

from pathlib import Path

import pytest
import typer

from linear_cli.profiles import (
    Profile,
    ProfileConfig,
    flatten_paths,
    load_config,
    resolve_profile_name,
    write_config,
)


def _config() -> ProfileConfig:
    return ProfileConfig(
        profiles={
            "foundation": Profile(
                api_key="key-foundation",
                paths=[
                    "/workspace/placeframe",
                    "/workspace/placeframe/deeply/nested",
                    "/workspace/governance",
                ],
            ),
            "personal": Profile(
                api_key="key-personal",
                paths=[
                    "/workspace/pulsar",
                ],
            ),
        },
    )


def test_flatten_paths_maps_each_path_to_its_profile() -> None:
    path_map = flatten_paths(_config())
    assert path_map["/workspace/placeframe"] == "foundation"
    assert path_map["/workspace/governance"] == "foundation"
    assert path_map["/workspace/pulsar"] == "personal"


def test_override_wins() -> None:
    config = _config()
    assert resolve_profile_name(config, "personal", Path("/workspace/placeframe")) == "personal"


def test_override_unknown_profile_errors() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_profile_name(config, "nonexistent", Path("/workspace/placeframe"))


def test_exact_path_match() -> None:
    config = _config()
    assert resolve_profile_name(config, None, Path("/workspace/pulsar")) == "personal"


def test_longest_prefix_wins() -> None:
    config = _config()
    assert resolve_profile_name(config, None, Path("/workspace/placeframe/deeply/nested")) == "foundation"


def test_prefix_below_registered_path_matches_parent_profile() -> None:
    config = _config()
    assert resolve_profile_name(config, None, Path("/workspace/pulsar/scripts/src")) == "personal"


def test_sibling_directory_does_not_match() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_profile_name(config, None, Path("/workspace/placeframe-foo"))


def test_no_match_errors() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_profile_name(config, None, Path("/var/empty"))


def test_load_config_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") is None


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "linear-cli" / "config.json"
    original = _config()
    write_config(original, path)
    loaded = load_config(path)
    assert loaded is not None
    assert loaded.profiles["foundation"].api_key == "key-foundation"
    assert loaded.profiles["foundation"].paths == [
        "/workspace/placeframe",
        "/workspace/placeframe/deeply/nested",
        "/workspace/governance",
    ]
    assert loaded.profiles["personal"].paths == ["/workspace/pulsar"]


def test_config_with_no_paths_anywhere_forces_explicit_profile() -> None:
    config = ProfileConfig(
        profiles={"foundation": Profile(api_key="key")},
    )
    with pytest.raises(typer.Exit):
        resolve_profile_name(config, None, Path("/workspace/anything"))
