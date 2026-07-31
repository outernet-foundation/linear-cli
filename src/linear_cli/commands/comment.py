from __future__ import annotations

from typing import Annotated

import typer

from ..client import emit, fail, mutate, read_stdin

comment_app = typer.Typer()


@comment_app.command(name="create", help="Reads the comment body (markdown) from stdin. Required.")
def comment_create(
    issue_id: Annotated[str, typer.Option("--issue", help="Issue id to comment on")],
) -> None:
    body = read_stdin()
    if not body.strip():
        fail("No comment body on stdin")

    emit(mutate("comment", "Create", {"input": {"issueId": issue_id, "body": body}}))


@comment_app.command(name="delete")
def comment_delete(
    comment_id: Annotated[str, typer.Option("--id", help="Comment id to delete")],
) -> None:
    emit(mutate("comment", "Delete", {"id": comment_id}))
