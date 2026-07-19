from __future__ import annotations

from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path.home() / ".config" / "linear-cli" / "config.json"


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Profile(_Model):
    api_key: str
    team_key: str | None = None


class ProfileConfig(_Model):
    profiles: dict[str, Profile]
    path_defaults: dict[str, str] = Field(default_factory=dict)


def load_config(path: Path = CONFIG_PATH) -> ProfileConfig | None:
    if not path.is_file():
        return None
    return ProfileConfig.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_profile_name(config: ProfileConfig, override: str | None, cwd: Path) -> str:
    if override is not None:
        if override not in config.profiles:
            available = ", ".join(sorted(config.profiles))
            typer.echo(f"No profile named {override!r}; available profiles: {available}", err=True)
            raise typer.Exit(1)
        return override

    cwd_str = str(cwd.resolve())
    matching = [
        prefix for prefix in config.path_defaults if cwd_str == prefix or cwd_str.startswith(prefix.rstrip("/") + "/")
    ]
    if not matching:
        typer.echo(
            f"No profile resolved for {cwd_str}; pass --profile <name> or add a path_defaults entry in {CONFIG_PATH}",
            err=True,
        )
        raise typer.Exit(1)

    return config.path_defaults[max(matching, key=len)]


def require_team(profile: Profile, override: str | None) -> str:
    team = override if override is not None else profile.team_key
    if team is None:
        typer.echo(
            "No team resolved; pass --team or set team_key on the profile in "
            f"{CONFIG_PATH}. Linear requires a team for this operation.",
            err=True,
        )
        raise typer.Exit(1)
    return team


def write_config(config: ProfileConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
