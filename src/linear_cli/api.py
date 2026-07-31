from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import NoReturn

import httpx
import typer
from pydantic import TypeAdapter, ValidationError

from .models import Connection, LinearModel, ResponsePayload
from .profiles import CONFIG_PATH, ProfileConfig, load_config, resolve_profile_name

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
_dict_adapter = TypeAdapter(dict[str, object])

DELETE_VERBS: dict[str, str] = {
    "Delete": "deleted",
    "Archive": "archived",
    "Unarchive": "unarchived",
}


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


class CliState:
    profile_override: str | None = None


def mutate(noun: str, verb: str, variables: dict[str, object]) -> dict[str, object]:
    query = build_mutation(noun, verb)
    data = graphql(query, variables)
    field = f"{noun}{verb}"
    result = _expect_dict(data.get(field))
    if not result.get("success"):
        fail(f"Linear API mutation {field} failed")

    if verb in DELETE_VERBS:
        return {"id": variables["id"], DELETE_VERBS[verb]: True}

    resource = RESOURCES[noun]
    if not resource.return_fields:
        return {}

    return _expect_dict(result.get(resource.node))


def paginate[T: LinearModel, NodeT](
    query: str,
    variables: dict[str, object],
    model: type[T],
    select: Callable[[T], Connection[NodeT]],
) -> Iterator[NodeT]:
    after: str | None = None
    while True:
        connection = select(model.model_validate(graphql(query, {**variables, "after": after})))
        yield from connection.nodes
        if not connection.page_info.has_next_page:
            break

        after = connection.page_info.end_cursor


def require_fields(fields: dict[str, object], message: str) -> None:
    if not fields:
        fail(message)


def graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
    response = httpx.post(
        LINEAR_ENDPOINT,
        headers={
            "Authorization": _load_config_or_die().root[resolved_profile_name()].api_key,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables},
        timeout=30.0,
    )
    try:
        payload = ResponsePayload.model_validate_json(response.content).root
    except ValidationError:
        fail(f"Linear API returned a malformed response (HTTP {response.status_code}): {response.text[:200]}")

    errors = payload.get("errors")
    if errors:
        fail(f"Linear API error: {json.dumps(errors)}")

    data = payload.get("data")
    if data is None:
        fail(f"Linear API returned no data (HTTP {response.status_code})")

    return _expect_dict(data)


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


def resolved_profile_name() -> str:
    return resolve_profile_name(_load_config_or_die(), CliState.profile_override, Path.cwd())


def emit(record: dict[str, object]) -> None:
    typer.echo(json.dumps(record))


def team_filter(team: str | None) -> dict[str, object]:
    return {"team": {"key": {"eq": team}}} if team is not None else {}


def read_stdin() -> str:
    return sys.stdin.read() if not sys.stdin.isatty() else ""


def _expect_dict(value: object | None) -> dict[str, object]:
    try:
        return _dict_adapter.validate_python(value)
    except ValidationError:
        fail("Linear API returned an unexpected response shape")


@cache
def _load_config_or_die() -> ProfileConfig:
    config = load_config()
    if config is None:
        fail(f"No profile config found at {CONFIG_PATH}; create one with profiles and path_defaults.")
    return config


def _pascal(noun: str) -> str:
    return noun[0].upper() + noun[1:]


def fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)
