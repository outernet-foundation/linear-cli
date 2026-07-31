from __future__ import annotations

from linear_cli.client import DELETE_VERBS, RESOURCES, build_mutation
from linear_cli.models import TeamNode
from linear_cli.operations import (
    ISSUE_LIST_FIELDS,
    LABEL_FIELDS,
    TEAM_FIELDS,
    build_list_query,
)


def test_team_node_parses_id_key_name() -> None:
    node = TeamNode.model_validate({"id": "abc", "key": "GOV", "name": "Governance"})
    assert node.id == "abc"
    assert node.key == "GOV"
    assert node.name == "Governance"


def test_build_create_mutation_for_team() -> None:
    mutation = build_mutation("team", "Create")
    assert "teamCreate(input: $input)" in mutation
    assert "TeamCreateInput!" in mutation
    assert "success team { id key name }" in mutation


def test_build_update_mutation_for_issue() -> None:
    mutation = build_mutation("issue", "Update")
    assert "issueUpdate(id: $id, input: $input)" in mutation
    assert "IssueUpdateInput!" in mutation
    assert "success issue { id identifier url }" in mutation


def test_build_delete_mutation_for_project() -> None:
    mutation = build_mutation("project", "Delete")
    assert "projectDelete(id: $id)" in mutation
    assert "success" in mutation
    assert "project {" not in mutation


def test_build_archive_mutation_for_workflow_state() -> None:
    mutation = build_mutation("workflowState", "Archive")
    assert "workflowStateArchive(id: $id)" in mutation
    assert "success" in mutation
    assert "workflowState {" not in mutation


def test_build_create_mutation_for_relation_has_no_node() -> None:
    mutation = build_mutation("issueRelation", "Create")
    assert "issueRelationCreate(input: $input)" in mutation
    assert "IssueRelationCreateInput!" in mutation
    assert "success }" in mutation


def test_build_unarchive_mutation_for_issue() -> None:
    mutation = build_mutation("issue", "Unarchive")
    assert "issueUnarchive(id: $id)" in mutation
    assert "success }" in mutation


def test_build_list_query_simple() -> None:
    query = build_list_query("teams", TEAM_FIELDS)
    assert "teams(first: 250)" in query
    assert "nodes { id key name }" in query
    assert "pageInfo" not in query
    assert "$filter" not in query


def test_build_list_query_paginated_filtered() -> None:
    query = build_list_query("issues", ISSUE_LIST_FIELDS, filter_type="IssueFilter", paginated=True, archive_aware=True)
    assert "$filter: IssueFilter" in query
    assert "$after: String" in query
    assert "$includeArchived: Boolean" in query
    assert "pageInfo { hasNextPage endCursor }" in query
    assert "filter: $filter" in query
    assert "includeArchived: $includeArchived" in query


def test_build_list_query_labels() -> None:
    query = build_list_query("issueLabels", LABEL_FIELDS)
    assert "issueLabels(first: 250)" in query
    assert "pageInfo" not in query


def test_delete_verbs_mapping() -> None:
    assert DELETE_VERBS["Delete"] == "deleted"
    assert DELETE_VERBS["Archive"] == "archived"
    assert DELETE_VERBS["Unarchive"] == "unarchived"


def test_resources_cover_all_nouns() -> None:
    expected = {"team", "issue", "project", "issueLabel", "workflowState", "comment", "issueRelation"}
    assert set(RESOURCES) == expected


def test_resources_return_fields_match_expected() -> None:
    assert RESOURCES["team"].return_fields == "id key name"
    assert RESOURCES["workflowState"].return_fields == "id name type"
    assert RESOURCES["project"].return_fields == "id url"
    assert RESOURCES["issue"].return_fields == "id identifier url"
    assert not RESOURCES["issueRelation"].return_fields
