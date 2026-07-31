from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun import bash_check, bash_output

from .client import CliState, emit, fail, graphql, mutate, paginate, team_filter
from .commands.comment import comment_app
from .commands.issue import issue_app
from .commands.label import label_app
from .commands.project import project_app
from .commands.relation import relation_app
from .commands.team import team_app
from .commands.workflow_state import workflow_state_app
from .commands.workspace import workspace_app
from .models import IssueListNode, IssuesData, LabelsData
from .operations import ISSUE_LIST_FIELDS, LABEL_FIELDS, build_list_query
from .validation import fix_bare_paths, orphan_design_docs, validate_body, validate_label_presence, validate_title

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

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
            emit({"identifier": issue.identifier, "fixed_paths": fixes})
            body = fixed_body
            violations = _issue_violations(issue.title, body, label_names, group_labels, group_name)
            violations = [v for v in violations if not v.startswith("bare path")]

    return body, violations


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
