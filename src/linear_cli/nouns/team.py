from __future__ import annotations

from typing import Annotated

import typer

from ..api import build_list_query, emit, fail, graphql, mutate, require_fields
from ..models import LinearModel, NodeList

TEAM_FIELDS = "id key name"
team_app = typer.Typer()


class TeamNode(LinearModel):
    id: str
    key: str
    name: str


class TeamsData(LinearModel):
    teams: NodeList[TeamNode]


def resolve_team_id(key: str) -> str:
    query = build_list_query("teams", TEAM_FIELDS)
    teams = TeamsData.model_validate(graphql(query, {})).teams.nodes
    team = next((team for team in teams if team.key == key), None)
    if team is None:
        available = ", ".join(sorted(team.key for team in teams))
        fail(f"No team with key {key!r}; available keys: {available}")
    return team.id


@team_app.command(name="list")
def team_list() -> None:
    query = build_list_query("teams", TEAM_FIELDS)
    teams = TeamsData.model_validate(graphql(query, {})).teams.nodes
    for team in sorted(teams, key=lambda team: team.key):
        emit({"id": team.id, "key": team.key, "name": team.name})


@team_app.command(name="create")
def team_create(
    name: Annotated[str, typer.Option("--name", help="Team display name")],
    key: Annotated[str, typer.Option("--key", help="Team key, e.g. GOV")],
    description: Annotated[str | None, typer.Option("--description", help="Optional team description")] = None,
) -> None:
    fields: dict[str, object] = {"name": name, "key": key}
    if description is not None:
        fields["description"] = description

    emit(mutate("team", "Create", {"input": fields}))


@team_app.command(name="update")
def team_update(
    team_id: Annotated[str, typer.Option("--id", help="Team id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New team display name")] = None,
    description: Annotated[str | None, typer.Option("--description", help="New team description")] = None,
) -> None:
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description

    require_fields(fields, "Nothing to update; pass --name and/or --description")

    emit(mutate("team", "Update", {"id": team_id, "input": fields}))
