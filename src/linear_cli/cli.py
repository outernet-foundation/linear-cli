from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from bashrun import bash_check, bash_output

from .client import CliState, fail, graphql, mutate, paginate, resolved_profile_name
from .models import (
    IssueDetailData,
    IssueListNode,
    IssueRelationsData,
    IssueSnapshotByIdData,
    IssueSnapshotData,
    IssueSnapshotNode,
    IssuesData,
    LabelNode,
    LabelsData,
    ProjectsData,
    TeamsData,
    WorkflowStatesData,
)
from .operations import (
    ISSUE_DETAIL_FIELDS,
    ISSUE_LIST_FIELDS,
    ISSUE_RELATIONS_FIELDS,
    ISSUE_SNAPSHOT_FIELDS,
    LABEL_FIELDS,
    PROJECT_FIELDS,
    TEAM_FIELDS,
    WORKFLOW_STATE_FIELDS,
    build_list_query,
    build_node_query,
)
from .snapshot import identifier_sort_key, label_snapshot_filter
from .validation import fix_bare_paths, orphan_design_docs, validate_body, validate_label_presence, validate_title

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
issue_app = typer.Typer()
project_app = typer.Typer()
team_app = typer.Typer()
workflow_state_app = typer.Typer()
label_app = typer.Typer()
relation_app = typer.Typer()
comment_app = typer.Typer()
workspace_app = typer.Typer()

app.add_typer(issue_app, name="issue")
app.add_typer(project_app, name="project")
app.add_typer(team_app, name="team")
app.add_typer(workflow_state_app, name="workflow-state")
app.add_typer(label_app, name="label")
app.add_typer(relation_app, name="relation")
app.add_typer(comment_app, name="comment")
app.add_typer(workspace_app, name="workspace")


@app.callback()
def root_callback(
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Profile name from ~/.config/linear-cli/config.json"),
    ] = None,
) -> None:
    CliState.profile_override = profile


@app.command()
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
    query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True, archive_aware=True)
    for issue in paginate(query, {"filter": _team_filter(team)}, IssuesData, lambda data: data.issues):
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


@app.command(name="find-references")
def find_references(
    identifier: Annotated[str, typer.Argument(help="Ticket identifier to search for, e.g. GOV-29")],
    scan_linear: Annotated[
        bool, typer.Option("--scan-linear", help="Also scan Linear ticket bodies and comments")
    ] = False,
) -> None:
    if not bash_check("git rev-parse --show-toplevel"):
        fail("Not inside a git repository")

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
        query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True)
        for issue in paginate(query, {}, IssuesData, lambda data: data.issues):
            if boundary.search(issue.description or "") or boundary.search(issue.title):
                _emit({"source": issue.identifier, "line": 0, "context": "ticket body"})


@issue_app.command(name="list")
def issue_list(
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
    query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True, archive_aware=True)
    for issue in paginate(query, variables, IssuesData, lambda data: data.issues):
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


@issue_app.command(name="get")
def issue_get(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier, e.g. GOV-21")],
) -> None:
    query = build_node_query("issue", ISSUE_DETAIL_FIELDS)
    issue = IssueDetailData.model_validate(graphql(query, {"id": issue_id})).issue
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

    _emit(mutate("issue", "Create", {"input": fields}))


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
        detail_query = build_node_query("issue", ISSUE_DETAIL_FIELDS)
        current = IssueDetailData.model_validate(graphql(detail_query, {"id": issue_id})).issue
        current_ids = {ref.id for ref in current.labels.nodes}
        add_ids: set[str] = set(_resolve_label_ids(add_label)) if add_label else set()
        remove_ids: set[str] = set(_resolve_label_ids(remove_label)) if remove_label else set()
        fields["labelIds"] = list(current_ids | add_ids - remove_ids)
    if team is not None:
        fields["teamId"] = _resolve_team_id(team)
    if state is not None:
        if team is None:
            fail("--state requires --team to specify which team's workflow to resolve against")
        fields["stateId"] = _resolve_state_id(state, team)

    if priority is not None:
        fields["priority"] = priority

    _require_fields(
        fields,
        "Nothing to update; pass --team, --title, --label, --add-label, --remove-label, --state, --priority, or a body on stdin",
    )

    _emit(mutate("issue", "Update", {"id": issue_id, "input": fields}))


@issue_app.command(name="unarchive")
def issue_unarchive(
    issue_id: Annotated[str, typer.Option("--id", help="Issue id or identifier to unarchive")],
) -> None:
    _emit(mutate("issue", "Unarchive", {"id": issue_id}))


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
        node_query = build_node_query("issue", ISSUE_SNAPSHOT_FIELDS)
        nodes = [
            IssueSnapshotByIdData.model_validate(graphql(node_query, {"id": identifier})).issue for identifier in issue
        ]
    elif label is not None:
        list_query = build_list_query("issues", ISSUE_SNAPSHOT_FIELDS, filter_type="IssueFilter", paginated=True)
        nodes = list(
            paginate(list_query, {"filter": label_snapshot_filter(label)}, IssueSnapshotData, lambda data: data.issues)
        )
    else:
        fail("Pass --issue (repeatable) or --label to select issues to snapshot.")
    nodes.sort(key=lambda node: identifier_sort_key(node.identifier))

    typer.echo(
        json.dumps(
            {
                "captured_at": datetime.now(UTC).isoformat(),
                "linear_profile": resolved_profile_name(),
                "issues": [_snapshot_issue_dict(node) for node in nodes],
            },
            indent=2,
        )
    )


@relation_app.command(name="list")
def relation_list(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
) -> None:
    query = build_list_query("issues", ISSUE_RELATIONS_FIELDS, filter_type="IssueFilter", paginated=True)
    for issue_node in paginate(query, {"filter": _team_filter(team)}, IssueRelationsData, lambda data: data.issues):
        for relation in issue_node.relations.nodes:
            if relation.related_issue is None:
                continue

            _emit({"source": issue_node.identifier, "target": relation.related_issue.identifier, "type": relation.type})


@relation_app.command(name="create")
def relation_create(
    blocker: Annotated[str, typer.Option("--blocker", help="Issue id that does the blocking")],
    blocked: Annotated[str, typer.Option("--blocked", help="Issue id that is blocked")],
) -> None:
    fields: dict[str, object] = {"issueId": blocker, "relatedIssueId": blocked, "type": "blocks"}
    mutate("issueRelation", "Create", {"input": fields})
    _emit({"blocker": blocker, "blocked": blocked, "type": "blocks"})


@comment_app.command(name="create", help="Reads the comment body (markdown) from stdin. Required.")
def comment_create(
    issue_id: Annotated[str, typer.Option("--issue", help="Issue id to comment on")],
) -> None:
    body = _read_stdin()
    if not body.strip():
        fail("No comment body on stdin")

    _emit(mutate("comment", "Create", {"input": {"issueId": issue_id, "body": body}}))


@comment_app.command(name="delete")
def comment_delete(
    comment_id: Annotated[str, typer.Option("--id", help="Comment id to delete")],
) -> None:
    _emit(mutate("comment", "Delete", {"id": comment_id}))


@project_app.command(name="list")
def project_list() -> None:
    query = build_list_query("projects", PROJECT_FIELDS, paginated=True)
    for project in paginate(query, {}, ProjectsData, lambda data: data.projects):
        _emit({"id": project.id, "name": project.name, "state": project.state, "url": project.url})


@project_app.command(name="create", help="Reads the project content (markdown body) from stdin.")
def project_create(
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

    _emit(mutate("project", "Create", {"input": fields}))


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
            fail("--team requires at least one team key")
        fields["teamIds"] = [_resolve_team_id(key) for key in team]

    _require_fields(fields, "Nothing to update; pass --team, --name, --summary, or a body on stdin")

    _emit(mutate("project", "Update", {"id": project_id, "input": fields}))


@project_app.command(name="delete")
def project_delete(
    project_id: Annotated[str, typer.Option("--id", help="Project id to delete")],
) -> None:
    _emit(mutate("project", "Delete", {"id": project_id}))


@team_app.command(name="list")
def team_list() -> None:
    query = build_list_query("teams", TEAM_FIELDS)
    teams = TeamsData.model_validate(graphql(query, {})).teams.nodes
    for team in sorted(teams, key=lambda team: team.key):
        _emit({"id": team.id, "key": team.key, "name": team.name})


@team_app.command(name="create")
def team_create(
    name: Annotated[str, typer.Option("--name", help="Team display name")],
    key: Annotated[str, typer.Option("--key", help="Team key, e.g. GOV")],
    description: Annotated[str | None, typer.Option("--description", help="Optional team description")] = None,
) -> None:
    fields: dict[str, object] = {"name": name, "key": key}
    if description is not None:
        fields["description"] = description

    _emit(mutate("team", "Create", {"input": fields}))


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

    _require_fields(fields, "Nothing to update; pass --name and/or --description")

    _emit(mutate("team", "Update", {"id": team_id, "input": fields}))


@workflow_state_app.command(name="list")
def workflow_state_list(
    team: Annotated[str, typer.Option("--team", help="Team key, e.g. GOV")],
) -> None:
    query = build_list_query("workflowStates", WORKFLOW_STATE_FIELDS, filter_type="WorkflowStateFilter")
    states = WorkflowStatesData.model_validate(graphql(query, {"filter": _team_filter(team)})).workflow_states.nodes
    for state in states:
        _emit({"id": state.id, "name": state.name, "type": state.type})


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
        "teamId": _resolve_team_id(team),
        "name": name,
        "type": state_type,
        "color": color,
    }
    if description is not None:
        fields["description"] = description
    if position is not None:
        fields["position"] = position

    _emit(mutate("workflowState", "Create", {"input": fields}))


@workflow_state_app.command(name="archive")
def workflow_state_archive(
    state_id: Annotated[str, typer.Option("--id", help="Workflow state id to archive")],
) -> None:
    _emit(mutate("workflowState", "Archive", {"id": state_id}))


@label_app.command(name="list")
def label_list() -> None:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
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


@label_app.command(name="ensure")
def label_ensure(
    name: Annotated[str, typer.Option("--name", help="Leaf label name")],
    parent: Annotated[str | None, typer.Option("--parent", help="Parent label-group name to nest under")] = None,
) -> None:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
    parent_id = _ensure_label_record(labels, parent, None, is_group=True) if parent is not None else None
    leaf_id = _ensure_label_record(labels, name, parent_id, is_group=False)
    _emit({"id": leaf_id})


@label_app.command(name="update")
def label_update(
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
        query = build_list_query("issueLabels", LABEL_FIELDS)
        labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
        groups = [node for node in labels if node.is_group and node.name == parent]
        if len(groups) != 1:
            fail(f"Expected exactly one group named {parent!r}, found {len(groups)}")

        fields["parentId"] = groups[0].id

    _require_fields(fields, "Nothing to update; pass --name, --parent, and/or --color")

    _emit(mutate("issueLabel", "Update", {"id": label_id, "input": fields}))


@label_app.command(name="delete")
def label_delete(
    label_id: Annotated[str, typer.Option("--id", help="Label id to delete")],
) -> None:
    _emit(mutate("issueLabel", "Delete", {"id": label_id}))


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
            _snapshot_issue_dict(node) for node in sorted(issues, key=lambda node: identifier_sort_key(node.identifier))
        ],
    }
    typer.echo(json.dumps(record, indent=2))


def _require_fields(fields: dict[str, object], message: str) -> None:
    if not fields:
        fail(message)


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

    fail("Refusing to write: fix the title/body to match the AGENTS.md conventions.")


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
            mutate("issue", "Update", {"id": issue.id, "input": {"description": fixed_body}})
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
        fail("No design/AGENTS.md found in the current directory or any parent; run from inside the repo")
    doc_names = [path.name for path in sorted(design_dir.glob("*.md")) if path.name not in ("AGENTS.md", "CLAUDE.md")]
    return orphan_design_docs(doc_names, open_bodies)


def _resolve_team_id(key: str) -> str:
    query = build_list_query("teams", TEAM_FIELDS)
    teams = TeamsData.model_validate(graphql(query, {})).teams.nodes
    team = next((team for team in teams if team.key == key), None)
    if team is None:
        available = ", ".join(sorted(team.key for team in teams))
        fail(f"No team with key {key!r}; available keys: {available}")
    return team.id


def _resolve_label_group(group_name: str) -> set[str]:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    all_labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
    names_by_id = {label.id: label.name for label in all_labels}
    group_labels = {
        label.name for label in all_labels if label.parent and names_by_id.get(label.parent.id) == group_name
    }
    if not group_labels:
        fail(
            f"No labels found in group {group_name!r}; available groups: "
            f"{', '.join(sorted(label.name for label in all_labels if label.is_group))}"
        )
    return group_labels


def _resolve_state_id(state: str, team: str) -> str:
    query = build_list_query("workflowStates", WORKFLOW_STATE_FIELDS, filter_type="WorkflowStateFilter")
    states = WorkflowStatesData.model_validate(graphql(query, {"filter": _team_filter(team)})).workflow_states.nodes
    matches = [candidate for candidate in states if candidate.name.casefold() == state.casefold()]
    if len(matches) != 1:
        available = ", ".join(sorted(candidate.name for candidate in states))
        fail(f"No unique state {state!r} in team {team!r}; available: {available}")
    return matches[0].id


def _resolve_label_ids(labels: list[str]) -> list[str]:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    all_labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
    name_to_id = {label.name: label.id for label in all_labels}
    resolved: list[str] = []
    for label in labels:
        if label in name_to_id:
            resolved.append(name_to_id[label])
        elif len(label) == 36 and label.count("-") == 4:
            resolved.append(label)
        else:
            available = ", ".join(sorted(name_to_id))
            fail(f"Unknown label {label!r}; available names: {available}")
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

    node = mutate("issueLabel", "Create", {"input": fields})
    node_id = node["id"]
    if not isinstance(node_id, str):
        fail("Linear API returned a non-string id for created label")
    return node_id


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
