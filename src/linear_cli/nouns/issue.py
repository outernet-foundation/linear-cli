from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import typer
from pydantic import Field

from ..api import (
    build_list_query,
    emit,
    fail,
    graphql,
    mutate,
    paginate,
    read_stdin,
    require_fields,
    resolved_profile_name,
    team_filter,
)
from ..models import Connection, LinearModel, NodeList
from ..validation import validate_body, validate_title
from .label import resolve_label_ids
from .team import TeamNode, resolve_team_id
from .workflow_state import WORKFLOW_STATE_FIELDS, WorkflowStatesData

ISSUE_LIST_FIELDS = (
    "id identifier title description url createdAt archivedAt "
    "state { name type } labels { nodes { name } } project { id name }"
)
ISSUE_SNAPSHOT_FIELDS = (
    "id identifier title description priority archivedAt "
    "state { name type } team { id key name } project { id name } "
    "labels { nodes { name } } comments { nodes { body createdAt user { name } } }"
)
_DETAIL_FIELDS = (
    "identifier title description url createdAt archivedAt "
    "state { name type } team { id key name } project { id name } "
    "labels { nodes { id } } attachments { nodes { id title subtitle url metadata } }"
)

issue_app = typer.Typer()


class IssueStateNode(LinearModel):
    name: str
    type: str


class IssueLabelName(LinearModel):
    name: str


class ProjectRef(LinearModel):
    id: str
    name: str


class CommentUserNode(LinearModel):
    name: str


class AttachmentNode(LinearModel):
    id: str
    title: str | None = None
    subtitle: str | None = None
    url: str
    metadata: dict[str, object] | None = None


class LabelIdRef(LinearModel):
    id: str


class IssueListNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    labels: NodeList[IssueLabelName]
    project: ProjectRef | None = None


class IssuesData(LinearModel):
    issues: Connection[IssueListNode]


class IssueSnapshotCommentNode(LinearModel):
    body: str | None = None
    created_at: str = Field(alias="createdAt")
    user: CommentUserNode | None = None


class IssueSnapshotNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int = 0
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: NodeList[IssueLabelName]
    comments: NodeList[IssueSnapshotCommentNode]


class IssueSnapshotData(LinearModel):
    issues: Connection[IssueSnapshotNode]


class IssueDetailNode(LinearModel):
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: NodeList[LabelIdRef] = Field(default_factory=lambda: NodeList(nodes=[]))
    attachments: NodeList[AttachmentNode]


class IssueDetailData(LinearModel):
    issue: IssueDetailNode


class IssueSnapshotByIdData(LinearModel):
    issue: IssueSnapshotNode


def snapshot_issue_dict(node: IssueSnapshotNode) -> dict[str, object]:
    return {
        "id": node.id,
        "identifier": node.identifier,
        "title": node.title,
        "description": node.description,
        "state": node.state.name,
        "state_type": node.state.type,
        "team": node.team.key if node.team else None,
        "project": node.project.name if node.project else None,
        "priority": node.priority,
        "archived_at": node.archived_at,
        "labels": [label.name for label in node.labels.nodes],
        "comments": [
            {
                "body": comment.body,
                "user": comment.user.name if comment.user else None,
                "created_at": comment.created_at,
            }
            for comment in node.comments.nodes
        ],
    }


def _node_query(fields: str) -> str:
    return f"query($id: String!) {{ issue(id: $id) {{ {fields} }} }}"


def _label_snapshot_filter(label: str) -> dict[str, object]:
    return {"labels": {"name": {"eq": label}}}


def identifier_sort_key(identifier: str) -> tuple[str, int]:
    team, _, number = identifier.partition("-")
    if number.isdigit():
        return (team, int(number))
    return (identifier, 0)


def _enforce_conventions(title: str | None, body: str | None) -> None:
    violations: list[str] = []
    if title is not None:
        violations.extend(validate_title(title))
    if body is not None:
        violations.extend(validate_body(body))
    if not violations:
        return

    for violation in violations:
        typer.echo(f"convention violation: {violation}", err=True)

    fail("Refusing to write: fix the title/body to match the AGENTS.md conventions.")


def _resolve_state_id(state: str, team: str) -> str:
    query = build_list_query("workflowStates", WORKFLOW_STATE_FIELDS, filter_type="WorkflowStateFilter")
    states = WorkflowStatesData.model_validate(graphql(query, {"filter": team_filter(team)})).workflow_states.nodes
    matches = [candidate for candidate in states if candidate.name.casefold() == state.casefold()]
    if len(matches) != 1:
        available = ", ".join(sorted(candidate.name for candidate in states))
        fail(f"No unique state {state!r} in team {team!r}; available: {available}")
    return matches[0].id


@issue_app.command(name="list")
def issue_list(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Label name to filter by")] = None,
    include_archived: Annotated[
        bool, typer.Option("--include-archived", help="Include archived issues in results")
    ] = False,
) -> None:
    filter_dict: dict[str, object] = team_filter(team)
    if label is not None:
        filter_dict["labels"] = {"name": {"eq": label}}
    variables: dict[str, object] = {"filter": filter_dict}
    if include_archived:
        variables["includeArchived"] = True
    query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True, archive_aware=True)
    for issue in paginate(query, variables, IssuesData, lambda data: data.issues):
        emit({
            "id": issue.id,
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state.name,
            "state_type": issue.state.type,
            "labels": [label.name for label in issue.labels.nodes],
            "project": issue.project.name if issue.project else None,
            "created_at": issue.created_at,
            "archived_at": issue.archived_at,
            "url": issue.url,
        })


@issue_app.command(name="get")
def issue_get(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier, e.g. GOV-21")],
) -> None:
    query = _node_query(_DETAIL_FIELDS)
    issue = IssueDetailData.model_validate(graphql(query, {"id": issue_id})).issue
    emit({
        "identifier": issue.identifier,
        "title": issue.title,
        "state": issue.state.name,
        "team": issue.team.key if issue.team else None,
        "project": issue.project.name if issue.project else None,
        "created_at": issue.created_at,
        "archived_at": issue.archived_at,
        "url": issue.url,
        "description": issue.description,
        "attachments": [
            {
                "title": attachment.title,
                "subtitle": attachment.subtitle,
                "url": attachment.url,
                "metadata": attachment.metadata,
            }
            for attachment in issue.attachments.nodes
        ],
    })


@issue_app.command(
    name="create",
    help="Reads the issue description (markdown body) from stdin. Required — must match the Why/Done-when/Links template.",
)
def issue_create(
    title: Annotated[str, typer.Option("--title", help="Issue title")],
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. PLE")],
    project: Annotated[str | None, typer.Option("--project", help="Project id to file the issue under")] = None,
    label: Annotated[list[str] | None, typer.Option("--label", help="Label name or id to attach (repeatable)")] = None,
    priority: Annotated[int | None, typer.Option("--priority", help="Issue priority: 0=none, 1=urgent, 2=high")] = None,
) -> None:
    description = read_stdin()
    _enforce_conventions(title, description)
    fields: dict[str, object] = {"teamId": resolve_team_id(team), "title": title}
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label:
        fields["labelIds"] = resolve_label_ids(label)
    if priority is not None:
        fields["priority"] = priority

    emit(mutate("issue", "Create", {"input": fields}))


@issue_app.command(
    name="update",
    help="Reads the new issue description (markdown body) from stdin if any is piped in. Piped bodies must match the Why/Done-when/Links template.",
)
def issue_update(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier, e.g. GOV-21")],
    title: Annotated[str | None, typer.Option("--title", help="New issue title")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Project id to move the issue under")] = None,
    label: Annotated[
        list[str] | None, typer.Option("--label", help="Replaces the label set by name or id (repeatable)")
    ] = None,
    add_label: Annotated[
        list[str] | None, typer.Option("--add-label", help="Label name or id to add to the existing set (repeatable)")
    ] = None,
    remove_label: Annotated[
        list[str] | None,
        typer.Option("--remove-label", help="Label name or id to remove from the existing set (repeatable)"),
    ] = None,
    state: Annotated[str | None, typer.Option("--state", help="Workflow state name to move the issue to")] = None,
    team: Annotated[
        str | None,
        typer.Option("--team", help="Team key to move the issue to (also used for state resolution), e.g. GOV"),
    ] = None,
    priority: Annotated[int | None, typer.Option("--priority", help="Issue priority: 0=none, 1=urgent, 2=high")] = None,
) -> None:
    description = read_stdin()
    _enforce_conventions(title, description if description.strip() else None)
    fields: dict[str, object] = {}
    if title is not None:
        fields["title"] = title
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label is not None and add_label is None and remove_label is None:
        fields["labelIds"] = resolve_label_ids(label)
    elif add_label is not None or remove_label is not None:
        detail_query = _node_query(_DETAIL_FIELDS)
        current = IssueDetailData.model_validate(graphql(detail_query, {"id": issue_id})).issue
        current_ids = {ref.id for ref in current.labels.nodes}
        add_ids: set[str] = set(resolve_label_ids(add_label)) if add_label else set()
        remove_ids: set[str] = set(resolve_label_ids(remove_label)) if remove_label else set()
        fields["labelIds"] = list(current_ids | add_ids - remove_ids)
    if team is not None:
        fields["teamId"] = resolve_team_id(team)
    if state is not None:
        if team is None:
            fail("--state requires --team to specify which team's workflow to resolve against")
        fields["stateId"] = _resolve_state_id(state, team)

    if priority is not None:
        fields["priority"] = priority

    require_fields(
        fields,
        "Nothing to update; pass --team, --title, --label, --add-label, --remove-label, --state, --priority, or a body on stdin",
    )

    emit(mutate("issue", "Update", {"id": issue_id, "input": fields}))


@issue_app.command(name="unarchive")
def issue_unarchive(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier to unarchive")],
) -> None:
    emit(mutate("issue", "Unarchive", {"id": issue_id}))


@issue_app.command(name="snapshot")
def issue_snapshot(
    issue: Annotated[
        list[str] | None,
        typer.Option("--issue", help="Issue identifier to include (repeatable), e.g. GOV-5"),
    ] = None,
    label: Annotated[
        str | None, typer.Option("--label", help="Label name; snapshot every issue carrying this label")
    ] = None,
) -> None:
    if issue is not None and label is not None:
        fail("Pass --issue or --label, not both.")

    if issue is not None:
        node_query = _node_query(ISSUE_SNAPSHOT_FIELDS)
        nodes = [
            IssueSnapshotByIdData.model_validate(graphql(node_query, {"id": identifier})).issue for identifier in issue
        ]
    elif label is not None:
        list_query = build_list_query("issues", ISSUE_SNAPSHOT_FIELDS, filter_type="IssueFilter", paginated=True)
        nodes = list(
            paginate(list_query, {"filter": _label_snapshot_filter(label)}, IssueSnapshotData, lambda data: data.issues)
        )
    else:
        fail("Pass --issue (repeatable) or --label to select issues to snapshot.")
    nodes.sort(key=lambda node: identifier_sort_key(node.identifier))

    typer.echo(
        json.dumps(
            {
                "captured_at": datetime.now(UTC).isoformat(),
                "linear_profile": resolved_profile_name(),
                "issues": [snapshot_issue_dict(node) for node in nodes],
            },
            indent=2,
        )
    )
