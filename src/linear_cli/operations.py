from __future__ import annotations

TEAM_FIELDS = "id key name"
LABEL_FIELDS = "id name color isGroup parent { id }"
WORKFLOW_STATE_FIELDS = "id name type"
PROJECT_FIELDS = "id name url state"

ISSUE_LIST_FIELDS = (
    "id identifier title description url createdAt archivedAt "
    "state { name type } labels { nodes { name } } project { id name }"
)
ISSUE_SNAPSHOT_FIELDS = (
    "id identifier title description priority archivedAt "
    "state { name type } team { id key name } project { id name } "
    "labels { nodes { name } } comments { nodes { body createdAt user { name } } }"
)


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
