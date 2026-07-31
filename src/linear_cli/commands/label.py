from __future__ import annotations

from typing import Annotated

import typer

from ..client import emit, fail, graphql, mutate, require_fields
from ..models import LabelNode, LabelsData
from ..operations import LABEL_FIELDS, build_list_query

label_app = typer.Typer()


def _ensure_label_record(labels: list[LabelNode], name: str, parent_id: str | None, is_group: bool) -> str:
    existing = next(
        (
            label.id
            for label in labels
            if label.name == name
            and label.is_group == is_group
            and (label.parent.id if label.parent else None) == parent_id
        ),
        None,
    )
    if existing is not None:
        return existing

    fields: dict[str, object] = {"name": name}
    if is_group:
        fields["isGroup"] = True
    if parent_id is not None:
        fields["parentId"] = parent_id

    node = mutate("issueLabel", "Create", {"input": fields})
    node_id = node["id"]
    if not isinstance(node_id, str):
        fail("Linear API returned a non-string id for created label")
    return node_id


@label_app.command(name="list")
def label_list() -> None:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
    names_by_id = {label.id: label.name for label in labels}
    for label in labels:
        parent_name = names_by_id.get(label.parent.id) if label.parent else None
        emit({
            "id": label.id,
            "name": label.name,
            "color": label.color,
            "is_group": label.is_group,
            "parent": parent_name,
        })


@label_app.command(name="ensure")
def label_ensure(
    name: Annotated[str, typer.Option("--name", help="Leaf label name")],
    parent: Annotated[str | None, typer.Option("--parent", help="Parent label-group name to nest under")] = None,
) -> None:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
    parent_id = _ensure_label_record(labels, parent, None, is_group=True) if parent is not None else None
    leaf_id = _ensure_label_record(labels, name, parent_id, is_group=False)
    emit({"id": leaf_id})


@label_app.command(name="update")
def label_update(
    label_id: Annotated[str, typer.Option("--id", help="Label id to update")],
    name: Annotated[str | None, typer.Option("--name", help="New label name")] = None,
    parent: Annotated[str | None, typer.Option("--parent", help="Parent group name to reparent under")] = None,
    color: Annotated[str | None, typer.Option("--color", help="New label color as a hex string, e.g. #eb5757")] = None,
) -> None:
    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if color is not None:
        fields["color"] = color
    if parent is not None:
        query = build_list_query("issueLabels", LABEL_FIELDS)
        labels = LabelsData.model_validate(graphql(query, {})).issue_labels.nodes
        groups = [node for node in labels if node.is_group and node.name == parent]
        if len(groups) != 1:
            fail(f"Expected exactly one group named {parent!r}, found {len(groups)}")

        fields["parentId"] = groups[0].id

    require_fields(fields, "Nothing to update; pass --name, --parent, and/or --color")

    emit(mutate("issueLabel", "Update", {"id": label_id, "input": fields}))


@label_app.command(name="delete")
def label_delete(
    label_id: Annotated[str, typer.Option("--id", help="Label id to delete")],
) -> None:
    emit(mutate("issueLabel", "Delete", {"id": label_id}))
