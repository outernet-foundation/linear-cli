from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    node: str
    return_fields: str


RESOURCES: dict[str, Resource] = {
    "team": Resource(node="team", return_fields="id key name"),
    "issue": Resource(node="issue", return_fields="id identifier url"),
    "project": Resource(node="project", return_fields="id url"),
    "issueLabel": Resource(node="issueLabel", return_fields="id name"),
    "workflowState": Resource(node="workflowState", return_fields="id name type"),
    "comment": Resource(node="comment", return_fields="id url"),
    "issueRelation": Resource(node="", return_fields=""),
}

DELETE_VERBS: dict[str, str] = {
    "Delete": "deleted",
    "Archive": "archived",
    "Unarchive": "unarchived",
}

TEAM_FIELDS = "id key name"
LABEL_FIELDS = "id name color isGroup parent { id }"
WORKFLOW_STATE_FIELDS = "id name type"
PROJECT_FIELDS = "id name url state"

ISSUE_LIST_FIELDS = (
    "id identifier title description url createdAt archivedAt "
    "state { name type } labels { nodes { name } } project { id name }"
)
ISSUE_DETAIL_FIELDS = (
    "identifier title description url createdAt archivedAt "
    "state { name type } team { id key name } project { id name } "
    "labels { nodes { id } } attachments { nodes { id title subtitle url metadata } }"
)
ISSUE_SNAPSHOT_FIELDS = (
    "id identifier title description priority archivedAt "
    "state { name type } team { id key name } project { id name } "
    "labels { nodes { name } } comments { nodes { body createdAt user { name } } }"
)
ISSUE_RELATIONS_FIELDS = "identifier relations { nodes { type relatedIssue { identifier } } }"


def _pascal(noun: str) -> str:
    return noun[0].upper() + noun[1:]


def build_mutation(noun: str, verb: str) -> str:
    resource = RESOURCES[noun]
    field = f"{noun}{verb}"
    node_selection = f" {resource.node} {{ {resource.return_fields} }}" if resource.return_fields else ""

    if verb == "Create":
        return (
            f"mutation($input: {_pascal(noun)}CreateInput!) {{ {field}(input: $input) {{ success{node_selection} }} }}"
        )
    if verb == "Update":
        return (
            f"mutation($id: String!, $input: {_pascal(noun)}UpdateInput!) "
            f"{{ {field}(id: $id, input: $input) {{ success{node_selection} }} }}"
        )
    return f"mutation($id: String!) {{ {field}(id: $id) {{ success }} }}"


def build_list_query(
    connection: str,
    fields: str,
    *,
    filter_type: str | None = None,
    paginated: bool = False,
    archive_aware: bool = False,
) -> str:
    vars_def: list[str] = []
    args: list[str] = ["first: 250"]

    if filter_type:
        vars_def.append(f"$filter: {filter_type}")
        args.append("filter: $filter")
    if paginated:
        vars_def.append("$after: String")
        args.append("after: $after")
    if archive_aware:
        vars_def.append("$includeArchived: Boolean")
        args.append("includeArchived: $includeArchived")

    vars_clause = f"({', '.join(vars_def)})" if vars_def else ""
    args_clause = f"({', '.join(args)})"
    page_info = "pageInfo { hasNextPage endCursor } " if paginated else ""

    return f"query{vars_clause} {{ {connection}{args_clause} {{ {page_info}nodes {{ {fields} }} }} }}"


def build_node_query(node: str, fields: str) -> str:
    return f"query($id: String!) {{ {node}(id: $id) {{ {fields} }} }}"
