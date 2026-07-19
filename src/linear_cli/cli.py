from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated

import httpx
import typer
from pydantic import BaseModel, ConfigDict, Field

from .profiles import (
    CONFIG_PATH,
    Profile,
    load_config,
    require_team,
    resolve_profile_name,
)
from .snapshot import identifier_sort_key, label_snapshot_filter
from .validation import orphan_design_docs, validate_body, validate_title

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
OPERATIONS_DOCUMENT = "linear_operations.graphql"


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _CliState:
    profile_override: str | None = None


class PageInfo(_Model):
    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class _Connection[NodeT](_Model):
    page_info: PageInfo = Field(alias="pageInfo")
    nodes: list[NodeT]


class _NodeList[NodeT](_Model):
    nodes: list[NodeT]


class TeamNode(_Model):
    id: str
    key: str
    name: str


class IssueStateNode(_Model):
    name: str
    type: str


class IssueLabelName(_Model):
    name: str


class ProjectRef(_Model):
    id: str
    name: str


class IssueListNode(_Model):
    id: str
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    state: IssueStateNode
    labels: _NodeList[IssueLabelName]
    project: ProjectRef | None = None


class AttachmentNode(_Model):
    id: str
    title: str | None = None
    subtitle: str | None = None
    url: str
    metadata: dict[str, object] | None = None


class IssueDetailNode(_Model):
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    state: IssueStateNode
    project: ProjectRef | None = None
    attachments: _NodeList[AttachmentNode]


class ProjectListNode(_Model):
    id: str
    name: str
    url: str
    state: str


class RelatedIssueNode(_Model):
    identifier: str


class IssueRelationNode(_Model):
    type: str
    related_issue: RelatedIssueNode | None = Field(default=None, alias="relatedIssue")


class IssueRelationsNode(_Model):
    identifier: str
    relations: _NodeList[IssueRelationNode]


class CommentUserNode(_Model):
    name: str


class IssueSnapshotCommentNode(_Model):
    body: str | None = None
    created_at: str = Field(alias="createdAt")
    user: CommentUserNode | None = None


class IssueSnapshotNode(_Model):
    id: str
    identifier: str
    title: str
    description: str | None = None
    state: IssueStateNode
    labels: _NodeList[IssueLabelName]
    comments: _NodeList[IssueSnapshotCommentNode]


class WorkflowStateNode(_Model):
    id: str
    name: str
    type: str


class LabelParent(_Model):
    id: str


class LabelNode(_Model):
    id: str
    name: str
    color: str | None = None
    is_group: bool = Field(default=False, alias="isGroup")
    parent: LabelParent | None = None


class CreatedLabel(_Model):
    id: str
    name: str


class CreatedProject(_Model):
    id: str
    url: str


class CreatedTeam(_Model):
    id: str
    key: str
    name: str


class CreatedWorkflowState(_Model):
    id: str
    name: str
    type: str


class CreatedIssue(_Model):
    id: str
    identifier: str
    url: str


class CommentNode(_Model):
    id: str
    url: str


class IssueLabelMutationPayload(_Model):
    success: bool
    issue_label: CreatedLabel | None = Field(default=None, alias="issueLabel")


class IssueLabelDeletePayload(_Model):
    success: bool


class ProjectMutationPayload(_Model):
    success: bool
    project: CreatedProject | None = None


class TeamMutationPayload(_Model):
    success: bool
    team: CreatedTeam | None = None


class WorkflowStateMutationPayload(_Model):
    success: bool
    workflow_state: CreatedWorkflowState | None = Field(default=None, alias="workflowState")


class ProjectDeletePayload(_Model):
    success: bool


class IssueMutationPayload(_Model):
    success: bool
    issue: CreatedIssue | None = None


class IssueRelationCreatePayload(_Model):
    success: bool


class CommentCreatePayload(_Model):
    success: bool
    comment: CommentNode | None = None


class CommentDeletePayload(_Model):
    success: bool


class TeamsData(_Model):
    teams: _NodeList[TeamNode]


class IssuesData(_Model):
    issues: _Connection[IssueListNode]


class IssueDetailData(_Model):
    issue: IssueDetailNode


class ProjectsData(_Model):
    projects: _Connection[ProjectListNode]


class IssueRelationsData(_Model):
    issues: _Connection[IssueRelationsNode]


class IssueSnapshotData(_Model):
    issues: _Connection[IssueSnapshotNode]


class IssueSnapshotByIdData(_Model):
    issue: IssueSnapshotNode


class WorkflowStatesData(_Model):
    workflow_states: _NodeList[WorkflowStateNode] = Field(alias="workflowStates")


class LabelsData(_Model):
    issue_labels: _NodeList[LabelNode] = Field(alias="issueLabels")


class IssueLabelCreateData(_Model):
    issue_label_create: IssueLabelMutationPayload = Field(alias="issueLabelCreate")


class IssueLabelUpdateData(_Model):
    issue_label_update: IssueLabelMutationPayload = Field(alias="issueLabelUpdate")


class IssueLabelDeleteData(_Model):
    issue_label_delete: IssueLabelDeletePayload = Field(alias="issueLabelDelete")


class ProjectCreateData(_Model):
    project_create: ProjectMutationPayload = Field(alias="projectCreate")


class TeamCreateData(_Model):
    team_create: TeamMutationPayload = Field(alias="teamCreate")


class WorkflowStateCreateData(_Model):
    workflow_state_create: WorkflowStateMutationPayload = Field(alias="workflowStateCreate")


class WorkflowStateArchivePayload(_Model):
    success: bool


class WorkflowStateArchiveData(_Model):
    workflow_state_archive: WorkflowStateArchivePayload = Field(alias="workflowStateArchive")


class ProjectUpdateData(_Model):
    project_update: ProjectMutationPayload = Field(alias="projectUpdate")


class ProjectDeleteData(_Model):
    project_delete: ProjectDeletePayload = Field(alias="projectDelete")


class IssueCreateData(_Model):
    issue_create: IssueMutationPayload = Field(alias="issueCreate")


class IssueUpdateData(_Model):
    issue_update: IssueMutationPayload = Field(alias="issueUpdate")


class IssueRelationCreateData(_Model):
    issue_relation_create: IssueRelationCreatePayload = Field(alias="issueRelationCreate")


class CommentCreateData(_Model):
    comment_create: CommentCreatePayload = Field(alias="commentCreate")


class CommentDeleteData(_Model):
    comment_delete: CommentDeletePayload = Field(alias="commentDelete")


app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.callback()
def root_callback(
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Profile name from ~/.config/linear-cli/config.json"),
    ] = None,
) -> None:
    _CliState.profile_override = profile


@app.command(name="list-issues")
def list_issues(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
) -> None:
    for issue in _paginate(
        "Issues", {"filter": _team_filter(_resolved_team(team))}, IssuesData, lambda data: data.issues
    ):
        _emit({
            "id": issue.id,
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state.name,
            "state_type": issue.state.type,
            "labels": [label.name for label in issue.labels.nodes],
            "project": issue.project.name if issue.project else None,
            "created_at": issue.created_at,
            "url": issue.url,
        })


@app.command(name="get-issue")
def get_issue(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id to fetch")],
) -> None:
    issue = graphql("Issue", {"id": issue_id}, IssueDetailData).issue
    _emit({
        "identifier": issue.identifier,
        "title": issue.title,
        "state": issue.state.name,
        "project": issue.project.name if issue.project else None,
        "created_at": issue.created_at,
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


@app.command(name="list-relations")
def list_relations(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
) -> None:
    for issue in _paginate(
        "IssueRelations", {"filter": _team_filter(_resolved_team(team))}, IssueRelationsData, lambda data: data.issues
    ):
        for relation in issue.relations.nodes:
            if relation.related_issue is None:
                continue

            _emit({"source": issue.identifier, "target": relation.related_issue.identifier, "type": relation.type})


@app.command(name="list-projects")
def list_projects() -> None:
    for project in _paginate("Projects", {}, ProjectsData, lambda data: data.projects):
        _emit({"id": project.id, "name": project.name, "state": project.state, "url": project.url})


@app.command(name="list-teams")
def list_teams() -> None:
    teams = graphql("Teams", {}, TeamsData).teams.nodes
    for team in sorted(teams, key=lambda team: team.key):
        _emit({"id": team.id, "key": team.key, "name": team.name})


@app.command(name="list-workflow-states")
def list_workflow_states(
    team: Annotated[str | None, typer.Option("--team", help="Team key, e.g. PLE")] = None,
) -> None:
    resolved_team = require_team(_resolved_profile(), team)
    states = graphql(
        "WorkflowStates", {"filter": _team_filter(resolved_team)}, WorkflowStatesData
    ).workflow_states.nodes
    for state in states:
        _emit({"id": state.id, "name": state.name, "type": state.type})


@app.command(name="create-team")
def create_team(
    name: Annotated[str, typer.Option("--name", help="Team display name")],
    key: Annotated[str, typer.Option("--key", help="Team key, e.g. GOV")],
    description: Annotated[str | None, typer.Option("--description", help="Optional team description")] = None,
) -> None:
    fields: dict[str, object] = {"name": name, "key": key}
    if description is not None:
        fields["description"] = description

    payload = graphql("CreateTeam", {"input": fields}, TeamCreateData).team_create
    team = _require(payload.success, payload.team, f"Failed to create team {name!r}")
    _emit({"id": team.id, "key": team.key, "name": team.name})


@app.command(name="create-workflow-state")
def create_workflow_state(
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
    resolved_team = require_team(_resolved_profile(), team)
    fields: dict[str, object] = {
        "teamId": _resolve_team_id(resolved_team),
        "name": name,
        "type": state_type,
        "color": color,
    }
    if description is not None:
        fields["description"] = description
    if position is not None:
        fields["position"] = position

    payload = graphql("CreateWorkflowState", {"input": fields}, WorkflowStateCreateData).workflow_state_create
    state = _require(payload.success, payload.workflow_state, f"Failed to create workflow state {name!r}")
    _emit({"id": state.id, "name": state.name, "type": state.type})


@app.command(name="archive-workflow-state")
def archive_workflow_state(
    state_id: Annotated[str, typer.Option("--id", help="Workflow state id to archive")],
) -> None:
    payload = graphql("ArchiveWorkflowState", {"id": state_id}, WorkflowStateArchiveData).workflow_state_archive
    _require_ok(payload.success, f"Failed to archive workflow state {state_id!r}")
    _emit({"id": state_id, "archived": True})


@app.command(name="snapshot")
def snapshot(
    issue: Annotated[
        list[str] | None,
        typer.Option("--issue", help="Issue identifier to include (repeatable), e.g. PLE-352"),
    ] = None,
    label: Annotated[
        str | None, typer.Option("--label", help="Label name; snapshot every issue carrying this label")
    ] = None,
) -> None:
    if issue is None and label is None:
        typer.echo("Pass --issue (repeatable) or --label to select issues to snapshot.", err=True)
        raise typer.Exit(1)
    if issue is not None and label is not None:
        typer.echo("Pass --issue or --label, not both.", err=True)
        raise typer.Exit(1)

    nodes = _snapshot_nodes(issue, label)
    nodes.sort(key=lambda node: identifier_sort_key(node.identifier))
    record = _snapshot_record(_resolved_profile_name(), nodes, datetime.now(UTC).isoformat())
    typer.echo(json.dumps(record, indent=2))


@app.command(name="lint")
def lint(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
    design_orphans: Annotated[
        bool, typer.Option("--design-orphans", help="Also flag design/ docs that no open ticket links")
    ] = False,
) -> None:
    offenders = 0
    open_bodies: list[str] = []
    for issue in _paginate(
        "Issues", {"filter": _team_filter(_resolved_team(team))}, IssuesData, lambda data: data.issues
    ):
        if issue.state.type in ("completed", "canceled"):
            continue

        open_bodies.append(issue.description or "")
        violations = validate_title(issue.title) + validate_body(issue.description or "")
        if violations:
            offenders += 1
            _emit({"identifier": issue.identifier, "title": issue.title, "violations": violations})

    if design_orphans:
        design_dir = _find_up("design/AGENTS.md").parent
        doc_names = [
            path.name for path in sorted(design_dir.glob("*.md")) if path.name not in ("AGENTS.md", "CLAUDE.md")
        ]
        for name in orphan_design_docs(doc_names, open_bodies):
            offenders += 1
            _emit({"design_orphan": f"design/{name}", "violations": ["no open Linear ticket links this design doc"]})

    if offenders:
        raise typer.Exit(1)


@app.command(name="ensure-label")
def ensure_label(
    name: Annotated[str, typer.Option("--name", help="Leaf label name")],
    parent: Annotated[str | None, typer.Option("--parent", help="Parent label-group name to nest under")] = None,
) -> None:
    labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
    parent_id = _ensure_label_record(labels, parent, None, is_group=True) if parent is not None else None
    leaf_id = _ensure_label_record(labels, name, parent_id, is_group=False)
    _emit({"id": leaf_id})


@app.command(name="list-labels")
def list_labels() -> None:
    labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
    names_by_id = {label.id: label.name for label in labels}
    for label in labels:
        parent_name = names_by_id.get(label.parent.id) if label.parent else None
        _emit({
            "id": label.id,
            "name": label.name,
            "color": label.color,
            "is_group": label.is_group,
            "parent": parent_name,
        })


@app.command(name="update-label")
def update_label(
    label_id: Annotated[str, typer.Option("--id", help="Label id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New label name")] = None,
    parent: Annotated[str | None, typer.Option("--parent", help="Parent group name to reparent under")] = None,
    color: Annotated[str | None, typer.Option("--color", help="New label color as a hex string, e.g. #eb5757")] = None,
) -> None:
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if color is not None:
        fields["color"] = color
    if parent is not None:
        labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
        groups = [node for node in labels if node.is_group and node.name == parent]
        if len(groups) != 1:
            typer.echo(f"Expected exactly one group named {parent!r}, found {len(groups)}", err=True)
            raise typer.Exit(1)

        fields["parentId"] = groups[0].id

    _require_fields(fields, "Nothing to update; pass --name, --parent, and/or --color")

    payload = graphql("UpdateLabel", {"id": label_id, "input": fields}, IssueLabelUpdateData).issue_label_update
    label = _require(payload.success, payload.issue_label, f"Failed to update label {label_id!r}")
    _emit({"id": label.id, "name": label.name})


@app.command(name="delete-label")
def delete_label(
    label_id: Annotated[str, typer.Option("--id", help="Label id to delete")],
) -> None:
    payload = graphql("DeleteLabel", {"id": label_id}, IssueLabelDeleteData).issue_label_delete
    _require_ok(payload.success, f"Failed to delete label {label_id!r}")
    _emit({"id": label_id, "deleted": True})


@app.command(name="create-project", help="Reads the project content (markdown body) from stdin.")
def create_project(
    name: Annotated[str, typer.Option("--name", help="Project name")],
    team: Annotated[str | None, typer.Option("--team", help="Team key the project belongs to, e.g. PLE")] = None,
    summary: Annotated[str, typer.Option("--summary", help="One-line project description")] = "",
) -> None:
    content = _read_stdin()
    resolved_team = require_team(_resolved_profile(), team)
    fields: dict[str, object] = {"name": name, "teamIds": [_resolve_team_id(resolved_team)]}
    if summary:
        fields["description"] = summary
    if content.strip():
        fields["content"] = content

    payload = graphql("CreateProject", {"input": fields}, ProjectCreateData).project_create
    project = _require(payload.success, payload.project, f"Failed to create project {name!r}")
    _emit({"id": project.id, "url": project.url})


@app.command(name="update-project", help="Reads the new project content (markdown body) from stdin if any is piped in.")
def update_project(
    project_id: Annotated[str, typer.Option("--id", help="Project id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New project name")] = None,
    summary: Annotated[str | None, typer.Option("--summary", help="New one-line description")] = None,
) -> None:
    content = _read_stdin()
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if summary is not None:
        fields["description"] = summary
    if content.strip():
        fields["content"] = content

    _require_fields(fields, "Nothing to update; pass --name, --summary, or a body on stdin")

    payload = graphql("UpdateProject", {"id": project_id, "input": fields}, ProjectUpdateData).project_update
    project = _require(payload.success, payload.project, f"Failed to update project {project_id!r}")
    _emit({"id": project.id, "url": project.url})


@app.command(name="delete-project")
def delete_project(
    project_id: Annotated[str, typer.Option("--id", help="Project id to delete")],
) -> None:
    payload = graphql("DeleteProject", {"id": project_id}, ProjectDeleteData).project_delete
    _require_ok(payload.success, f"Failed to delete project {project_id!r}")
    _emit({"id": project_id, "deleted": True})


@app.command(
    name="create-issue",
    help="Reads the issue description (markdown body) from stdin. Required — must match the Why/Done-when/Links template.",
)
def create_issue(
    title: Annotated[str, typer.Option("--title", help="Issue title")],
    team: Annotated[str | None, typer.Option("--team", help="Team key, e.g. PLE")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Project id to file the issue under")] = None,
    label: Annotated[list[str] | None, typer.Option("--label", help="Label id to attach (repeatable)")] = None,
) -> None:
    description = _read_stdin()
    _enforce_conventions(title, description)
    resolved_team = require_team(_resolved_profile(), team)
    fields: dict[str, object] = {"teamId": _resolve_team_id(resolved_team), "title": title}
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label:
        fields["labelIds"] = label

    payload = graphql("CreateIssue", {"input": fields}, IssueCreateData).issue_create
    issue = _require(payload.success, payload.issue, f"Failed to create issue {title!r}")
    _emit({"id": issue.id, "identifier": issue.identifier, "url": issue.url})


@app.command(
    name="update-issue",
    help="Reads the new issue description (markdown body) from stdin if any is piped in. Piped bodies must match the Why/Done-when/Links template.",
)
def update_issue(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id to update")],
    title: Annotated[str | None, typer.Option("--title", help="New issue title")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Project id to move the issue under")] = None,
    label: Annotated[list[str] | None, typer.Option("--label", help="Replaces the label set (repeatable)")] = None,
    state: Annotated[str | None, typer.Option("--state", help="Workflow state name to move the issue to")] = None,
    team: Annotated[
        str | None,
        typer.Option("--team", help="Team key to move the issue to (also used for state resolution), e.g. GOV"),
    ] = None,
) -> None:
    description = _read_stdin()
    _enforce_conventions(title, description if description.strip() else None)
    fields: dict[str, object] = {}
    if title is not None:
        fields["title"] = title
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label:
        fields["labelIds"] = label
    if team is not None:
        resolved_team_key = require_team(_resolved_profile(), team)
        fields["teamId"] = _resolve_team_id(resolved_team_key)
    if state is not None:
        resolved_state_team = require_team(_resolved_profile(), team)
        states = graphql(
            "WorkflowStates", {"filter": _team_filter(resolved_state_team)}, WorkflowStatesData
        ).workflow_states.nodes
        matches = [candidate for candidate in states if candidate.name.casefold() == state.casefold()]
        if len(matches) != 1:
            available = ", ".join(sorted(candidate.name for candidate in states))
            typer.echo(f"No unique state {state!r} in team {resolved_state_team!r}; available: {available}", err=True)
            raise typer.Exit(1)

        fields["stateId"] = matches[0].id

    _require_fields(fields, "Nothing to update; pass --team, --title, --label, --state, or a body on stdin")

    payload = graphql("UpdateIssue", {"id": issue_id, "input": fields}, IssueUpdateData).issue_update
    issue = _require(payload.success, payload.issue, f"Failed to update issue {issue_id!r}")
    _emit({"id": issue.id, "identifier": issue.identifier, "url": issue.url})


@app.command()
def link(
    blocker: Annotated[str, typer.Option("--blocker", help="Issue id that does the blocking")],
    blocked: Annotated[str, typer.Option("--blocked", help="Issue id that is blocked")],
) -> None:
    fields: dict[str, object] = {"issueId": blocker, "relatedIssueId": blocked, "type": "blocks"}
    payload = graphql("CreateRelation", {"input": fields}, IssueRelationCreateData).issue_relation_create
    _require_ok(payload.success, "Failed to create blocking relation")
    _emit({"blocker": blocker, "blocked": blocked, "type": "blocks"})


@app.command(help="Reads the comment body (markdown) from stdin. Required.")
def comment(
    issue_id: Annotated[str, typer.Option("--issue", help="Issue id to comment on")],
) -> None:
    body = _read_stdin()
    if not body.strip():
        typer.echo("No comment body on stdin", err=True)
        raise typer.Exit(1)

    payload = graphql("CreateComment", {"input": {"issueId": issue_id, "body": body}}, CommentCreateData).comment_create
    created = _require(payload.success, payload.comment, f"Failed to comment on issue {issue_id!r}")
    _emit({"id": created.id, "url": created.url})


@app.command(name="delete-comment")
def delete_comment(
    comment_id: Annotated[str, typer.Option("--id", help="Comment id to delete")],
) -> None:
    payload = graphql("DeleteComment", {"id": comment_id}, CommentDeleteData).comment_delete
    _require_ok(payload.success, f"Failed to delete comment {comment_id!r}")
    _emit({"id": comment_id, "deleted": True})


def _paginate[T: _Model, NodeT](
    operation: str,
    variables: dict[str, object],
    model: type[T],
    select: Callable[[T], _Connection[NodeT]],
) -> Iterator[NodeT]:
    after: str | None = None
    while True:
        connection = select(graphql(operation, {**variables, "after": after}, model))
        yield from connection.nodes
        if not connection.page_info.has_next_page:
            break

        after = connection.page_info.end_cursor


def _snapshot_nodes(issues: list[str] | None, label: str | None) -> list[IssueSnapshotNode]:
    if issues is not None:
        return [graphql("IssueSnapshotById", {"id": identifier}, IssueSnapshotByIdData).issue for identifier in issues]
    if label is not None:
        return list(
            _paginate(
                "IssueSnapshot", {"filter": label_snapshot_filter(label)}, IssueSnapshotData, lambda data: data.issues
            )
        )
    return []


def _snapshot_record(profile_name: str, nodes: list[IssueSnapshotNode], captured_at: str) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "linear_profile": profile_name,
        "issues": [_snapshot_issue_dict(node) for node in nodes],
    }


def _snapshot_issue_dict(node: IssueSnapshotNode) -> dict[str, object]:
    return {
        "id": node.id,
        "identifier": node.identifier,
        "title": node.title,
        "description": node.description,
        "state": node.state.name,
        "labels": [label.name for label in node.labels.nodes],
        "comments": [_snapshot_comment_dict(comment) for comment in node.comments.nodes],
    }


def _snapshot_comment_dict(comment: IssueSnapshotCommentNode) -> dict[str, object]:
    return {
        "body": comment.body,
        "user": comment.user.name if comment.user else None,
        "created_at": comment.created_at,
    }


def graphql[T: _Model](operation: str, variables: dict[str, object], model: type[T]) -> T:
    response = httpx.post(
        LINEAR_ENDPOINT,
        headers={"Authorization": _api_key(), "Content-Type": "application/json"},
        json={"query": _operations(), "operationName": operation, "variables": variables},
        timeout=30.0,
    )
    try:
        payload: dict[str, object] = response.json()
    except json.JSONDecodeError:
        typer.echo(
            f"Linear API returned a non-JSON response (HTTP {response.status_code}): {response.text[:200]}", err=True
        )
        raise typer.Exit(1) from None

    errors = payload.get("errors")
    if errors:
        typer.echo(f"Linear API error: {json.dumps(errors)}", err=True)
        raise typer.Exit(1)

    data = payload.get("data")
    if data is None:
        typer.echo(f"Linear API returned no data (HTTP {response.status_code})", err=True)
        raise typer.Exit(1)

    return model.model_validate(data)


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

    typer.echo("Refusing to write: fix the title/body to match the AGENTS.md conventions.", err=True)
    raise typer.Exit(1)


def _resolve_team_id(key: str) -> str:
    teams = graphql("Teams", {}, TeamsData).teams.nodes
    for team in teams:
        if team.key == key:
            return team.id

    available = ", ".join(sorted(team.key for team in teams))
    typer.echo(f"No team with key {key!r}; available keys: {available}", err=True)
    raise typer.Exit(1)


def _ensure_label_record(labels: list[LabelNode], name: str, parent_id: str | None, is_group: bool) -> str:
    for label in labels:
        label_parent_id = label.parent.id if label.parent else None
        if label.name == name and label.is_group == is_group and label_parent_id == parent_id:
            return label.id

    fields: dict[str, object] = {"name": name}
    if is_group:
        fields["isGroup"] = True
    if parent_id is not None:
        fields["parentId"] = parent_id

    payload = graphql("CreateLabel", {"input": fields}, IssueLabelCreateData).issue_label_create
    return _require(payload.success, payload.issue_label, f"Failed to create label {name!r}").id


def _require[T](success: bool, value: T | None, message: str) -> T:
    if not success or value is None:
        typer.echo(message, err=True)
        raise typer.Exit(1)

    return value


def _require_ok(success: bool, message: str) -> None:
    if not success:
        typer.echo(message, err=True)
        raise typer.Exit(1)


def _require_fields(fields: dict[str, object], message: str) -> None:
    if not fields:
        typer.echo(message, err=True)
        raise typer.Exit(1)


def _read_stdin() -> str:
    return sys.stdin.read() if not sys.stdin.isatty() else ""


def _team_filter(team: str | None) -> dict[str, object]:
    return {"team": {"key": {"eq": team}}} if team is not None else {}


@cache
def _operations() -> str:
    return Path(__file__).with_name(OPERATIONS_DOCUMENT).read_text(encoding="utf-8")


def _find_up(marker: str) -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / marker
        if candidate.is_file():
            return candidate

    raise RuntimeError(f"No {marker} found in the current directory or any parent; run from inside the repo")


def _api_key() -> str:
    return _resolved_profile().api_key


def _resolved_team(override: str | None) -> str | None:
    if override is not None:
        return override

    return _resolved_profile().team_key


@cache
def _resolved_profile() -> Profile:
    return _resolved_profile_and_name()[1]


@cache
def _resolved_profile_name() -> str:
    return _resolved_profile_and_name()[0]


@cache
def _resolved_profile_and_name() -> tuple[str, Profile]:
    config = load_config()
    if config is None:
        typer.echo(
            f"No profile config found at {CONFIG_PATH}; create one with profiles and path_defaults.",
            err=True,
        )
        raise typer.Exit(1)

    name = resolve_profile_name(config, _CliState.profile_override, Path.cwd())
    return name, config.profiles[name]


def _emit(record: dict[str, object]) -> None:
    typer.echo(json.dumps(record))
