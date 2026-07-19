from __future__ import annotations

from pathlib import Path

import pytest
import typer

from linear_cli.profiles import (
    Profile,
    ProfileConfig,
    load_config,
    require_team,
    resolve_profile_name,
    write_config,
)


def _config() -> ProfileConfig:
    return ProfileConfig(
        profiles={
            "foundation": Profile(api_key="key-foundation", team_key="PLE", labels={"repo": ["placeframe"]}),
            "personal": Profile(api_key="key-personal", team_key=None),
        },
        path_defaults={
            "/workspace/placeframe": "foundation",
            "/workspace/pulsar": "personal",
            "/workspace/placeframe/deeply/nested": "foundation",
        },
    )


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


def test_prefix_below_registered_path_matches_parent() -> None:
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


def test_require_team_uses_override() -> None:
    profile = Profile(api_key="key", team_key="PLE")
    assert require_team(profile, "OTHER") == "OTHER"


def test_require_team_uses_profile_default() -> None:
    profile = Profile(api_key="key", team_key="PLE")
    assert require_team(profile, None) == "PLE"


def test_require_team_errors_when_neither_given() -> None:
    profile = Profile(api_key="key", team_key=None)
    with pytest.raises(typer.Exit):
        require_team(profile, None)


def test_load_config_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") is None


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "linear-cli" / "config.json"
    original = _config()
    write_config(original, path)
    loaded = load_config(path)
    assert loaded is not None
    assert loaded.profiles["foundation"].api_key == "key-foundation"
    assert loaded.profiles["foundation"].team_key == "PLE"
    assert loaded.profiles["personal"].team_key is None
    assert loaded.path_defaults["/workspace/pulsar"] == "personal"


def test_profile_with_no_team_key_defaults_to_none() -> None:
    profile = Profile(api_key="key")
    assert profile.team_key is None
    assert profile.labels == {}


def test_config_with_empty_path_defaults_forces_explicit_profile() -> None:
    config = ProfileConfig(
        profiles={"foundation": Profile(api_key="key", team_key="PLE")},
        path_defaults={},
    )
    with pytest.raises(typer.Exit):
        resolve_profile_name(config, None, Path("/workspace/anything"))
