from __future__ import annotations

from typing import Annotated

import typer

from ..api import build_list_query, emit, fail, mutate, paginate, read_stdin, require_fields
from ..models import Connection, LinearModel
from .team import resolve_team_id

PROJECT_FIELDS = "id name url state"
project_app = typer.Typer()


class ProjectListNode(LinearModel):
    id: str
    name: str
    url: str
    state: str


class ProjectsData(LinearModel):
    projects: Connection[ProjectListNode]


@project_app.command(name="list")
def project_list() -> None:
    query = build_list_query("projects", PROJECT_FIELDS, paginated=True)
    for project in paginate(query, {}, ProjectsData, lambda data: data.projects):
        emit({"id": project.id, "name": project.name, "state": project.state, "url": project.url})


@project_app.command(name="create", help="Reads the project content (markdown body) from stdin.")
def project_create(
    name: Annotated[str, typer.Option("--name", help="Project name")],
    team: Annotated[str, typer.Option("--team", help="Team key the project belongs to, e.g. PLE")],
    summary: Annotated[str, typer.Option("--summary", help="One-line project description")] = "",
) -> None:
    content = read_stdin()
    fields: dict[str, object] = {"name": name, "teamIds": [resolve_team_id(team)]}
    if summary:
        fields["description"] = summary
    if content.strip():
        fields["content"] = content

    emit(mutate("project", "Create", {"input": fields}))


@project_app.command(name="update", help="Reads the new project content (markdown body) from stdin if any is piped in.")
def project_update(
    project_id: Annotated[str, typer.Option("--id", help="Project id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New project name")] = None,
    summary: Annotated[str | None, typer.Option("--summary", help="New one-line description")] = None,
    team: Annotated[
        list[str] | None,
        typer.Option("--team", help="Team key for the project (repeatable); replaces the project's team set"),
    ] = None,
) -> None:
    content = read_stdin()
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if summary is not None:
        fields["description"] = summary
    if content.strip():
        fields["content"] = content
    if team is not None:
        if len(team) == 0:
            fail("--team requires at least one team key")
        fields["teamIds"] = [resolve_team_id(key) for key in team]

    require_fields(fields, "Nothing to update; pass --team, --name, --summary, or a body on stdin")

    emit(mutate("project", "Update", {"id": project_id, "input": fields}))


@project_app.command(name="delete")
def project_delete(
    project_id: Annotated[str, typer.Option("--id", help="Project id to delete")],
) -> None:
    emit(mutate("project", "Delete", {"id": project_id}))
