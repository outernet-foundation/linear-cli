from __future__ import annotations

import pytest
import typer

from linear_cli.api import build_list_query
from linear_cli.nouns.user import USER_FIELDS, UserNode, resolve_user_id

_USERS: list[dict[str, object]] = [
    {"id": "u-1", "name": "Joshua Revzin", "displayName": "Josh Revzin", "email": "josh@example.com", "active": True},
    {"id": "u-2", "name": "Tyler Hatch", "displayName": "Tyler", "email": "tyler@example.com", "active": True},
]


def _patch_graphql(monkeypatch: pytest.MonkeyPatch, users: list[dict[str, object]] | None = None) -> None:
    payload = list(users if users is not None else _USERS)

    def _impl(_query: str, _variables: dict[str, object]) -> dict[str, object]:
        return {"users": {"nodes": payload}}

    monkeypatch.setattr("linear_cli.nouns.user.graphql", _impl)


def test_user_node_parses() -> None:
    node = UserNode.model_validate(_USERS[0])
    assert node.id == "u-1"
    assert node.name == "Joshua Revzin"
    assert node.display_name == "Josh Revzin"
    assert node.email == "josh@example.com"
    assert node.active


def test_build_list_query_users() -> None:
    query = build_list_query("users", USER_FIELDS)
    assert "users(first: 250)" in query
    assert "nodes { id name displayName email active }" in query
    assert "pageInfo" not in query


def test_resolve_user_id_by_email(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    assert resolve_user_id("josh@example.com") == "u-1"


def test_resolve_user_id_email_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    assert resolve_user_id("JOSH@EXAMPLE.COM") == "u-1"


def test_resolve_user_id_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    assert resolve_user_id("Tyler Hatch") == "u-2"


def test_resolve_user_id_by_display_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    assert resolve_user_id("Josh Revzin") == "u-1"


def test_resolve_user_id_by_raw_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    assert resolve_user_id("u-2") == "u-2"


def test_resolve_user_id_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    users: list[dict[str, object]] = [
        {"id": "u-a", "name": "Sam", "displayName": None, "email": "a@x.com", "active": True},
        {"id": "u-b", "name": "Sam", "displayName": None, "email": "b@x.com", "active": True},
    ]
    _patch_graphql(monkeypatch, users)
    with pytest.raises(typer.Exit):
        resolve_user_id("Sam")


def test_resolve_user_id_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graphql(monkeypatch)
    with pytest.raises(typer.Exit):
        resolve_user_id("nobody@example.com")
