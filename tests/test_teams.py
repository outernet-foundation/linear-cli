from __future__ import annotations

from pathlib import Path

import linear_cli.cli as cli_module
from linear_cli.cli import (
    CreatedTeam,
    CreatedWorkflowState,
    TeamCreateData,
    TeamNode,
    WorkflowStateArchiveData,
    WorkflowStateCreateData,
)


def _operations_text() -> str:
    return Path(cli_module.__file__).with_name("linear_operations.graphql").read_text(encoding="utf-8")


def test_team_node_parses_id_key_name() -> None:
    node = TeamNode.model_validate({"id": "abc", "key": "GOV", "name": "Governance"})
    assert node.id == "abc"
    assert node.key == "GOV"
    assert node.name == "Governance"


def test_created_team_parses_id_key_name() -> None:
    team = CreatedTeam.model_validate({"id": "abc", "key": "GOV", "name": "Governance"})
    assert team.id == "abc"
    assert team.key == "GOV"
    assert team.name == "Governance"


def test_team_create_data_parses_payload() -> None:
    data = TeamCreateData.model_validate({
        "teamCreate": {"success": True, "team": {"id": "abc", "key": "GOV", "name": "Governance"}}
    })
    assert data.team_create.success is True
    assert data.team_create.team is not None
    assert data.team_create.team.key == "GOV"


def test_team_create_data_parses_failed_payload_with_null_team() -> None:
    data = TeamCreateData.model_validate({"teamCreate": {"success": False, "team": None}})
    assert data.team_create.success is False
    assert data.team_create.team is None


def test_created_workflow_state_parses_id_name_type() -> None:
    state = CreatedWorkflowState.model_validate({"id": "abc", "name": "Done", "type": "completed"})
    assert state.id == "abc"
    assert state.name == "Done"
    assert state.type == "completed"


def test_workflow_state_create_data_parses_payload() -> None:
    data = WorkflowStateCreateData.model_validate({
        "workflowStateCreate": {
            "success": True,
            "workflowState": {"id": "abc", "name": "On Agenda", "type": "started"},
        }
    })
    assert data.workflow_state_create.success is True
    assert data.workflow_state_create.workflow_state is not None
    assert data.workflow_state_create.workflow_state.name == "On Agenda"


def test_workflow_state_archive_data_parses_success() -> None:
    data = WorkflowStateArchiveData.model_validate({"workflowStateArchive": {"success": True}})
    assert data.workflow_state_archive.success is True


def test_operations_document_defines_create_team_mutation() -> None:
    assert "mutation CreateTeam($input: TeamCreateInput!)" in _operations_text()


def test_operations_document_defines_create_workflow_state_mutation() -> None:
    assert "mutation CreateWorkflowState($input: WorkflowStateCreateInput!)" in _operations_text()


def test_operations_document_defines_archive_workflow_state_mutation() -> None:
    assert "mutation ArchiveWorkflowState($id: String!)" in _operations_text()


def test_operations_document_teams_query_selects_name() -> None:
    text = _operations_text()
    start = text.index("query Teams {")
    end = text.index("query Issues(")
    teams_section = text[start:end]
    assert "name" in teams_section
