from __future__ import annotations

from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict, Field, RootModel

CONFIG_PATH = Path.home() / ".config" / "linear-cli" / "config.json"


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Profile(_Model):
    api_key: str
    paths: list[str] = Field(default_factory=list)


class ProfileConfig(RootModel[dict[str, Profile]]):
    root: dict[str, Profile] = Field(default_factory=dict)


def load_config(path: Path = CONFIG_PATH) -> ProfileConfig | None:
    if not path.is_file():
        return None
    return ProfileConfig.model_validate_json(path.read_text(encoding="utf-8"))


def flatten_paths(config: ProfileConfig) -> dict[str, str]:
    result: dict[str, str] = {}
    for profile_name, profile in config.root.items():
        for path in profile.paths:
            result[path] = profile_name
    return result


def resolve_profile_name(
    config: ProfileConfig,
    profile_override: str | None,
    cwd: Path,
) -> str:
    if profile_override is not None:
        if profile_override not in config.root:
            available = ", ".join(sorted(config.root))
            typer.echo(f"No profile named {profile_override!r}; available profiles: {available}", err=True)
            raise typer.Exit(1)
        return profile_override

    path_map = flatten_paths(config)
    cwd_str = str(cwd.resolve())
    matching = [prefix for prefix in path_map if cwd_str == prefix or cwd_str.startswith(prefix.rstrip("/") + "/")]
    if not matching:
        typer.echo(
            f"No profile resolved for {cwd_str}; pass --profile <name> or add the path to a profile's paths list in {CONFIG_PATH}",
            err=True,
        )
        raise typer.Exit(1)

    return path_map[max(matching, key=len)]


def write_config(config: ProfileConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
