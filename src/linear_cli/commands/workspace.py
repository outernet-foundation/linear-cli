from __future__ import annotations

import json
from datetime import UTC, datetime

import typer

from ..client import graphql, paginate, resolved_profile_name, snapshot_issue_dict
from ..models import IssueSnapshotData, LabelsData, ProjectsData, TeamsData, WorkflowStatesData
from ..operations import (
    ISSUE_SNAPSHOT_FIELDS,
    LABEL_FIELDS,
    PROJECT_FIELDS,
    TEAM_FIELDS,
    WORKFLOW_STATE_FIELDS,
    build_list_query,
)
from ..snapshot import identifier_sort_key

workspace_app = typer.Typer()


@workspace_app.command(name="snapshot")
def workspace_snapshot() -> None:
    captured_at = datetime.now(UTC).isoformat()
    profile_name = resolved_profile_name()

    teams_query = build_list_query("teams", TEAM_FIELDS)
    teams = TeamsData.model_validate(graphql(teams_query, {})).teams.nodes

    projects_query = build_list_query("projects", PROJECT_FIELDS, paginated=True)
    projects = list(paginate(projects_query, {}, ProjectsData, lambda data: data.projects))

    labels_query = build_list_query("issueLabels", LABEL_FIELDS)
    labels = LabelsData.model_validate(graphql(labels_query, {})).issue_labels.nodes

    states_query = build_list_query("workflowStates", WORKFLOW_STATE_FIELDS, filter_type="WorkflowStateFilter")
    workflow_states = WorkflowStatesData.model_validate(graphql(states_query, {"filter": {}})).workflow_states.nodes

    issues_query = build_list_query(
        "issues", ISSUE_SNAPSHOT_FIELDS, filter_type="IssueFilter", paginated=True, archive_aware=True
    )
    issues = list(paginate(issues_query, {"includeArchived": True}, IssueSnapshotData, lambda data: data.issues))

    record = {
        "captured_at": captured_at,
        "linear_profile": profile_name,
        "teams": [{"id": team.id, "key": team.key, "name": team.name} for team in teams],
        "workflow_states": [{"id": state.id, "name": state.name, "type": state.type} for state in workflow_states],
        "projects": [
            {"id": project.id, "name": project.name, "state": project.state, "url": project.url} for project in projects
        ],
        "labels": [
            {
                "id": label.id,
                "name": label.name,
                "color": label.color,
                "is_group": label.is_group,
                "parent_id": label.parent.id if label.parent else None,
            }
            for label in labels
        ],
        "issues": [
            snapshot_issue_dict(node) for node in sorted(issues, key=lambda node: identifier_sort_key(node.identifier))
        ],
    }
    typer.echo(json.dumps(record, indent=2))
