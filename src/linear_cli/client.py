from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
from typing import NoReturn

import httpx
import typer
from pydantic import TypeAdapter, ValidationError

from .models import Connection, LinearModel, ResponsePayload
from .operations import DELETE_VERBS, RESOURCES, build_mutation
from .profiles import CONFIG_PATH, ProfileConfig, load_config, resolve_profile_name

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
_dict_adapter = TypeAdapter(dict[str, object])


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


def resolved_profile_name() -> str:
    return resolve_profile_name(_load_config_or_die(), CliState.profile_override, Path.cwd())


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


def fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)
