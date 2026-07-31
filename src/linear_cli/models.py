from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel


class LinearModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PageInfo(LinearModel):
    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class Connection[NodeT](LinearModel):
    page_info: PageInfo = Field(alias="pageInfo")
    nodes: list[NodeT]


class _NodeList[NodeT](LinearModel):
    nodes: list[NodeT]


class TeamNode(LinearModel):
    id: str
    key: str
    name: str


class IssueStateNode(LinearModel):
    name: str
    type: str


class IssueLabelName(LinearModel):
    name: str


class ProjectRef(LinearModel):
    id: str
    name: str


class IssueListNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    labels: _NodeList[IssueLabelName]
    project: ProjectRef | None = None


class AttachmentNode(LinearModel):
    id: str
    title: str | None = None
    subtitle: str | None = None
    url: str
    metadata: dict[str, object] | None = None


class LabelIdRef(LinearModel):
    id: str


class IssueDetailNode(LinearModel):
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: _NodeList[LabelIdRef] = Field(default_factory=lambda: _NodeList(nodes=[]))
    attachments: _NodeList[AttachmentNode]


class ProjectListNode(LinearModel):
    id: str
    name: str
    url: str
    state: str


class RelatedIssueNode(LinearModel):
    identifier: str


class IssueRelationNode(LinearModel):
    type: str
    related_issue: RelatedIssueNode | None = Field(default=None, alias="relatedIssue")


class IssueRelationsNode(LinearModel):
    identifier: str
    relations: _NodeList[IssueRelationNode]


class CommentUserNode(LinearModel):
    name: str


class IssueSnapshotCommentNode(LinearModel):
    body: str | None = None
    created_at: str = Field(alias="createdAt")
    user: CommentUserNode | None = None


class IssueSnapshotNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int = 0
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: _NodeList[IssueLabelName]
    comments: _NodeList[IssueSnapshotCommentNode]


class WorkflowStateNode(LinearModel):
    id: str
    name: str
    type: str


class LabelParent(LinearModel):
    id: str


class LabelNode(LinearModel):
    id: str
    name: str
    color: str | None = None
    is_group: bool = Field(default=False, alias="isGroup")
    parent: LabelParent | None = None


class CreatedLabel(LinearModel):
    id: str
    name: str


class CreatedProject(LinearModel):
    id: str
    url: str


class CreatedTeam(LinearModel):
    id: str
    key: str
    name: str


class CreatedWorkflowState(LinearModel):
    id: str
    name: str
    type: str


class CreatedIssue(LinearModel):
    id: str
    identifier: str
    url: str


class CommentNode(LinearModel):
    id: str
    url: str


class SuccessPayload(LinearModel):
    success: bool


class IssueLabelMutationPayload(LinearModel):
    success: bool
    issue_label: CreatedLabel | None = Field(default=None, alias="issueLabel")


class ProjectMutationPayload(LinearModel):
    success: bool
    project: CreatedProject | None = None


class TeamMutationPayload(LinearModel):
    success: bool
    team: CreatedTeam | None = None


class WorkflowStateMutationPayload(LinearModel):
    success: bool
    workflow_state: CreatedWorkflowState | None = Field(default=None, alias="workflowState")


class IssueMutationPayload(LinearModel):
    success: bool
    issue: CreatedIssue | None = None


class CommentCreatePayload(LinearModel):
    success: bool
    comment: CommentNode | None = None


class TeamsData(LinearModel):
    teams: _NodeList[TeamNode]


class IssuesData(LinearModel):
    issues: Connection[IssueListNode]


class IssueDetailData(LinearModel):
    issue: IssueDetailNode


class ProjectsData(LinearModel):
    projects: Connection[ProjectListNode]


class IssueRelationsData(LinearModel):
    issues: Connection[IssueRelationsNode]


class IssueSnapshotData(LinearModel):
    issues: Connection[IssueSnapshotNode]


class IssueSnapshotByIdData(LinearModel):
    issue: IssueSnapshotNode


class WorkflowStatesData(LinearModel):
    workflow_states: _NodeList[WorkflowStateNode] = Field(alias="workflowStates")


class LabelsData(LinearModel):
    issue_labels: _NodeList[LabelNode] = Field(alias="issueLabels")


class IssueLabelCreateData(LinearModel):
    issue_label_create: IssueLabelMutationPayload = Field(alias="issueLabelCreate")


class IssueLabelUpdateData(LinearModel):
    issue_label_update: IssueLabelMutationPayload = Field(alias="issueLabelUpdate")


class IssueLabelDeleteData(LinearModel):
    issue_label_delete: SuccessPayload = Field(alias="issueLabelDelete")


class ProjectCreateData(LinearModel):
    project_create: ProjectMutationPayload = Field(alias="projectCreate")


class TeamCreateData(LinearModel):
    team_create: TeamMutationPayload = Field(alias="teamCreate")


class TeamUpdateData(LinearModel):
    team_update: TeamMutationPayload = Field(alias="teamUpdate")


class WorkflowStateCreateData(LinearModel):
    workflow_state_create: WorkflowStateMutationPayload = Field(alias="workflowStateCreate")


class WorkflowStateArchiveData(LinearModel):
    workflow_state_archive: SuccessPayload = Field(alias="workflowStateArchive")


class ProjectUpdateData(LinearModel):
    project_update: ProjectMutationPayload = Field(alias="projectUpdate")


class ProjectDeleteData(LinearModel):
    project_delete: SuccessPayload = Field(alias="projectDelete")


class IssueCreateData(LinearModel):
    issue_create: IssueMutationPayload = Field(alias="issueCreate")


class IssueUpdateData(LinearModel):
    issue_update: IssueMutationPayload = Field(alias="issueUpdate")


class IssueRelationCreateData(LinearModel):
    issue_relation_create: SuccessPayload = Field(alias="issueRelationCreate")


class CommentCreateData(LinearModel):
    comment_create: CommentCreatePayload = Field(alias="commentCreate")


class CommentDeleteData(LinearModel):
    comment_delete: SuccessPayload = Field(alias="commentDelete")


class IssueUnarchiveData(LinearModel):
    issue_unarchive: SuccessPayload = Field(alias="issueUnarchive")


class ResponsePayload(RootModel[dict[str, object]]):
    root: dict[str, object]
