from __future__ import annotations

import typer
from pydantic import Field

from ..api import build_list_query, emit, fail, graphql
from ..models import LinearModel, NodeList

USER_FIELDS = "id name displayName email active"
user_app = typer.Typer()


class UserNode(LinearModel):
    id: str
    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    active: bool = True


class UsersData(LinearModel):
    users: NodeList[UserNode]


def _all_users() -> list[UserNode]:
    query = build_list_query("users", USER_FIELDS)
    return UsersData.model_validate(graphql(query, {})).users.nodes


def _label(user: UserNode) -> str:
    return f"{user.name} <{user.email}>" if user.email else user.name


def resolve_user_id(assignee: str) -> str:
    users = _all_users()
    if any(user.id == assignee for user in users):
        return assignee

    needle = assignee.casefold()
    matches = [
        user
        for user in users
        if (user.email is not None and user.email.casefold() == needle)
        or user.name.casefold() == needle
        or (user.display_name is not None and user.display_name.casefold() == needle)
    ]
    if len(matches) != 1:
        if matches:
            available = ", ".join(sorted(_label(user) for user in matches))
            fail(f"Ambiguous assignee {assignee!r}; multiple users matched: {available}")
        available = ", ".join(sorted(_label(user) for user in users))
        fail(f"No user matching {assignee!r}; available: {available}")

    return matches[0].id


@user_app.command(name="list")
def user_list() -> None:
    for user in sorted(_all_users(), key=lambda candidate: candidate.name.casefold()):
        emit({
            "id": user.id,
            "name": user.name,
            "display_name": user.display_name,
            "email": user.email,
            "active": user.active,
        })
