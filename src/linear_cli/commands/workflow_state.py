from __future__ import annotations

from typing import Annotated

import typer

from ..client import emit, graphql, mutate, resolve_team_id, team_filter
from ..models import WorkflowStatesData
from ..operations import WORKFLOW_STATE_FIELDS, build_list_query

workflow_state_app = typer.Typer()


@workflow_state_app.command(name="list")
def workflow_state_list(
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. GOV")],
) -> None:
    query = build_list_query("workflowStates", WORKFLOW_STATE_FIELDS, filter_type="WorkflowStateFilter")
    states = WorkflowStatesData.model_validate(graphql(query, {"filter": team_filter(team)})).workflow_states.nodes
    for state in states:
        emit({"id": state.id, "name": state.name, "type": state.type})


@workflow_state_app.command(name="create")
def workflow_state_create(
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. GOV")],
    name: Annotated[str, typer.Option("--name", help="State display name")],
    state_type: Annotated[
        str,
        typer.Option("--type", help="Linear state type: backlog, unstarted, started, completed, canceled"),
    ],
    color: Annotated[str, typer.Option("--color", help="Hex color, e.g. #eb5757")],
    description: Annotated[str | None, typer.Option("--description", help="Optional state description")] = None,
    position: Annotated[float | None, typer.Option("--position", help="Position (ordering)")] = None,
) -> None:
    fields: dict[str, object] = {
        "teamId": resolve_team_id(team),
        "name": name,
        "type": state_type,
        "color": color,
    }
    if description is not None:
        fields["description"] = description
    if position is not None:
        fields["position"] = position

    emit(mutate("workflowState", "Create", {"input": fields}))


@workflow_state_app.command(name="archive")
def workflow_state_archive(
    state_id: Annotated[str, typer.Option("--id", help="Workflow state id to archive")],
) -> None:
    emit(mutate("workflowState", "Archive", {"id": state_id}))
