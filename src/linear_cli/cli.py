from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer
from bashrun import bash_check, bash_output
from pydantic import BaseModel, ConfigDict, Field

from .profiles import (
    CONFIG_PATH,
    ProfileConfig,
    load_config,
    resolve_profile_name,
)
from .snapshot import identifier_sort_key, label_snapshot_filter
from .validation import fix_bare_paths, orphan_design_docs, validate_body, validate_label_presence, validate_title

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
OPERATIONS_DOCUMENT = "linear_operations.graphql"
_OPERATIONS = Path(__file__).with_name(OPERATIONS_DOCUMENT).read_text(encoding="utf-8")

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


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
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    labels: _NodeList[IssueLabelName]
    project: ProjectRef | None = None


class AttachmentNode(_Model):
    id: str
    title: str | None = None
    subtitle: str | None = None
    url: str
    metadata: dict[str, object] | None = None


class LabelIdRef(_Model):
    id: str


class IssueDetailNode(_Model):
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: _NodeList[LabelIdRef] = Field(default_factory=lambda: _NodeList(nodes=[]))
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
    priority: int = 0
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
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


class SuccessPayload(_Model):
    success: bool


class IssueLabelMutationPayload(_Model):
    success: bool
    issue_label: CreatedLabel | None = Field(default=None, alias="issueLabel")


class ProjectMutationPayload(_Model):
    success: bool
    project: CreatedProject | None = None


class TeamMutationPayload(_Model):
    success: bool
    team: CreatedTeam | None = None


class WorkflowStateMutationPayload(_Model):
    success: bool
    workflow_state: CreatedWorkflowState | None = Field(default=None, alias="workflowState")


class IssueMutationPayload(_Model):
    success: bool
    issue: CreatedIssue | None = None


class CommentCreatePayload(_Model):
    success: bool
    comment: CommentNode | None = None


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
    issue_label_delete: SuccessPayload = Field(alias="issueLabelDelete")


class ProjectCreateData(_Model):
    project_create: ProjectMutationPayload = Field(alias="projectCreate")


class TeamCreateData(_Model):
    team_create: TeamMutationPayload = Field(alias="teamCreate")


class TeamUpdateData(_Model):
    team_update: TeamMutationPayload = Field(alias="teamUpdate")


class WorkflowStateCreateData(_Model):
    workflow_state_create: WorkflowStateMutationPayload = Field(alias="workflowStateCreate")


class WorkflowStateArchiveData(_Model):
    workflow_state_archive: SuccessPayload = Field(alias="workflowStateArchive")


class ProjectUpdateData(_Model):
    project_update: ProjectMutationPayload = Field(alias="projectUpdate")


class ProjectDeleteData(_Model):
    project_delete: SuccessPayload = Field(alias="projectDelete")


class IssueCreateData(_Model):
    issue_create: IssueMutationPayload = Field(alias="issueCreate")


class IssueUpdateData(_Model):
    issue_update: IssueMutationPayload = Field(alias="issueUpdate")


class IssueRelationCreateData(_Model):
    issue_relation_create: SuccessPayload = Field(alias="issueRelationCreate")


class CommentCreateData(_Model):
    comment_create: CommentCreatePayload = Field(alias="commentCreate")


class CommentDeleteData(_Model):
    comment_delete: SuccessPayload = Field(alias="commentDelete")


class IssueUnarchiveData(_Model):
    issue_unarchive: SuccessPayload = Field(alias="issueUnarchive")


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
    label: Annotated[str | None, typer.Option("--label", help="Label name to filter by")] = None,
    include_archived: Annotated[
        bool, typer.Option("--include-archived", help="Include archived issues in results")
    ] = False,
) -> None:
    filter_dict: dict[str, object] = _team_filter(team)
    if label is not None:
        filter_dict["labels"] = {"name": {"eq": label}}
    variables: dict[str, object] = {"filter": filter_dict}
    if include_archived:
        variables["includeArchived"] = True
    for issue in _paginate("Issues", variables, IssuesData, lambda data: data.issues):
        _emit({
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


@app.command(name="get-issue")
def get_issue(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier, e.g. GOV-21")],
) -> None:
    issue = graphql("Issue", {"id": issue_id}, IssueDetailData).issue
    _emit({
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


@app.command(name="list-relations")
def list_relations(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
) -> None:
    for issue in _paginate(
        "IssueRelations", {"filter": _team_filter(team)}, IssueRelationsData, lambda data: data.issues
    ):
        for relation in issue.relations.nodes:
            if relation.related_issue is None:
                continue

            _emit({"source": issue.identifier, "target": relation.related_issue.identifier, "type": relation.type})


@app.command(name="find-references")
def find_references(
    identifier: Annotated[str, typer.Argument(help="Ticket identifier to search for, e.g. GOV-29")],
    scan_linear: Annotated[
        bool, typer.Option("--scan-linear", help="Also scan Linear ticket bodies and comments")
    ] = False,
) -> None:
    if not bash_check("git rev-parse --show-toplevel"):
        _fail("Not inside a git repository")

    repository_root = Path(bash_output("git rev-parse --show-toplevel").strip())
    boundary = re.compile(r"\b" + re.escape(identifier) + r"\b")

    for file_path in sorted(repository_root.rglob("*")):
        if ".git" in file_path.parts or "_build" in file_path.parts or not file_path.is_file():
            continue
        if file_path.suffix not in (".md", ".yml", ".yaml", ".json"):
            continue
        text = file_path.read_text(errors="ignore")
        for line_number, line in enumerate(text.splitlines(), 1):
            if boundary.search(line):
                _emit({
                    "source": str(file_path.relative_to(repository_root)),
                    "line": line_number,
                    "context": line.strip()[:200],
                })

    if scan_linear:
        for issue in _paginate("Issues", {}, IssuesData, lambda data: data.issues):
            if boundary.search(issue.description or "") or boundary.search(issue.title):
                _emit({"source": issue.identifier, "line": 0, "context": "ticket body"})


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
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. GOV")],
) -> None:
    states = graphql("WorkflowStates", {"filter": _team_filter(team)}, WorkflowStatesData).workflow_states.nodes
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


@app.command(name="update-team")
def update_team(
    team_id: Annotated[str, typer.Option("--id", help="Team id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New team display name")] = None,
    description: Annotated[str | None, typer.Option("--description", help="New team description")] = None,
) -> None:
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description

    _require_fields(fields, "Nothing to update; pass --name and/or --description")

    payload = graphql("UpdateTeam", {"id": team_id, "input": fields}, TeamUpdateData).team_update
    team = _require(payload.success, payload.team, f"Failed to update team {team_id!r}")
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
    fields: dict[str, object] = {
        "teamId": _resolve_team_id(team),
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
        typer.Option("--issue", help="Issue identifier to include (repeatable), e.g. GOV-5"),
    ] = None,
    label: Annotated[
        str | None, typer.Option("--label", help="Label name; snapshot every issue carrying this label")
    ] = None,
) -> None:
    if issue is not None and label is not None:
        _fail("Pass --issue or --label, not both.")

    if issue is not None:
        nodes = [graphql("IssueSnapshotById", {"id": identifier}, IssueSnapshotByIdData).issue for identifier in issue]
    elif label is not None:
        nodes = list(
            _paginate(
                "IssueSnapshot", {"filter": label_snapshot_filter(label)}, IssueSnapshotData, lambda data: data.issues
            )
        )
    else:
        _fail("Pass --issue (repeatable) or --label to select issues to snapshot.")
    nodes.sort(key=lambda node: identifier_sort_key(node.identifier))

    typer.echo(
        json.dumps(
            {
                "captured_at": datetime.now(UTC).isoformat(),
                "linear_profile": _resolved_profile_name(),
                "issues": [_snapshot_issue_dict(node) for node in nodes],
            },
            indent=2,
        )
    )


@app.command(name="snapshot-workspace")
def snapshot_workspace() -> None:
    captured_at = datetime.now(UTC).isoformat()
    profile_name = _resolved_profile_name()

    teams = graphql("Teams", {}, TeamsData).teams.nodes
    projects = list(_paginate("Projects", {}, ProjectsData, lambda data: data.projects))
    labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
    workflow_states = graphql("WorkflowStates", {"filter": {}}, WorkflowStatesData).workflow_states.nodes
    issues = list(_paginate("IssueSnapshot", {"includeArchived": True}, IssueSnapshotData, lambda data: data.issues))

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
            _snapshot_issue_dict(node) for node in sorted(issues, key=lambda node: identifier_sort_key(node.identifier))
        ],
    }
    typer.echo(json.dumps(record, indent=2))


@app.command(name="lint")
def lint(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
    design_orphans: Annotated[
        bool, typer.Option("--design-orphans", help="Also flag design/ docs that no open ticket links")
    ] = False,
    include_canceled: Annotated[bool, typer.Option("--include-canceled", help="Also lint canceled issues")] = False,
    require_label_parent: Annotated[
        str | None,
        typer.Option(
            "--require-label-parent", help="Require every ticket to carry a label in this parent group, e.g. repo"
        ),
    ] = None,
    fix_paths: Annotated[
        bool,
        typer.Option("--fix-paths", help="Auto-fix bare repo-relative paths in ticket bodies to full GitHub blob URLs"),
    ] = False,
) -> None:
    skip_types = {"completed"}
    if not include_canceled:
        skip_types.add("canceled")

    group_labels: set[str] | None = None
    if require_label_parent is not None:
        group_labels = _resolve_label_group(require_label_parent)

    repo_urls, default_repository = _discover_repo_urls() if fix_paths else ({}, None)

    offenders = 0
    open_bodies: list[str] = []
    for issue in _paginate("Issues", {"filter": _team_filter(team)}, IssuesData, lambda data: data.issues):
        if issue.state.type in skip_types:
            continue

        issue_body, violations = _lint_issue(
            issue, group_labels, require_label_parent, fix_paths, repo_urls, default_repository
        )
        open_bodies.append(issue_body)
        if violations:
            offenders += 1
            _emit({"identifier": issue.identifier, "title": issue.title, "violations": violations})

    if design_orphans:
        for name in _orphaned_design_docs(open_bodies):
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
            _fail(f"Expected exactly one group named {parent!r}, found {len(groups)}")

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
    team: Annotated[str, typer.Option("--team", help="Team key the project belongs to, e.g. PLE")],
    summary: Annotated[str, typer.Option("--summary", help="One-line project description")] = "",
) -> None:
    content = _read_stdin()
    fields: dict[str, object] = {"name": name, "teamIds": [_resolve_team_id(team)]}
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
    team: Annotated[
        list[str] | None,
        typer.Option("--team", help="Team key for the project (repeatable); replaces the project's team set"),
    ] = None,
) -> None:
    content = _read_stdin()
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if summary is not None:
        fields["description"] = summary
    if content.strip():
        fields["content"] = content
    if team is not None:
        if len(team) == 0:
            _fail("--team requires at least one team key")
        fields["teamIds"] = [_resolve_team_id(key) for key in team]

    _require_fields(fields, "Nothing to update; pass --team, --name, --summary, or a body on stdin")

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
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. PLE")],
    project: Annotated[str | None, typer.Option("--project", help="Project id to file the issue under")] = None,
    label: Annotated[list[str] | None, typer.Option("--label", help="Label name or id to attach (repeatable)")] = None,
    priority: Annotated[int | None, typer.Option("--priority", help="Issue priority: 0=none, 1=urgent, 2=high")] = None,
) -> None:
    description = _read_stdin()
    _enforce_conventions(title, description)
    fields: dict[str, object] = {"teamId": _resolve_team_id(team), "title": title}
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label:
        fields["labelIds"] = _resolve_label_ids(label)
    if priority is not None:
        fields["priority"] = priority

    payload = graphql("CreateIssue", {"input": fields}, IssueCreateData).issue_create
    issue = _require(payload.success, payload.issue, f"Failed to create issue {title!r}")
    _emit({"id": issue.id, "identifier": issue.identifier, "url": issue.url})


@app.command(
    name="update-issue",
    help="Reads the new issue description (markdown body) from stdin if any is piped in. Piped bodies must match the Why/Done-when/Links template.",
)
def update_issue(
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
    description = _read_stdin()
    _enforce_conventions(title, description if description.strip() else None)
    fields: dict[str, object] = {}
    if title is not None:
        fields["title"] = title
    if description.strip():
        fields["description"] = description
    if project is not None:
        fields["projectId"] = project
    if label is not None and add_label is None and remove_label is None:
        fields["labelIds"] = _resolve_label_ids(label)
    elif add_label is not None or remove_label is not None:
        issue = graphql("Issue", {"id": issue_id}, IssueDetailData).issue
        current_ids = {ref.id for ref in issue.labels.nodes}
        add_ids: set[str] = set(_resolve_label_ids(add_label)) if add_label else set()
        remove_ids: set[str] = set(_resolve_label_ids(remove_label)) if remove_label else set()
        fields["labelIds"] = list(current_ids | add_ids - remove_ids)
    if team is not None:
        fields["teamId"] = _resolve_team_id(team)
    if state is not None:
        if team is None:
            _fail("--state requires --team to specify which team's workflow to resolve against")
        fields["stateId"] = _resolve_state_id(state, team)

    if priority is not None:
        fields["priority"] = priority

    _require_fields(
        fields,
        "Nothing to update; pass --team, --title, --label, --add-label, --remove-label, --state, --priority, or a body on stdin",
    )

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
        _fail("No comment body on stdin")

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


@app.command(name="unarchive-issue")
def unarchive_issue(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier to unarchive")],
) -> None:
    payload = graphql("IssueUnarchive", {"id": issue_id}, IssueUnarchiveData).issue_unarchive
    _require_ok(payload.success, f"Failed to unarchive issue {issue_id!r}")
    _emit({"id": issue_id, "unarchived": True})


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


@cache
def _load_config_or_die() -> ProfileConfig:
    config = load_config()
    if config is None:
        _fail(f"No profile config found at {CONFIG_PATH}; create one with profiles and path_defaults.")
    return config


@cache
def _resolved_profile_name() -> str:
    return resolve_profile_name(_load_config_or_die(), _CliState.profile_override, Path.cwd())


def graphql[T: _Model](operation: str, variables: dict[str, object], model: type[T]) -> T:
    response = httpx.post(
        LINEAR_ENDPOINT,
        headers={
            "Authorization": _load_config_or_die().root[_resolved_profile_name()].api_key,
            "Content-Type": "application/json",
        },
        json={"query": _OPERATIONS, "operationName": operation, "variables": variables},
        timeout=30.0,
    )
    try:
        payload: dict[str, object] = response.json()
    except json.JSONDecodeError:
        _fail(f"Linear API returned a non-JSON response (HTTP {response.status_code}): {response.text[:200]}")

    errors = payload.get("errors")
    if errors:
        _fail(f"Linear API error: {json.dumps(errors)}")

    data = payload.get("data")
    if data is None:
        _fail(f"Linear API returned no data (HTTP {response.status_code})")

    return model.model_validate(data)


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


def _require[T](success: bool, value: T | None, message: str) -> T:
    if not success or value is None:
        _fail(message)
    return value


def _require_ok(success: bool, message: str) -> None:
    if not success:
        _fail(message)


def _require_fields(fields: dict[str, object], message: str) -> None:
    if not fields:
        _fail(message)


def _team_filter(team: str | None) -> dict[str, object]:
    return {"team": {"key": {"eq": team}}} if team is not None else {}


def _read_stdin() -> str:
    return sys.stdin.read() if not sys.stdin.isatty() else ""


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

    _fail("Refusing to write: fix the title/body to match the AGENTS.md conventions.")


def _issue_violations(
    title: str,
    body: str,
    label_names: list[str],
    group_labels: set[str] | None = None,
    group_name: str | None = None,
) -> list[str]:
    violations = validate_title(title) + validate_body(body)
    if group_labels is not None and group_name is not None:
        violations += validate_label_presence(label_names, group_labels, group_name)
    return violations


def _lint_issue(
    issue: IssueListNode,
    group_labels: set[str] | None,
    group_name: str | None,
    fix_paths: bool,
    repo_urls: dict[str, str],
    default_repository: str | None,
) -> tuple[str, list[str]]:
    body = issue.description or ""
    label_names = [label.name for label in issue.labels.nodes]
    violations = _issue_violations(issue.title, body, label_names, group_labels, group_name)

    bare_path_violations = [v for v in violations if v.startswith("bare path")]
    if fix_paths and bare_path_violations:
        fixed_body, fixes = fix_bare_paths(body, repo_urls, default_repository)
        if fixes:
            graphql("UpdateIssue", {"id": issue.id, "input": {"description": fixed_body}}, IssueUpdateData)
            _emit({"identifier": issue.identifier, "fixed_paths": fixes})
            body = fixed_body
            violations = _issue_violations(issue.title, body, label_names, group_labels, group_name)
            violations = [v for v in violations if not v.startswith("bare path")]

    return body, violations


def _orphaned_design_docs(open_bodies: list[str]) -> list[str]:
    design_dir = next(
        (
            directory / "design"
            for directory in (Path.cwd(), *Path.cwd().parents)
            if (directory / "design/AGENTS.md").is_file()
        ),
        None,
    )
    if design_dir is None:
        _fail("No design/AGENTS.md found in the current directory or any parent; run from inside the repo")
    doc_names = [path.name for path in sorted(design_dir.glob("*.md")) if path.name not in ("AGENTS.md", "CLAUDE.md")]
    return orphan_design_docs(doc_names, open_bodies)


def _resolve_team_id(key: str) -> str:
    teams = graphql("Teams", {}, TeamsData).teams.nodes
    team = next((team for team in teams if team.key == key), None)
    if team is None:
        available = ", ".join(sorted(team.key for team in teams))
        _fail(f"No team with key {key!r}; available keys: {available}")
    return team.id


def _resolve_label_group(group_name: str) -> set[str]:
    all_labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
    names_by_id = {label.id: label.name for label in all_labels}
    group_labels = {
        label.name for label in all_labels if label.parent and names_by_id.get(label.parent.id) == group_name
    }
    if not group_labels:
        _fail(
            f"No labels found in group {group_name!r}; available groups: "
            f"{', '.join(sorted(label.name for label in all_labels if label.is_group))}"
        )
    return group_labels


def _resolve_state_id(state: str, team: str) -> str:
    states = graphql("WorkflowStates", {"filter": _team_filter(team)}, WorkflowStatesData).workflow_states.nodes
    matches = [candidate for candidate in states if candidate.name.casefold() == state.casefold()]
    if len(matches) != 1:
        available = ", ".join(sorted(candidate.name for candidate in states))
        _fail(f"No unique state {state!r} in team {team!r}; available: {available}")
    return matches[0].id


def _resolve_label_ids(labels: list[str]) -> list[str]:
    all_labels = graphql("Labels", {}, LabelsData).issue_labels.nodes
    name_to_id = {label.name: label.id for label in all_labels}
    resolved: list[str] = []
    for label in labels:
        if label in name_to_id:
            resolved.append(name_to_id[label])
        elif len(label) == 36 and label.count("-") == 4:
            resolved.append(label)
        else:
            available = ", ".join(sorted(name_to_id))
            _fail(f"Unknown label {label!r}; available names: {available}")
    return resolved


def _ensure_label_record(labels: list[LabelNode], name: str, parent_id: str | None, is_group: bool) -> str:
    existing = next(
        (
            label.id
            for label in labels
            if label.name == name
            and label.is_group == is_group
            and (label.parent.id if label.parent else None) == parent_id
        ),
        None,
    )
    if existing is not None:
        return existing

    fields: dict[str, object] = {"name": name}
    if is_group:
        fields["isGroup"] = True
    if parent_id is not None:
        fields["parentId"] = parent_id

    payload = graphql("CreateLabel", {"input": fields}, IssueLabelCreateData).issue_label_create
    return _require(payload.success, payload.issue_label, f"Failed to create label {name!r}").id


def _snapshot_issue_dict(node: IssueSnapshotNode) -> dict[str, object]:
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


def _discover_repo_urls() -> tuple[dict[str, str], str | None]:
    mappings: dict[str, str] = {}
    default_repository: str | None = None

    cwd = Path.cwd()
    for repository_directory in sorted(cwd.parent.iterdir()) if cwd.parent.exists() else []:
        if not repository_directory.is_dir() or repository_directory.name.startswith("."):
            continue
        if not bash_check("git remote get-url origin", cwd=repository_directory):
            continue
        remote = bash_output("git remote get-url origin", cwd=repository_directory).strip()
        match = re.match(r"(?:https://|git@)github\.com[/:](\S+?)(?:\.git)?$", remote)
        if not match:
            continue
        base = f"https://github.com/{match.group(1)}/blob/main"
        mappings[repository_directory.name] = base
        projects_directory = repository_directory / "projects"
        if projects_directory.is_dir():
            for project_directory in sorted(projects_directory.iterdir()):
                if project_directory.is_dir() and not project_directory.name.startswith("."):
                    mappings[project_directory.name] = f"{base}/projects/{project_directory.name}"
        if cwd == repository_directory or repository_directory in cwd.parents:
            default_repository = repository_directory.name

    return mappings, default_repository


def _emit(record: dict[str, object]) -> None:
    typer.echo(json.dumps(record))
