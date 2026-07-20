from __future__ import annotations

from pathlib import Path

import pytest
import typer

from linear_cli.profiles import (
    PathBinding,
    Profile,
    ProfileConfig,
    load_config,
    resolve_path_binding,
    write_config,
)


def _config() -> ProfileConfig:
    return ProfileConfig(
        profiles={
            "foundation": Profile(api_key="key-foundation"),
            "personal": Profile(api_key="key-personal"),
        },
        path_defaults={
            "/workspace/placeframe": PathBinding(profile="foundation", team="PLE"),
            "/workspace/pulsar": PathBinding(profile="personal", team="TYL"),
            "/workspace/governance": PathBinding(profile="foundation", team="GOV"),
            "/workspace/placeframe/deeply/nested": PathBinding(profile="foundation", team="PLE"),
        },
    )


def test_override_wins_and_clears_team() -> None:
    config = _config()
    binding = resolve_path_binding(config, "personal", Path("/workspace/placeframe"))
    assert binding.profile == "personal"
    assert binding.team is None


def test_override_unknown_profile_errors() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_path_binding(config, "nonexistent", Path("/workspace/placeframe"))


def test_exact_path_match_returns_full_binding() -> None:
    config = _config()
    binding = resolve_path_binding(config, None, Path("/workspace/pulsar"))
    assert binding.profile == "personal"
    assert binding.team == "TYL"


def test_longest_prefix_wins() -> None:
    config = _config()
    binding = resolve_path_binding(config, None, Path("/workspace/placeframe/deeply/nested"))
    assert binding.profile == "foundation"
    assert binding.team == "PLE"


def test_prefix_below_registered_path_inherits_parent_binding() -> None:
    config = _config()
    binding = resolve_path_binding(config, None, Path("/workspace/pulsar/scripts/src"))
    assert binding.profile == "personal"
    assert binding.team == "TYL"


def test_governance_path_uses_foundation_credentials_with_gov_team() -> None:
    config = _config()
    binding = resolve_path_binding(config, None, Path("/workspace/governance"))
    assert binding.profile == "foundation"
    assert binding.team == "GOV"


def test_sibling_directory_does_not_match() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_path_binding(config, None, Path("/workspace/placeframe-foo"))


def test_no_match_errors() -> None:
    config = _config()
    with pytest.raises(typer.Exit):
        resolve_path_binding(config, None, Path("/var/empty"))


def test_load_config_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") is None


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "linear-cli" / "config.json"
    original = _config()
    write_config(original, path)
    loaded = load_config(path)
    assert loaded is not None
    assert loaded.profiles["foundation"].api_key == "key-foundation"
    assert loaded.path_defaults["/workspace/pulsar"].profile == "personal"
    assert loaded.path_defaults["/workspace/pulsar"].team == "TYL"
    assert loaded.path_defaults["/workspace/governance"].team == "GOV"


def test_config_with_empty_path_defaults_forces_explicit_profile() -> None:
    config = ProfileConfig(
        profiles={"foundation": Profile(api_key="key")},
        path_defaults={},
    )
    with pytest.raises(typer.Exit):
        resolve_path_binding(config, None, Path("/workspace/anything"))


def test_path_binding_allows_null_team_for_team_optional_verbs() -> None:
    config = ProfileConfig(
        profiles={"foundation": Profile(api_key="key")},
        path_defaults={"/workspace/placeframe": PathBinding(profile="foundation", team=None)},
    )
    binding = resolve_path_binding(config, None, Path("/workspace/placeframe"))
    assert binding.team is None
