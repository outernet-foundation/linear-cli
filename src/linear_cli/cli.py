from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from bashrun import bash_check, bash_output

from .api import CliState, build_list_query, emit, fail, graphql, mutate, paginate, resolved_profile_name, team_filter
from .nouns.comment import comment_app
from .nouns.issue import (
    ISSUE_LIST_FIELDS,
    ISSUE_SNAPSHOT_FIELDS,
    IssueListNode,
    IssueSnapshotData,
    IssuesData,
    issue_app,
    identifier_sort_key,
    snapshot_issue_dict,
)
from .nouns.label import LABEL_FIELDS, LabelsData, label_app
from .nouns.project import PROJECT_FIELDS, ProjectsData, project_app
from .nouns.relation import relation_app
from .nouns.team import TEAM_FIELDS, TeamsData, team_app
from .nouns.workflow_state import WORKFLOW_STATE_FIELDS, WorkflowStatesData, workflow_state_app
from .validation import fix_bare_paths, orphan_design_docs, validate_body, validate_label_presence, validate_title

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

app.add_typer(issue_app, name="issue")
app.add_typer(project_app, name="project")
app.add_typer(team_app, name="team")
app.add_typer(workflow_state_app, name="workflow-state")
app.add_typer(label_app, name="label")
app.add_typer(relation_app, name="relation")
app.add_typer(comment_app, name="comment")


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
    for issue in paginate(query, {"filter": team_filter(team)}, IssuesData, lambda data: data.issues):
        if issue.state.type in skip_types:
            continue

        issue_body, violations = _lint_issue(
            issue, group_labels, require_label_parent, fix_paths, repo_urls, default_repository
        )
        open_bodies.append(issue_body)
        if violations:
            offenders += 1
            emit({"identifier": issue.identifier, "title": issue.title, "violations": violations})

    if design_orphans:
        for name in _orphaned_design_docs(open_bodies):
            offenders += 1
            emit({"design_orphan": f"design/{name}", "violations": ["no open Linear ticket links this design doc"]})

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
                emit({
                    "source": str(file_path.relative_to(repository_root)),
                    "line": line_number,
                    "context": line.strip()[:200],
                })

    if scan_linear:
        query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True)
        for issue in paginate(query, {}, IssuesData, lambda data: data.issues):
            if boundary.search(issue.description or "") or boundary.search(issue.title):
                emit({"source": issue.identifier, "line": 0, "context": "ticket body"})


@app.command()
def snapshot() -> None:
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

    if not fix_paths:
        return body, violations

    bare_path_violations = [v for v in violations if v.startswith("bare path")]
    if not bare_path_violations:
        return body, violations

    fixed_body, fixes = fix_bare_paths(body, repo_urls, default_repository)
    if not fixes:
        return body, violations

    fixed_violations = _issue_violations(issue.title, fixed_body, label_names, group_labels, group_name)
    fixed_bare_path_count = sum(1 for v in fixed_violations if v.startswith("bare path"))
    if fixed_bare_path_count >= len(bare_path_violations):
        violations.append(
            f"--fix-paths did not reduce bare-path violations ({len(bare_path_violations)} -> {fixed_bare_path_count}); body not written"
        )
        return body, violations

    mutate("issue", "Update", {"id": issue.id, "input": {"description": fixed_body}})
    emit({"identifier": issue.identifier, "fixed_paths": fixes})
    return fixed_body, fixed_violations


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
