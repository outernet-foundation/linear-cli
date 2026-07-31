from __future__ import annotations

from typing import Annotated

import typer
from pydantic import Field

from ..client import emit, mutate, paginate, team_filter
from ..models import Connection, LinearModel, NodeList
from ..operations import build_list_query

_RELATIONS_FIELDS = "identifier relations { nodes { type relatedIssue { identifier } } }"

relation_app = typer.Typer()


class RelatedIssueNode(LinearModel):
    identifier: str


class IssueRelationNode(LinearModel):
    type: str
    related_issue: RelatedIssueNode | None = Field(default=None, alias="relatedIssue")


class IssueRelationsNode(LinearModel):
    identifier: str
    relations: NodeList[IssueRelationNode]


class IssueRelationsData(LinearModel):
    issues: Connection[IssueRelationsNode]


@relation_app.command(name="list")
def relation_list(
    team: Annotated[str | None, typer.Option("--team", help="Team key to filter by, e.g. PLE")] = None,
) -> None:
    query = build_list_query("issues", _RELATIONS_FIELDS, filter_type="IssueFilter", paginated=True)
    for issue_node in paginate(query, {"filter": team_filter(team)}, IssueRelationsData, lambda data: data.issues):
        for relation in issue_node.relations.nodes:
            if relation.related_issue is None:
                continue

            emit({"source": issue_node.identifier, "target": relation.related_issue.identifier, "type": relation.type})


@relation_app.command(name="create")
def relation_create(
    blocker: Annotated[str, typer.Option("--blocker", help="Issue id that does the blocking")],
    blocked: Annotated[str, typer.Option("--blocked", help="Issue id that is blocked")],
) -> None:
    fields: dict[str, object] = {"issueId": blocker, "relatedIssueId": blocked, "type": "blocks"}
    mutate("issueRelation", "Create", {"input": fields})
    emit({"blocker": blocker, "blocked": blocked, "type": "blocks"})
